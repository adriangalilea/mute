# Mute

![macOS](https://img.shields.io/badge/macOS-13%2B-blue?logo=apple)
![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python)
![pfctl](https://img.shields.io/badge/pfctl-kernel%20level-orange)
![License](https://img.shields.io/badge/license-MIT-green)

**Open-source website blocker for macOS using kernel-level pfctl packet filtering.**

Block distracting websites at the network level. No browser extensions, no DNS tricks, no bypasses.

## Features

- ✅ **Grouped config (INI)** - organize sites into categories ([social], [video], [nsfw])
- ✅ **Persistent sessions** - state saved to disk, survives app restarts
- ✅ **Smart restore** - calculates remaining time on restart, expires old sessions properly
- ✅ **Forever blocking** - no end time, blocks persist through kill/reboot, manual stop only

## How It Works

**Current:** Python + pfctl (kernel-level packet filtering)
- ✅ Actually blocks traffic (not just DNS)
- ✅ Works across all browsers
- ❌ Disables Apple Private Relay (pfctl limitation)

**Why pfctl?** Fast to implement, battle-tested blocking approach. Python chosen for rapid prototyping with `rumps` menu bar library.

**Future:** Most likely Native Swift app with Network Extension API
- Preserves Private Relay (`NEDNSProxyProvider` integrates properly with macOS)
- No sudo required (proper entitlements)
- Alternative: Rust + pfctl-rs (if staying with pfctl, better than subprocess)
- See [docs/blocking-approaches.md](docs/blocking-approaches.md) for full technical research

**Alternatives:**
- **SelfControl** - pfctl, breaks Private Relay
- **Focus/1Blocker** - Network Extension (proprietary, $20-40)

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

## TODO

- **Per-group toggle** - enable/disable categories individually (block [nsfw] only, allow [social])

- **Scheduled blocking** - auto-activate during time windows (Mon-Fri 9-5), smart restore checks if currently in schedule

- **Auto-start on login** - launchd plist or Login Items integration

- **Pause feature** - temporarily disable for 5/15 minutes, auto-resume

- **macOS Shortcuts integration** - actions for "Start 25min", "Start 2hr", automation triggers

- **Siri voice commands** - "Hey Siri, mute distractions" voice activation

- **Serve static site on blocked domains** - local web server shows motivational page instead of timeout

- **Prevent easy toggle-off** - delay before ending, password confirmation, log start/end times