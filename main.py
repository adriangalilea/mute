#!/usr/bin/env python3

import os
import sys
import signal
import atexit
import rumps
import subprocess
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from py_utils import xdg

HOSTS_PATH = Path("/etc/hosts")
HOSTS_BACKUP = Path("/etc/hosts.mute-backup")
TEMPLATE_PATH = Path(__file__).parent / "blocklist.txt.template"
BLOCKLIST_PATH = xdg.config / "mute" / "blocklist.txt"
MUTE_START_MARKER = "# === MUTE START ==="
MUTE_END_MARKER = "# === MUTE END ==="


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


def restore_hosts_from_backup():
    """Restore hosts file from backup - used for cleanup"""
    try:
        if HOSTS_BACKUP.exists():
            print("🔄 Restoring hosts file from backup...")
            shutil.copy2(HOSTS_BACKUP, HOSTS_PATH)
            print("✅ Hosts file restored")
    except Exception as e:
        print(f"⚠️  Failed to restore hosts file: {e}")


def cleanup_handler():
    """Cleanup function called on exit"""
    global app_instance
    if app_instance and app_instance.is_muted:
        print("\n🧹 Cleaning up...")
        restore_hosts_from_backup()


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
        """Check if hosts file already has mute blocks"""
        try:
            content = HOSTS_PATH.read_text()
            if MUTE_START_MARKER in content:
                self.is_muted = True
                self.title = "🔇 Mute"
                self._update_menu_state()
                print("⚠️  Found existing mute blocks in hosts file")
            else:
                print("✅ Hosts file is clean")
        except Exception as e:
            print(f"⚠️  Could not check hosts file: {e}")

    def _create_backup(self) -> bool:
        """Create backup of clean hosts file if it doesn't exist"""
        try:
            # Only create backup if it doesn't exist or if current hosts has no mute blocks
            if not HOSTS_BACKUP.exists():
                current = HOSTS_PATH.read_text()
                if MUTE_START_MARKER not in current:
                    shutil.copy2(HOSTS_PATH, HOSTS_BACKUP)
                    print("📦 Created hosts backup")
                else:
                    # Current hosts is dirty, try to clean it first
                    print("⚠️  Current hosts file has mute blocks, cleaning first...")
                    self._clean_hosts()
                    shutil.copy2(HOSTS_PATH, HOSTS_BACKUP)
            return True
        except Exception as e:
            print(f"Failed to backup hosts: {e}")
            return False

    def _clean_hosts(self):
        """Remove any existing mute blocks from hosts file"""
        try:
            current = HOSTS_PATH.read_text()
            if MUTE_START_MARKER in current:
                start = current.index(MUTE_START_MARKER)
                end = current.index(MUTE_END_MARKER) + len(MUTE_END_MARKER)
                clean_content = current[:start].rstrip() + current[end+1:].lstrip()
                HOSTS_PATH.write_text(clean_content)
        except Exception as e:
            print(f"Failed to clean hosts: {e}")

    def _apply_blocks(self) -> bool:
        """Apply blocks to hosts file"""
        assert not self.is_muted, "Already muted"

        # Read from backup as base
        try:
            if not HOSTS_BACKUP.exists():
                print("⚠️  No backup found, creating one...")
                if not self._create_backup():
                    return False

            base_content = HOSTS_BACKUP.read_text().rstrip()
        except Exception as e:
            rumps.alert("Error", f"Failed to read hosts backup: {e}")
            return False

        # Load domains and add blocks
        domains = load_blocklist()
        blocks = [
            "",
            MUTE_START_MARKER,
            f"# Muted at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        for domain in domains:
            blocks.append(f"127.0.0.1\t{domain}")
        blocks.append(MUTE_END_MARKER)

        new_content = base_content + "\n" + "\n".join(blocks) + "\n"

        # Write new hosts file
        try:
            HOSTS_PATH.write_text(new_content)

            # Verify it worked
            if not self._verify_blocks():
                print("⚠️  Blocks may not be working properly")

            return True
        except Exception as e:
            print(f"Failed to write hosts file: {e}")
            return False

    def _remove_blocks(self) -> bool:
        """Restore hosts from backup"""
        assert self.is_muted, "Not muted"

        try:
            if HOSTS_BACKUP.exists():
                shutil.copy2(HOSTS_BACKUP, HOSTS_PATH)
                print("✅ Restored clean hosts from backup")
                return True
            else:
                print("⚠️  No backup found, attempting to clean manually")
                self._clean_hosts()
                return True
        except Exception as e:
            print(f"Failed to restore hosts: {e}")
            return False

    def _verify_blocks(self) -> bool:
        """Verify blocks are working by checking if a domain resolves to 127.0.0.1"""
        try:
            import socket
            # Test with twitter.com
            result = socket.gethostbyname("twitter.com")
            is_blocked = result == "127.0.0.1"
            if is_blocked:
                print("✅ Blocks verified working")
            else:
                print(f"⚠️  twitter.com resolved to {result} instead of 127.0.0.1")
            return is_blocked
        except Exception as e:
            print(f"⚠️  Could not verify blocks: {e}")
            return False

    def _start_session(self, minutes: Optional[int] = None):
        """Start a focus session"""
        if self.is_muted:
            rumps.alert("Already Focused", "End current session first")
            return

        # Create backup if needed
        if not self._create_backup():
            rumps.alert("Error", "Failed to backup hosts file")
            return

        # Apply blocks
        if not self._apply_blocks():
            rumps.alert("Error", "Failed to apply blocks")
            return

        self.is_muted = True
        self.title = "🔇 Mute"
        self._update_menu_state()

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