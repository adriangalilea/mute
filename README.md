# Mute

Mute distractions.

## Current Implementation

**Status:** Temporary pfctl-based blocking (Python)

**Works but has critical limitations:**
- ✅ Kernel-level blocking (actually stops browsers)
- ❌ **Disables Apple Private Relay** (pfctl limitation)
- ❌ Python subprocess (non-type-safe, text parsing)

**Planned:** Swift rewrite with Network Extension API (the proper Apple way)

## Alternatives

- **SelfControl** - dated pfctl approach, breaks Private Relay
- **Focus** - uses Network Extension, preserves Private Relay (proprietary, $20-40)
- **1Blocker** - uses Network Extension, preserves Private Relay (proprietary)
- **Mute** - open source, currently pfctl (temporary), moving to Network Extension

## Why Network Extension?

Apps like Focus and 1Blocker preserve Private Relay because they use Apple's Network Extension Framework:
- `NEDNSProxyProvider` - DNS-level filtering, coexists with Private Relay
- `NEFilterDataProvider` - Packet-level filtering, Apple's intended API

**pfctl (Unix approach)** conflicts with Private Relay at kernel level.
**Network Extension (Apple approach)** integrates properly with macOS networking stack.

See [docs/blocking-approaches.md](docs/blocking-approaches.md) for full technical research.

## Current Usage

Requires sudo for pfctl manipulation. **Warning: Disables Private Relay while active.**

```bash
sudo -E uv run python main.py
```

## Configuration

Edit `~/.config/mute/blocklist.txt` (or `$XDG_CONFIG_HOME/mute/blocklist.txt`) to customize blocked domains. One domain per line.

On first run, the template from the repo is copied to your config directory.

## TODO

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