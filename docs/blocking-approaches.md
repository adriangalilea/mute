# Blocking Approaches: Research & Contingency Plans

## Current Problem

**hosts file approach (current):** Fails against modern browsers
- Safari/Chrome/Firefox use DNS-over-HTTPS (DoH) → bypass hosts file entirely
- macOS 11+ HTTPS DNS records (Type 65) → checked after hosts file
- Browser caching + persistent connections → blocks don't take effect

**Result:** Only blocks terminal tools (curl, wget), not browsers

---

## Approach 1: pfctl + Periodic DNS Resolution (Testing First)

**How it works:**
1. Resolve blocklist domains → IP addresses (IPv4 + IPv6)
2. Generate pfctl rules: `block drop quick from any to <IP>`
3. Background thread: re-resolve every 15 min (catch IP changes)

**Pros:**
- Pure Python (no binaries, no trust issues)
- Kernel-level blocking (actually stops browsers)
- Low overhead (~0.1% CPU)
- No code signing, no Apple bureaucracy
- 80 lines of code

**Cons:**
- 95% reliable (IPs change between refreshes → temporary slips)
- Shared IPs (blocking Cloudflare IP may catch unrelated sites)
- Must manage pfctl state (cleanup on exit)

**When it fails:**
- High-churn CDNs (YouTube, Twitter) change IPs faster than we refresh
- User notices sites slip through for 5-15 min windows

---

## IF pfctl Fails: Two Paths Forward

### Option A: Hybrid (Swift Helper + Python App)

**Architecture:**
```
Python app (UI/logic) ↔ JSON over stdin/stdout ↔ Swift helper (Network Extension)
```

**Swift helper (~250 lines):**
- NEFilterDataProvider (System Extension)
- Reads JSON: `{"action":"block", "domains":["twitter.com"]}`
- Responds: `{"status":"ok"}`
- Signed + notarized with Developer ID

**Python app (current codebase):**
- Menu bar, timers, session logic (unchanged)
- Spawn helper process, communicate via JSON

**Pros:**
- Keep Python for UI/logic (what you like)
- 99.9% reliable (Network Extension is bulletproof)
- Domain-based (no IP churn issues)

**Cons:**
- Binary trust problem (users must trust your signed binary OR compile themselves)
- Xcode maintenance (even if small)
- JSON IPC debugging overhead
- System Extension approval UX (users click through System Settings)
- Higher performance overhead (user-space filtering, kernel↔user packet copying)
- Code signing + notarization workflow on every release

**Distribution:**
- Ship binary in `/bin/` (signed with your Developer ID)
- Ship source in `/helper/` (users can compile if untrusting)
- README explains verification: `codesign -vv bin/MuteFilterHelper`

**Complexity:** +250 Swift, +50 Python for IPC

---

### Option B: Full Swift Rewrite

**What changes:**
- Rewrite entire app in Swift + SwiftUI
- Network Extension embedded in app bundle
- Native macOS app (no Python dependency)

**Pros:**
- Single codebase (no IPC complexity)
- Better macOS integration (notifications, menu bar, etc.)
- 99.9% reliable (Network Extension)
- Easier code signing (single app bundle)
- Better performance (no Python runtime)
- Follows Apple's intended architecture

**Cons:**
- You hate Xcode/Swift development
- Lose Python ecosystem benefits
- Steeper learning curve for contributors
- More verbose code (~600-800 lines vs 430 Python)

**Consider this if:**
- You want to distribute on Mac App Store eventually
- Project grows beyond simple blocking (Screen Time API, etc.)
- Performance becomes critical

**Complexity:** Full rewrite, ~800 lines Swift

---

## Research Summary

### What Doesn't Work:
- **hosts file:** Bypassed by DoH, DNS Type 65
- **Local DNS server (dnsmasq):** Same DoH bypass problem
- **Browser extensions:** Must install in every browser, easily disabled
- **Local proxy (Squid):** Requires root CA cert (security risk)

### What Works:
- **pfctl:** 95% reliable, kernel-level, simple
- **Network Extension:** 99.9% reliable, Apple's intended solution, complex

### Performance Data:
- **pfctl:** Negligible overhead (anecdotal, no benchmarks exist)
- **Network Extension:** Reported 100% CPU spikes on high-speed links, 30s pauses, sleep/wake issues

### Industry Examples:
- **SelfControl:** hosts + pfctl (still has IP churn issues)
- **Freedom:** Local proxy + browser extensions
- **Focus/1Focus:** Network Extension (commercial, $15-40)
- **LuLu:** Network Extension (open source, ships binary)

---

## Decision Framework

**Try pfctl first** → if 95% reliability acceptable, done

**If pfctl fails:**

| Priority | Choose |
|----------|--------|
| Minimize effort | Hybrid (250 Swift, keep Python) |
| Maximize simplicity | Full Swift (no IPC, single codebase) |
| Best reliability | Either (both 99.9%) |
| Easiest maintenance | Full Swift (no JSON protocol versioning) |
| Keep Python | Hybrid (obviously) |

**Key question:** Is avoiding Swift development worth the complexity of maintaining two languages + IPC?

---

## Implementation Notes (If We Go Hybrid)

**Swift helper interface:**
```swift
// Read stdin → parse JSON → call NEFilterManager → write stdout
stdin: {"action": "block", "domains": ["twitter.com", "youtube.com"]}
stdout: {"status": "ok", "message": "Blocking 2 domains"}

stdin: {"action": "unblock"}
stdout: {"status": "ok", "message": "Filter disabled"}
```

**Python integration:**
```python
import subprocess, json

proc = Popen(["./bin/MuteFilterHelper"], stdin=PIPE, stdout=PIPE)
proc.stdin.write(json.dumps({"action": "block", "domains": domains}))
response = json.loads(proc.stdout.readline())
```

**Build requirements:**
- Xcode 14+
- Apple Developer account (for code signing)
- Entitlements: `com.apple.developer.networking.networkextension`
- Provisioning profile for System Extension

**Distribution:**
1. Compile + sign helper with Developer ID
2. Notarize with Apple: `xcrun notarytool submit`
3. Ship binary in repo (users verify signature)
4. Provide source for paranoid users to compile themselves

---

## pfctl Investigation Results (2025-11-05)

### Python subprocess Implementation (PR #2)

**Status:** ✅ Works but has critical limitations

**What we built:**
- DNS resolution → IP addresses (IPv4 + IPv6)
- Generate pfctl rules: `block drop quick from any to <IP>`
- Auto-configure `/etc/pf.conf` with anchor
- Reload pf.conf to activate rules
- Background thread refreshes IPs every 15 min
- Functional verification (curl test instead of parsing output)

**Testing:**
- ✅ Blocks twitter.com, x.com (confirmed via curl)
- ✅ Kernel-level blocking (actually stops traffic)
- ✅ ~430 lines Python + rumps menu bar

**Critical Issues:**

1. **Disables Apple Private Relay**
   - pfctl at kernel level conflicts with Private Relay
   - Not a bug - fundamental limitation of packet filtering
   - User must disable Private Relay manually to use mute

2. **Text Output Parsing is Garbage**
   - `pfctl -s rules -v` outputs unstructured text
   - Regex parsing of "Evaluations: N" is fragile
   - Had to use functional tests (curl) instead
   - No proper error codes or machine-readable output

### Rust pfctl-rs Investigation

**Library:** [pfctl-rs](https://github.com/mullvad/pfctl-rs) by Mullvad VPN

**Tested:** 2025-11-05 with proof-of-concept

**Proof of concept code:** [docs/rust-pfctl-poc/](rust-pfctl-poc/) (~70 lines)

**What we tested:**
- Direct ioctl syscalls to `/dev/pf` device
- Type-safe API (no text parsing)
- Proper error handling via Result types
- ~70 lines Rust for equivalent functionality

**Results:**
- ✅ Blocking works (confirmed via curl timeout)
- ❌ **Also disables Private Relay** (same as subprocess)
- ✅ Much cleaner code (no regex, type-safe)
- ✅ Battle-tested (used by Mullvad VPN in production)

**Conclusion:** pfctl (CLI or ioctl) always disables Private Relay. It's a macOS limitation, not implementation detail.

### Why WireGuard Doesn't Disable Private Relay

WireGuard uses **virtual network interfaces** (`utun` devices), not packet filtering:
- Traffic routes through interface, not filtered
- Operates at different OSI layer than pfctl
- Doesn't conflict with Private Relay's routing

### Future Option: Rust + pfctl-rs

**Status:** Potential alternative for better ergonomics

**Why consider Rust:**
1. **Type-safe API** - No text parsing, proper types
2. **Better errors** - Result types instead of exit codes
3. **Cleaner code** - Builder patterns, no regex
4. **Production-tested** - Used by Mullvad VPN
5. **Future-proof** - Modern, maintained library

**Proof of concept:** See `docs/rust-pfctl-poc/` for minimal working example (~70 lines)

**Trade-offs:**
- ✅ Much better ergonomics than subprocess
- ✅ Type-safe, maintainable
- ❌ Still disables Private Relay (same limitation)
- ❌ Requires Rust toolchain
- ❌ Need menu bar UI crate (more research needed)

**Decision:** Not yet made. Python implementation works. May revisit Rust for better code quality and maintainability.
