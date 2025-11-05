@README.md

# Implementation Status

## Current: Python + rumps + pfctl
- ✅ Works, kernel-level blocking, periodic IP refresh
- ✅ Grouped config, persistent sessions, forever blocking
- ❌ Disables Private Relay (pfctl limitation)

## Future Direction

**Most likely:** Native Swift app with Network Extension API
- Preserves Private Relay (proper Apple integration)
- NEDNSProxyProvider for DNS-level filtering
- See [docs/blocking-approaches.md](docs/blocking-approaches.md) for technical details

**Alternative:** If staying with pfctl → Rust (type-safe, better ergonomics than subprocess)

**stackit investigation:** Complete. Staying with rumps (Python is temporary anyway).