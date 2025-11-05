# pfctl-rs Proof of Concept

Minimal example demonstrating pfctl-rs for type-safe packet filtering.

## What This Tests

- pfctl-rs library (direct ioctl to `/dev/pf`)
- Creating anchors programmatically
- Adding blocking rules (single IP)
- Clean type-safe API vs subprocess text parsing

## Running

```bash
cd docs/rust-pfctl-poc
sudo cargo run
```

## Results

✅ Blocking works (curl timeout on 172.66.0.227)
❌ Disables Apple Private Relay (same as subprocess pfctl)

## Code

~70 lines of clean Rust vs ~430 lines Python + subprocess

See `src/main.rs` for implementation.
