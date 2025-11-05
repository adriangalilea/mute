#!/usr/bin/env python3
"""
Quick test of pfctl blocking logic (without requiring sudo)

This demonstrates the DNS resolution and rule generation logic.
Requires network connectivity to resolve domains.
"""

import socket
from typing import List, Set

def resolve_domains_to_ips(domains: List[str]) -> Set[str]:
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
            print(f"  ⚠️  Could not resolve {domain} (no network or DNS failure)")
        except Exception as e:
            print(f"  ⚠️  Error resolving {domain}: {e}")
    return ips

if __name__ == "__main__":
    # Test domains
    test_domains = [
        "twitter.com",
        "facebook.com",
        "youtube.com",
        "reddit.com",
    ]

    print("Testing DNS resolution:")
    print("=" * 50)
    print("Note: Requires internet connectivity\n")

    ips = resolve_domains_to_ips(test_domains)

    print("\n" + "=" * 50)
    print(f"Total unique IPs: {len(ips)}")

    if ips:
        print("\nSample pfctl rules that would be generated:")
        print("-" * 50)
        for ip in sorted(list(ips)[:5]):  # Show first 5
            print(f"block drop quick from any to {ip}")
        if len(ips) > 5:
            print(f"... and {len(ips) - 5} more")
    else:
        print("\n⚠️  No IPs resolved. Check network connectivity.")
        print("\nExpected output (when network is available):")
        print("-" * 50)
        print("  twitter.com → 2-4 IPs")
        print("  facebook.com → 2-4 IPs")
        print("  youtube.com → 4-8 IPs")
        print("  reddit.com → 2-4 IPs")
        print("\nWould generate ~10-20 pfctl blocking rules")
