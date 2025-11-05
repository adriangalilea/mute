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

### py-pf Investigation

**Library:** [py-pf](https://github.com/dotpy/py-pf) - Python wrapper for pfctl

**Status:** ❌ Dropped immediately - OpenBSD-only, won't work on macOS

### BlockMaster Reference

**Project:** [BlockMaster](https://github.com/bythebug/Block-Master-System-Level-Website-Blocker)

**Approach:** "Dual-layer" hosts file + pfctl blocking

**Marketing claims:** "Cannot be bypassed by DNS-over-HTTPS" (false)

**Reality:**
- hosts file doesn't work against DoH (already documented above)
- One-time DNS resolution → stale IPs (we do periodic refresh)
- DNS cache flushing irrelevant (we use pfctl, not hosts file)
- No functional verification (just checks pfctl status)

---

## The Real Solution: Network Extension API

### Why Focus/1Blocker Preserve Private Relay

Apps like Focus ($20-40) and 1Blocker preserve Private Relay because they use **Apple's Network Extension Framework** instead of Unix pfctl:

- `NEDNSProxyProvider` - DNS-level filtering that coexists with Private Relay
- `NEFilterDataProvider` - Packet-level filtering, Apple's intended API

**Key insight:** Apps using Network Extensions with Apple's URLSession/NWConnection APIs don't conflict with Private Relay. When data goes through a Network Extension, Private Relay automatically steps back by design. Apple wants developers to use their APIs, not raw pfctl.

### Why pfctl Breaks Private Relay

**pfctl (Unix approach):**
- Operates at kernel packet filter level
- Conflicts with Private Relay's routing
- SelfControl, Cold Turkey, Murus all break Private Relay

**Network Extension (Apple approach):**
- Integrates with macOS networking stack
- Designed to coexist with system services
- Focus, 1Blocker, AdGuard all preserve Private Relay

### Implementation: DNS Proxy Extension (Recommended)

**Simplest approach** - intercepts DNS before browsers can use DoH:

```swift
import NetworkExtension

class DistractionBlockerDNSProxy: NEDNSProxyProvider {
    let blockedDomains = ["facebook.com", "twitter.com", "reddit.com"]

    override func startProxy(options: [String : Any]?,
                            completionHandler: @escaping (Error?) -> Void) {
        // Start DNS proxy
        completionHandler(nil)
    }

    override func handleNewFlow(_ flow: NEAppProxyFlow) -> Bool {
        guard let hostname = flow.remoteHostname else { return true }

        // Check against blocklist
        if blockedDomains.contains(hostname) {
            return false  // Drop DNS request
        }

        return true  // Allow request
    }
}
```

**Pros:**
- ✅ Preserves Private Relay
- ✅ Blocks before DNS-over-HTTPS
- ✅ System-wide (all apps/browsers)
- ✅ ~200 lines of Swift

**Cons:**
- Requires Network Extension entitlement (Apple Developer account, $99/year)
- Needs signing & notarization
- Domain-based only (not IP-based)

### Alternative: Content Filter Extension

**More powerful** - can inspect/filter packets after DNS:

```swift
import NetworkExtension

class DistractionBlockerFilter: NEFilterDataProvider {
    override func handleNewFlow(_ flow: NEFilterFlow) -> NEFilterNewFlowVerdict {
        guard let socketFlow = flow as? NEFilterSocketFlow else {
            return .allow()
        }

        // Check hostname or IP
        if isDistractingSite(socketFlow.remoteHostname) {
            return .drop()
        }

        return .allow()
    }
}
```

**Pros:**
- ✅ Preserves Private Relay
- ✅ Domain AND IP filtering
- ✅ More granular control
- ✅ Can inspect traffic patterns

**Cons:**
- More complex (~500 lines)
- Higher performance overhead
- Still needs entitlements

### Requirements

**Entitlements needed:**
```xml
<key>com.apple.developer.networking.networkextension</key>
<array>
    <string>dns-proxy</string>
    <!-- or -->
    <string>content-filter-provider</string>
</array>
```

**Apple Developer Program:**
- $99/year
- Legitimate use case (distraction blocker)
- Apple approves these for content filtering apps

**No sudo needed:**
- Network Extensions are system extensions
- Installed via System Settings
- Managed by macOS, clean lifecycle

### Real-World Examples

**Apps using Network Extension (preserve Private Relay):**
- Focus - distraction blocker
- 1Blocker - content blocker
- AdGuard - uses NEDNSProxyProvider ([open source](https://github.com/AdguardTeam/AdguardForMac))

**Apps using pfctl (break Private Relay):**
- SelfControl - ancient approach
- Cold Turkey - also pfctl
- Murus - direct pfctl manipulation

### Migration Path

**Phase 1: Current (Temporary)**
- Python + pfctl subprocess
- Works but disables Private Relay
- Use for quick testing/validation

**Phase 2: Swift + Network Extension (Planned)**
- NEDNSProxyProvider for DNS filtering
- Preserves Private Relay
- Proper macOS integration
- ~200-300 lines Swift

**Phase 3: Polish (Optional)**
- NEFilterDataProvider if DNS insufficient
- Native SwiftUI menu bar
- Signing + notarization workflow

### Resources

- [NEDNSProxyProvider docs](https://developer.apple.com/documentation/networkextension/nednsproxyprovider)
- [NEFilterDataProvider docs](https://developer.apple.com/documentation/networkextension/nefilterdataprovider)
- [AdGuard open source implementation](https://github.com/AdguardTeam/AdguardForMac)
- Network Extension entitlement request: Apple Developer portal

### Decision

**Recommendation:** Swift + NEDNSProxyProvider

**Why not keep pfctl:**
1. Breaks Private Relay (deal-breaker)
2. Requires sudo (bad UX)
3. Text parsing is fragile
4. Not the Apple way

**Why not Rust + pfctl-rs:**
1. Still breaks Private Relay (same pfctl limitation)
2. Need menu bar UI anyway (might as well go full Swift)
3. Network Extension is the proper solution

**Current Status (Nov 2025):**
- ✅ Python+pfctl implementation complete and functional
- ✅ Grouped config, persistent sessions, forever blocking working
- ⚠️ Disables Private Relay (pfctl limitation, acceptable for now)

**Future Direction:**
- **Most likely:** Swift + Network Extension API (proper Apple solution, preserves Private Relay)
- **Alternative:** Rust + pfctl-rs (if staying with pfctl, better than subprocess)
