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
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Set
from py_utils import xdg

TEMPLATE_PATH = Path(__file__).parent / "blocklist.txt.template"
BLOCKLIST_PATH = xdg.config / "mute" / "blocklist.txt"
PFCTL_ANCHOR = "mute"
PF_RULES_PATH = Path("/etc/pf.anchors/mute")
PF_CONF = Path("/etc/pf.conf")


def load_blocklist():
    """Load domains from user's XDG config directory"""
    domains = []

    # Get actual user's UID/GID (not root when running with sudo)
    actual_uid = int(os.environ.get('SUDO_UID', os.getuid()))
    actual_gid = int(os.environ.get('SUDO_GID', os.getgid()))

    # Ensure config directory exists with correct ownership
    if not BLOCKLIST_PATH.parent.exists():
        BLOCKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        os.chown(BLOCKLIST_PATH.parent, actual_uid, actual_gid)

    # Copy template to user config on first run
    if not BLOCKLIST_PATH.exists():
        if TEMPLATE_PATH.exists():
            print(f"📋 First run: copying blocklist template to {BLOCKLIST_PATH}")
            shutil.copy2(TEMPLATE_PATH, BLOCKLIST_PATH)
        else:
            print(f"⚠️  Template not found, creating minimal blocklist at {BLOCKLIST_PATH}")
            minimal = """# Mute Blocklist
# Edit this file to customize which sites to block
# One domain per line, # for comments

twitter.com
www.twitter.com
facebook.com
www.facebook.com
youtube.com
www.youtube.com
reddit.com
www.reddit.com
"""
            BLOCKLIST_PATH.write_text(minimal)

        # Fix ownership so user can edit
        os.chown(BLOCKLIST_PATH, actual_uid, actual_gid)

    # Load blocklist from user config
    try:
        with open(BLOCKLIST_PATH) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if line and not line.startswith('#'):
                    domains.append(line)
        print(f"📋 Loaded {len(domains)} domains from {BLOCKLIST_PATH}")
    except Exception as e:
        print(f"⚠️  Failed to load blocklist: {e}")
        # Fallback to minimal list
        domains = ["twitter.com", "facebook.com", "youtube.com", "reddit.com"]

    return domains

# Global app instance for cleanup
app_instance = None


def check_sudo():
    """Check if running with sudo privileges"""
    # TODO: v1 - implement proper privilege escalation:
    #   - Privileged helper tool with XPC communication
    #   - Authorization Services API
    #   - or launchd daemon with proper entitlements
    if os.geteuid() != 0:
        print("❌ Mute requires sudo privileges to modify /etc/hosts")
        print("\nUsage: sudo uv run python main.py")
        print("   or: sudo python main.py")
        sys.exit(1)


def remove_pfctl_rules():
    """Remove pfctl blocking rules - used for cleanup"""
    try:
        print("🔄 Removing pfctl blocking rules...")
        # Flush all rules in mute anchor
        subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-F", "all"],
                      capture_output=True, check=False)
        # Try to disable pfctl (may fail if other rules exist, that's ok)
        subprocess.run(["pfctl", "-d"], capture_output=True, check=False)
        print("✅ pfctl rules removed")
    except Exception as e:
        print(f"⚠️  Failed to remove pfctl rules: {e}")


def cleanup_handler():
    """Cleanup function called on exit"""
    global app_instance
    if app_instance and app_instance.is_muted:
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
            rumps.separator,
            rumps.MenuItem("End Session", callback=None),  # Greyed out initially
            rumps.separator,
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        self._update_menu_state()

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
            self.menu["End Session"].set_callback(self.end_session)
        else:
            # Not in session: enable start options, disable end
            self.menu["25 minutes"].set_callback(self.start_25)
            self.menu["1 hour"].set_callback(self.start_60)
            self.menu["2 hours"].set_callback(self.start_120)
            self.menu["Until tomorrow"].set_callback(self.start_until_tomorrow)
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
        """Check if pfctl rules already exist"""
        try:
            result = subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-s", "rules"],
                                   capture_output=True, text=True, check=False)
            if result.stdout.strip():
                self.is_muted = True
                self.title = "🔇 Mute"
                self._update_menu_state()
                print("⚠️  Found existing pfctl mute rules")
            else:
                print("✅ No existing pfctl rules")
        except Exception as e:
            print(f"⚠️  Could not check pfctl rules: {e}")

    def _resolve_domains_to_ips(self, domains: List[str]) -> Set[str]:
        """Resolve domains to IP addresses (both IPv4 and IPv6)"""
        ips = set()
        for domain in domains:
            try:
                # Get all address info (IPv4 and IPv6)
                results = socket.getaddrinfo(domain, None)
                for result in results:
                    ip = result[4][0]
                    # Filter out IPv6 link-local addresses
                    if not ip.startswith("fe80:"):
                        ips.add(ip)
                print(f"  {domain} → {len([r for r in results if r[4][0] in ips])} IPs")
            except socket.gaierror:
                print(f"  ⚠️  Could not resolve {domain}")
            except Exception as e:
                print(f"  ⚠️  Error resolving {domain}: {e}")
        return ips

    def _ensure_pf_anchor_config(self):
        """Ensure pf.conf loads our anchor (one-time setup)"""
        try:
            pf_conf_content = PF_CONF.read_text()
            anchor_line = f"anchor \"{PFCTL_ANCHOR}\""

            if anchor_line not in pf_conf_content:
                print("📝 Adding mute anchor to pf.conf...")
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
                print("✅ pf.conf updated")
        except Exception as e:
            raise RuntimeError(f"Failed to update pf.conf: {e}") from e

    def _apply_blocks(self) -> bool:
        """Apply pfctl blocking rules"""
        assert not self.is_muted, "Already muted"

        # Ensure pf.conf has our anchor configured
        self._ensure_pf_anchor_config()

        # Load domains and resolve to IPs
        domains = load_blocklist()
        self.current_domains = domains

        print(f"🔍 Resolving {len(domains)} domains to IP addresses...")
        ips = self._resolve_domains_to_ips(domains)

        if not ips:
            rumps.alert("Error", "Failed to resolve any domains to IPs")
            return False

        print(f"🎯 Blocking {len(ips)} unique IP addresses")

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
        try:
            PF_RULES_PATH.write_text("\n".join(rules) + "\n")
        except Exception as e:
            print(f"Failed to write pfctl rules: {e}")
            return False

        # Load rules into pfctl
        try:
            subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-f", str(PF_RULES_PATH)],
                          capture_output=True, check=True)
            # Enable pfctl
            subprocess.run(["pfctl", "-e"], capture_output=True, check=False)
            print("✅ pfctl rules loaded and enabled")

            # Verify it worked
            if not self._verify_blocks():
                print("⚠️  Blocks may not be working properly")

            return True
        except subprocess.CalledProcessError as e:
            print(f"Failed to load pfctl rules: {e.stderr.decode()}")
            return False

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
        """Verify pfctl rules are loaded"""
        try:
            result = subprocess.run(["pfctl", "-a", PFCTL_ANCHOR, "-s", "rules"],
                                   capture_output=True, text=True, check=True)
            rule_count = len([line for line in result.stdout.split('\n')
                            if line.strip() and not line.startswith('#')])
            if rule_count > 0:
                print(f"✅ Verified {rule_count} blocking rules active")
                return True
            else:
                print("⚠️  No blocking rules found in anchor")
                return False
        except Exception as e:
            print(f"⚠️  Could not verify blocks: {e}")
            return False

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

    def _start_session(self, minutes: Optional[int] = None):
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

        # Setup timer if duration specified
        if minutes:
            self.end_time = datetime.now() + timedelta(minutes=minutes)
            if self.timer:
                self.timer.stop()
            self.timer = rumps.Timer(self.update_timer, 1)
            self.timer.start()
            try:
                rumps.notification("Focus Started", "", f"Muting for {minutes} minutes")
            except:
                print(f"✅ Focus started for {minutes} minutes")
        else:
            try:
                rumps.notification("Focus Started", "", "Muting until tomorrow")
            except:
                print("✅ Focus started until tomorrow")
            # Set end time to 4 AM tomorrow
            tomorrow = datetime.now() + timedelta(days=1)
            self.end_time = tomorrow.replace(hour=4, minute=0, second=0, microsecond=0)
            if self.timer:
                self.timer.stop()
            self.timer = rumps.Timer(self.update_timer, 60)  # Check every minute
            self.timer.start()

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