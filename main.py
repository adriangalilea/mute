#!/usr/bin/env python3

import os
import sys
import signal
import atexit
import rumps
import subprocess
import shutil
import socket
import threading
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Set, Dict
from configparser import ConfigParser
from py_utils import xdg

TEMPLATE_PATH = Path(__file__).parent / "sites.ini.template"
SITES_INI_PATH = xdg.config / "mute" / "sites.ini"
STATE_PATH = xdg.state / "mute" / "session.json"
PFCTL_ANCHOR = "mute"
PF_RULES_PATH = Path("/etc/pf.anchors/mute")
PF_CONF = Path("/etc/pf.conf")


def validate_domain(domain: str) -> str:
    """Validate and clean domain format"""
    # Remove protocols
    if '://' in domain:
        raise ValueError(f"Invalid domain '{domain}': Remove protocol (http://, https://)")

    # Remove paths
    if '/' in domain:
        raise ValueError(f"Invalid domain '{domain}': Remove paths (everything after /)")

    # Basic format check
    if not domain or '.' not in domain:
        raise ValueError(f"Invalid domain '{domain}': Must be a valid domain name")

    return domain.lower()


def load_groups() -> Dict[str, List[str]]:
    """Load domain groups from INI config"""
    # Get actual user's UID/GID (not root when running with sudo)
    actual_uid = int(os.environ.get('SUDO_UID', os.getuid()))
    actual_gid = int(os.environ.get('SUDO_GID', os.getgid()))

    # Ensure config directory exists with correct ownership
    if not SITES_INI_PATH.parent.exists():
        SITES_INI_PATH.parent.mkdir(parents=True, exist_ok=True)
        os.chown(SITES_INI_PATH.parent, actual_uid, actual_gid)

    # Copy template to user config on first run
    if not SITES_INI_PATH.exists():
        if TEMPLATE_PATH.exists():
            print(f"📋 First run: copying sites template to {SITES_INI_PATH}")
            shutil.copy2(TEMPLATE_PATH, SITES_INI_PATH)
        else:
            print(f"⚠️  Template not found, creating minimal config at {SITES_INI_PATH}")
            minimal_cfg = ConfigParser(allow_no_value=True)
            minimal_cfg['social'] = {
                'twitter.com': None,
                'facebook.com': None,
                'reddit.com': None
            }
            with open(SITES_INI_PATH, 'w') as f:
                minimal_cfg.write(f)

        # Fix ownership so user can edit
        os.chown(SITES_INI_PATH, actual_uid, actual_gid)

    # Load groups from INI
    cfg = ConfigParser(allow_no_value=True)
    cfg.read(SITES_INI_PATH)

    groups = {}
    errors = []
    total_domains = 0

    for section in cfg.sections():
        domains = []
        for domain in cfg[section].keys():
            try:
                validated = validate_domain(domain)
                domains.append(validated)
                total_domains += 1
            except ValueError as e:
                errors.append(f"[{section}] {e}")

        if domains:
            groups[section] = domains

    # Report errors but continue with valid domains
    if errors:
        print(f"⚠️ Sites: skipped {len(errors)} invalid entries")
        for error in errors:
            print(f"   {error}")
        print()  # Blank line

    assert len(groups) > 0, f"No valid groups in config: {SITES_INI_PATH}"
    assert total_domains > 0, f"No valid domains in any group: {SITES_INI_PATH}"

    print(f"✅ Sites: loaded {total_domains} domains from {len(groups)} groups")
    return groups


def save_state(active: bool, session_type: str, start_time: datetime,
               end_time: Optional[datetime], blocked_groups: List[str]):
    """Save session state to XDG state directory"""
    # Get actual user's UID/GID (not root when running with sudo)
    actual_uid = int(os.environ.get('SUDO_UID', os.getuid()))
    actual_gid = int(os.environ.get('SUDO_GID', os.getgid()))

    # Ensure state directory exists
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.chown(STATE_PATH.parent, actual_uid, actual_gid)

    state = {
        "active": active,
        "session_type": session_type,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat() if end_time else None,
        "blocked_groups": blocked_groups
    }

    STATE_PATH.write_text(json.dumps(state, indent=2))
    os.chown(STATE_PATH, actual_uid, actual_gid)


def load_state() -> Optional[Dict]:
    """Load session state from XDG state directory"""
    if not STATE_PATH.exists():
        return None

    try:
        state = json.loads(STATE_PATH.read_text())
        # Parse ISO timestamps back to datetime
        if state.get("start_time"):
            state["start_time"] = datetime.fromisoformat(state["start_time"])
        if state.get("end_time"):
            state["end_time"] = datetime.fromisoformat(state["end_time"])
        return state
    except Exception as e:
        print(f"⚠️  Failed to load state: {e}")
        return None


def clear_state():
    """Clear session state file"""
    if STATE_PATH.exists():
        STATE_PATH.unlink()


# Global app instance for cleanup
app_instance = None


def check_sudo():
    """Check if running with sudo privileges"""
    # TODO: v1 - implement proper privilege escalation:
    #   - Privileged helper tool with XPC communication
    #   - Authorization Services API
    #   - or launchd daemon with proper entitlements
    if os.geteuid() != 0:
        print("❌ Mute requires sudo privileges to modify pfctl rules")
        print("\nUsage: sudo -E uv run python main.py")
        print("   or: sudo -E python main.py")
        sys.exit(1)


def remove_pfctl_rules():
    """Remove pfctl blocking rules - used for cleanup"""
    try:
        # Flush all rules in mute anchor
        subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-F", "all"],
                      capture_output=True, check=False)
        # Try to disable pfctl (may fail if other rules exist, that's ok)
        subprocess.run(["pfctl", "-d"], capture_output=True, check=False)
    except Exception as e:
        print(f"⚠️  Failed to remove pfctl rules: {e}")


def cleanup_handler():
    """Cleanup function called on exit"""
    global app_instance
    if app_instance and app_instance.is_muted:
        # Check if this is a forever session
        state = load_state()
        if state and state.get("session_type") == "forever":
            print("\n⚠️  Forever session - blocks remain active")
            print("   (Restart app to manage session)")
            # Stop refresh thread only, leave pfctl rules in place
            if app_instance.refresh_thread and app_instance.refresh_thread.is_alive():
                app_instance.stop_refresh = True
            return

        # Timed/until_tomorrow sessions: cleanup normally
        print("\n🧹 Cleaning up...")
        remove_pfctl_rules()
        # Stop refresh thread if running
        if app_instance.refresh_thread and app_instance.refresh_thread.is_alive():
            app_instance.stop_refresh = True


def signal_handler(sig, frame):
    """Handle signals for clean exit"""
    print(f"\n📍 Received signal {sig}")
    cleanup_handler()
    sys.exit(0)


# Register cleanup handlers
atexit.register(cleanup_handler)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
try:
    signal.signal(signal.SIGHUP, signal_handler)
except:
    pass  # SIGHUP might not be available


class MuteApp(rumps.App):
    def __init__(self):
        super().__init__("Mute", quit_button=None)

        # Copy Info.plist to where rumps expects it for notifications
        self._setup_plist()
        self.timer = None
        self.end_time: Optional[datetime] = None
        self.is_muted = False

        # Threading for periodic IP refresh
        self.refresh_thread: Optional[threading.Thread] = None
        self.stop_refresh = False
        self.current_domains: List[str] = []

        # Store global reference for cleanup
        global app_instance
        app_instance = self

        # Setup menu - all items always present to avoid layout shift
        self.menu = [
            rumps.MenuItem("Quick Focus", callback=None),
            rumps.separator,
            rumps.MenuItem("25 minutes", callback=self.start_25),
            rumps.MenuItem("1 hour", callback=self.start_60),
            rumps.MenuItem("2 hours", callback=self.start_120),
            rumps.MenuItem("Until tomorrow", callback=self.start_until_tomorrow),
            rumps.MenuItem("Forever", callback=self.start_forever),
            rumps.separator,
            rumps.MenuItem("End Session", callback=None),  # Greyed out initially
            rumps.separator,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        self._update_menu_state()

        # Validate sites config on startup
        try:
            load_groups()
        except Exception as e:
            print(f"❌ Sites config error: {e}")

        # Check if already muted on startup
        self._check_existing_mute()

    def _update_menu_state(self):
        """Update menu item states based on mute status"""
        if self.is_muted:
            # During session: disable start options, enable end
            self.menu["25 minutes"].set_callback(None)
            self.menu["1 hour"].set_callback(None)
            self.menu["2 hours"].set_callback(None)
            self.menu["Until tomorrow"].set_callback(None)
            self.menu["Forever"].set_callback(None)
            self.menu["End Session"].set_callback(self.end_session)
        else:
            # Not in session: enable start options, disable end
            self.menu["25 minutes"].set_callback(self.start_25)
            self.menu["1 hour"].set_callback(self.start_60)
            self.menu["2 hours"].set_callback(self.start_120)
            self.menu["Until tomorrow"].set_callback(self.start_until_tomorrow)
            self.menu["Forever"].set_callback(self.start_forever)
            self.menu["End Session"].set_callback(None)

    def _setup_plist(self):
        """Setup Info.plist for notifications to work"""
        try:
            # Copy our Info.plist to where Python executable expects it
            import shutil
            plist_source = Path(__file__).parent / "Info.plist"
            plist_dest = Path(sys.executable).parent / "Info.plist"

            if plist_source.exists() and not plist_dest.exists():
                shutil.copy2(plist_source, plist_dest)
        except:
            pass  # Notifications won't work but app will still function

    def _check_existing_mute(self):
        """Check state and restore session or cleanup leftover rules"""
        state = load_state()

        if state and state.get("active"):
            # Session was active when app quit - restore it
            print("🔄 Restoring session from previous run...")
            self._restore_session(state)
        else:
            # No active session - cleanup any leftover pfctl rules
            try:
                result = subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-s", "rules"],
                                       capture_output=True, text=True, check=False)
                if result.stdout.strip():
                    print("🧹 Cleaning up leftover pfctl rules...")
                    remove_pfctl_rules()
                    clear_state()  # Clean up stale state too
            except Exception as e:
                print(f"⚠️  Could not check pfctl rules: {e}")

    def _restore_session(self, state: Dict):
        """Restore session from saved state"""
        try:
            # Restore session variables
            self.is_muted = True
            self.title = "🔇 Mute"
            self.end_time = state.get("end_time")
            session_type = state.get("session_type", "timed")

            # Re-apply blocks (rules already exist in pfctl from previous run)
            # Load current domains for refresh thread
            groups = load_groups()
            domains = []
            for group_domains in groups.values():
                domains.extend(group_domains)
            self.current_domains = domains

            # Update menu state
            self._update_menu_state()

            # Restart IP refresh thread
            self._start_refresh_thread()

            # Restart timer if needed
            if session_type == "forever":
                # No timer for forever sessions
                print("✅ Session restored (forever)")
            elif self.end_time:
                if datetime.now() >= self.end_time:
                    # Session expired while app was closed
                    print("⏰ Session expired, ending...")
                    self.end_session(None)
                    return

                # Session still active, restart timer
                if session_type == "until_tomorrow":
                    self.timer = rumps.Timer(self.update_timer, 60)
                else:
                    self.timer = rumps.Timer(self.update_timer, 1)
                self.timer.start()

                print(f"✅ Session restored ({session_type})")
        except Exception as e:
            print(f"❌ Failed to restore session: {e}")
            self.end_session(None)

    def _resolve_domains_to_ips(self, domains: List[str]) -> Set[str]:
        """Resolve domains to IP addresses (both IPv4 and IPv6)"""
        ips = set()
        failed = []
        for domain in domains:
            try:
                # Get all address info (IPv4 and IPv6)
                results = socket.getaddrinfo(domain, None)
                for result in results:
                    ip = result[4][0]
                    # Filter out IPv6 link-local addresses
                    if not ip.startswith("fe80:"):
                        ips.add(ip)
            except socket.gaierror:
                failed.append(domain)
            except Exception as e:
                failed.append(f"{domain} ({e})")

        if failed:
            print(f"⚠️  Could not resolve {len(failed)} domains: {', '.join(failed)}")

        return ips

    def _ensure_pf_anchor_config(self):
        """Ensure pf.conf loads our anchor (one-time setup)"""
        pf_conf_content = PF_CONF.read_text()
        anchor_line = f"anchor \"{PFCTL_ANCHOR}\""

        if anchor_line not in pf_conf_content:
            print("⚙️  First run: configuring pfctl anchor...")
            # Add anchor after dummynet-anchor, before filtering anchors
            # Order: scrub > nat > rdr > dummynet > [OUR ANCHOR] > filtering
            lines = pf_conf_content.split('\n')
            insert_pos = len(lines)

            # Try to insert after dummynet-anchor
            for i, line in enumerate(lines):
                if line.strip().startswith("dummynet-anchor"):
                    insert_pos = i + 1
                    break
            else:
                # Fallback: insert before first filtering anchor
                for i, line in enumerate(lines):
                    if line.strip().startswith("anchor "):
                        insert_pos = i
                        break

            lines.insert(insert_pos, anchor_line)
            PF_CONF.write_text('\n'.join(lines))

            # Verify anchor was written
            updated_content = PF_CONF.read_text()
            assert anchor_line in updated_content, "Failed to add anchor to pf.conf"

            # Reload pf.conf to activate anchor
            subprocess.run(["pfctl", "-f", str(PF_CONF)], capture_output=True, check=True)

    def _apply_blocks(self) -> bool:
        """Apply pfctl blocking rules"""
        assert not self.is_muted, "Already muted"

        # Ensure pf.conf has our anchor configured
        self._ensure_pf_anchor_config()

        # Load groups and flatten to domains
        groups = load_groups()
        domains = []
        for group_domains in groups.values():
            domains.extend(group_domains)
        self.current_domains = domains

        ips = self._resolve_domains_to_ips(domains)
        assert len(ips) > 0, f"Failed to resolve any domains to IPs (checked {len(domains)} domains)"

        print(f"🔇 Blocking {len(domains)} domains ({len(ips)} IPs)")

        # Ensure anchor directory exists
        PF_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Generate pfctl rules
        rules = [
            f"# Mute blocking rules - generated at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Blocking {len(domains)} domains ({len(ips)} unique IPs)",
            "",
        ]
        for ip in sorted(ips):
            rules.append(f"block drop quick from any to {ip}")

        # Write rules to anchor file
        PF_RULES_PATH.write_text("\n".join(rules) + "\n")

        # Load rules into pfctl
        subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-f", str(PF_RULES_PATH)],
                      capture_output=True, check=True)
        # Enable pfctl
        subprocess.run(["pfctl", "-e"], capture_output=True, check=False)

        # Verify it worked
        verified = self._verify_blocks()
        assert verified, "pfctl rules loaded but verification failed"

        return True

    def _remove_blocks(self) -> bool:
        """Remove pfctl blocking rules"""
        assert self.is_muted, "Not muted"

        # Stop refresh thread
        if self.refresh_thread and self.refresh_thread.is_alive():
            self.stop_refresh = True
            self.refresh_thread.join(timeout=2)

        try:
            subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-F", "all"],
                          capture_output=True, check=True)
            print("✅ Removed pfctl blocking rules")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to remove pfctl rules: {e.stderr.decode()}")
            return False

    def _verify_blocks(self) -> bool:
        """Verify pfctl rules work by functional test"""
        import re

        # Check rules exist in anchor
        result = subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-s", "rules"],
                               capture_output=True, text=True, check=True)

        lines = result.stdout.split('\n')
        rule_count = len([line for line in lines
                         if line.strip() and line.startswith('block drop quick')])

        assert rule_count > 0, "No blocking rules found in anchor"

        # Functional test: Try to connect to blocked IP, should timeout
        first_rule = next((line for line in lines if line.startswith('block drop quick')), None)
        assert first_rule, "No block rules found"

        # Extract IP from rule like "block drop quick inet from any to 172.66.0.227"
        match = re.search(r'to (\S+)$', first_rule)
        assert match, "Could not parse IP from rule"

        test_ip = match.group(1)

        # IPv6 addresses need brackets in URLs
        if ':' in test_ip:
            test_url = f"http://[{test_ip}]"
        else:
            test_url = f"http://{test_ip}"

        # Try to connect - should timeout or fail
        result = subprocess.run(
            ["curl", "-m", "2", "--connect-timeout", "2", test_url],
            capture_output=True
        )

        # Exit codes: 7 = failed to connect, 28 = timeout, 3 = URL malformed (IPv6 edge case)
        assert result.returncode in [7, 28, 3], \
            f"Blocking failed - connection succeeded (exit code {result.returncode})"

        return True

    def _start_refresh_thread(self):
        """Start background thread to refresh IPs every 15 minutes"""
        def refresh_loop():
            while not self.stop_refresh:
                # Sleep for 15 minutes (900 seconds), checking every second for stop signal
                for _ in range(900):
                    if self.stop_refresh:
                        return
                    time.sleep(1)

                if not self.stop_refresh and self.is_muted:
                    print("🔄 Refreshing IP addresses...")
                    ips = self._resolve_domains_to_ips(self.current_domains)
                    if ips:
                        # Regenerate rules
                        rules = [
                            f"# Mute blocking rules - refreshed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                            f"# Blocking {len(self.current_domains)} domains ({len(ips)} unique IPs)",
                            "",
                        ]
                        for ip in sorted(ips):
                            rules.append(f"block drop quick from any to {ip}")

                        try:
                            PF_RULES_PATH.write_text("\n".join(rules) + "\n")
                            subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-f", str(PF_RULES_PATH)],
                                         capture_output=True, check=True)
                            print(f"✅ Refreshed {len(ips)} IP addresses")
                        except Exception as e:
                            print(f"⚠️  Failed to refresh rules: {e}")

        self.stop_refresh = False
        self.refresh_thread = threading.Thread(target=refresh_loop, daemon=True)
        self.refresh_thread.start()
        print("🔄 Started IP refresh thread (15 min interval)")

    def _start_session(self, minutes: Optional[int] = None, session_type: Optional[str] = None):
        """Start a focus session"""
        if self.is_muted:
            rumps.alert("Already Focused", "End current session first")
            return

        # Apply pfctl blocks
        if not self._apply_blocks():
            rumps.alert("Error", "Failed to apply blocks")
            return

        self.is_muted = True
        self.title = "🔇 Mute"
        self._update_menu_state()

        # Start background IP refresh thread
        self._start_refresh_thread()

        # Determine session type and times
        start_time = datetime.now()

        # Handle different session types
        if session_type == "forever":
            # Forever blocking - no end time, no timer
            self.end_time = None
            try:
                rumps.notification("Focus Started", "", "Muting forever")
            except:
                print("✅ Focus started forever (manual stop only)")
        elif minutes:
            # Timed session
            session_type = "timed"
            self.end_time = start_time + timedelta(minutes=minutes)
            if self.timer:
                self.timer.stop()
            self.timer = rumps.Timer(self.update_timer, 1)
            self.timer.start()
            try:
                rumps.notification("Focus Started", "", f"Muting for {minutes} minutes")
            except:
                print(f"✅ Focus started for {minutes} minutes")
        else:
            # Until tomorrow
            session_type = "until_tomorrow"
            try:
                rumps.notification("Focus Started", "", "Muting until tomorrow")
            except:
                print("✅ Focus started until tomorrow")
            # Set end time to 4 AM tomorrow
            tomorrow = start_time + timedelta(days=1)
            self.end_time = tomorrow.replace(hour=4, minute=0, second=0, microsecond=0)
            if self.timer:
                self.timer.stop()
            self.timer = rumps.Timer(self.update_timer, 60)  # Check every minute
            self.timer.start()

        # Save session state
        groups = load_groups()
        save_state(
            active=True,
            session_type=session_type,
            start_time=start_time,
            end_time=self.end_time,
            blocked_groups=list(groups.keys())
        )

    @rumps.timer(1)
    def update_timer(self, _):
        """Update timer display"""
        if not self.end_time or not self.is_muted:
            if self.timer:
                self.timer.stop()
            return

        now = datetime.now()
        if now >= self.end_time:
            self.end_session(None)
        else:
            remaining = self.end_time - now
            hours = int(remaining.total_seconds() // 3600)
            minutes = int((remaining.total_seconds() % 3600) // 60)
            seconds = int(remaining.total_seconds() % 60)

            if hours > 0:
                self.title = f"🔇 {hours:02d}:{minutes:02d}"
            else:
                self.title = f"🔇 {minutes:02d}:{seconds:02d}"

    def start_25(self, _):
        self._start_session(25)

    def start_60(self, _):
        self._start_session(60)

    def start_120(self, _):
        self._start_session(120)

    def start_until_tomorrow(self, _):
        self._start_session()

    def start_forever(self, _):
        self._start_session(session_type="forever")

    def end_session(self, _):
        """End the current focus session"""
        if not self.is_muted:
            return

        print("🛑 Ending focus session...")
        if not self._remove_blocks():
            rumps.alert("Error", "Failed to remove blocks")
            return

        self.is_muted = False
        self.title = "Mute"
        self._update_menu_state()

        if self.timer:
            self.timer.stop()
            self.timer = None

        self.end_time = None

        # Clear session state
        clear_state()

        try:
            rumps.notification("Focus Ended", "", "Distractions unmuted")
        except:
            print("✅ Focus ended - distractions unmuted")

    def quit_app(self, _):
        """Quit the app, cleaning up properly"""
        cleanup_handler()
        rumps.quit_application()


def main():
    check_sudo()
    try:
        MuteApp().run()
    finally:
        # Ensure cleanup even if app crashes
        cleanup_handler()


if __name__ == "__main__":
    main()