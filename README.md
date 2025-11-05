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

Edit `~/.config/mute/sites.ini` (or `$XDG_CONFIG_HOME/mute/sites.ini`) to customize blocked domains. Organized by groups:

```ini
[social]
twitter.com
facebook.com

[video]
youtube.com
```

On first run, the template from the repo is copied to your config directory.

## Features

- ✅ **Grouped config (INI)** - organize sites into categories ([social], [video], [nsfw])
- ✅ **Persistent sessions** - state saved to disk, survives app restarts
- ✅ **Smart restore** - calculates remaining time on restart, expires old sessions properly
- ✅ **Forever blocking** - no end time, blocks persist through kill/reboot, manual stop only

## TODO

- **Per-group toggle** - enable/disable categories individually (block [nsfw] only, allow [social])

- **Scheduled blocking** - auto-activate during time windows (Mon-Fri 9-5), smart restore checks if currently in schedule

- **Auto-start on login** - launchd plist or Login Items integration

- **Pause feature** - temporarily disable for 5/15 minutes, auto-resume

- **macOS Shortcuts integration** - actions for "Start 25min", "Start 2hr", automation triggers

- **Siri voice commands** - "Hey Siri, mute distractions" voice activation

- **Serve static site on blocked domains** - local web server shows motivational page instead of timeout

- **Prevent easy toggle-off** - delay before ending, password confirmation, log start/end times