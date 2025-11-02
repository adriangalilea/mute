# Mute

Mute distractions.

## Alternatives

- **SelfControl** - dated, unmaintained
- **Focus Firewall** - closed source, paid
- **Mute** - simple, open source, hosts-based blocking

## Libraries

- [rumps](https://github.com/jaredks/rumps) - traditional macOS menubar apps
- [stackit](https://github.com/Bbalduzz/stackit) - modern SwiftUI-inspired framework

## Usage

Requires sudo to modify `/etc/hosts`. Use `-E` flag to preserve environment variables:

```bash
sudo -E uv run python main.py
```

## Configuration

Edit `~/.config/mute/blocklist.txt` (or `$XDG_CONFIG_HOME/mute/blocklist.txt`) to customize blocked domains. One domain per line.

On first run, the template from the repo is copied to your config directory.

## TODO

- **Critical: Browsers bypass /etc/hosts entirely**
  - Safari: Always ignores hosts file
  - Chrome/SigmaOS: Can browse despite blocks (DNS over HTTPS, persistent connections, browser cache)
  - DNS flush commands (`dscacheutil`, `killall mDNSResponder`) do nothing
  - Even force quit + reopen doesn't always work
  - **hosts file approach is fundamentally broken for modern browsers**

- **Solution needed**:
  - Implement pfctl packet filter firewall rules (like SelfControl does)
  - Or use local proxy server to intercept all traffic
  - hosts file only reliable for terminal/system apps, not browsers

- **macOS Shortcuts integration**:
  - Create Shortcuts actions for "Start 25min focus", "Start 2hr focus", etc.
  - Automation triggers (time-based, location-based)

- **Siri voice commands**:
  - Voice activation: "Hey Siri, mute distractions"
  - Quick toggling without opening menu bar

- **Run permanently on macOS**:
  - Create launchd plist to run on login
  - Or Login Items in System Settings
  - Keep running in menu bar persistently

- **Serve static site on blocked domains (instead of 127.0.0.1 404)**:
  - Run local web server on :80 when muted
  - Show motivational page: "You're focusing. Get back to work."
  - Display session time remaining
  - Show your goals/reasons for blocking
  - Alternative: Pomodoro timer, task list, or meditation prompt
  - Simple HTML/CSS, no fancy frameworks

- **Prevent easy toggle-off (reduce temptation)**:
  - Add delay before ending session (e.g., 30 second countdown)
  - Require password/confirmation to end early
  - Log all start/end times to shame yourself
  - Optional: Hide "End Session" button entirely (force quit = restore)
  - Consider: App hiding/removal protection

- **Future: Move to .toml config format**:
  ```toml
  # Categories with toggles
  [social]
  enabled = true
  domains = ["twitter.com", "facebook.com", "instagram.com"]

  [video]
  enabled = true
  domains = ["youtube.com", "netflix.com", "twitch.tv"]

  [news]
  enabled = false
  domains = ["reddit.com", "news.ycombinator.com"]

  # Time-based routines
  [routines.work_hours]
  schedule = "9:00-17:00"
  weekdays = ["mon", "tue", "wed", "thu", "fri"]
  categories = ["social", "video", "news"]

  [routines.deep_work]
  categories = ["social", "video", "news", "chat"]
  ```