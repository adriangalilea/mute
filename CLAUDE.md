@README.md

# Completed Research

## Blocking Approaches
- [x] Deep research on reliable blocking methods for macOS
  - Analyzed hosts file limitations (DoH bypass, browser caching)
  - Evaluated pfctl, Network Extension, DNS servers, proxies, browser extensions
  - Documented contingency plans if pfctl fails
  - See [docs/blocking-approaches.md](docs/blocking-approaches.md) for full analysis

**Next:** Implement pfctl + periodic DNS resolution approach (testing phase)

# Pending Tasks

## Library Investigation

- [ ] Deep dive into [stackit](https://github.com/Bbalduzz/stackit) codebase
  - Full code review for security/malware
  - Compare API design vs rumps
  - Test SwiftUI-inspired components
  - Evaluate if refactor from rumps → stackit is worth it