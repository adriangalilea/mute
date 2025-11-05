use pfctl::{PfCtl, FilterRuleBuilder, FilterRuleAction, DropAction, Ip, AnchorKind};
use std::net::IpAddr;
use std::thread;
use std::time::Duration;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("🔧 pfctl-rs Private Relay Compatibility Test");
    println!("=============================================\n");

    // Check if running as root
    if !nix::unistd::Uid::effective().is_root() {
        eprintln!("❌ Must run with sudo");
        std::process::exit(1);
    }

    // Initialize pfctl
    println!("📝 Initializing pfctl...");
    let mut pf = PfCtl::new()?;

    // Enable pfctl
    println!("🔌 Enabling pfctl...");
    pf.try_enable()?;
    println!("✅ pfctl enabled\n");

    // Create anchor
    let anchor = "mute_test";
    println!("📁 Creating anchor '{}'...", anchor);
    pf.try_add_anchor(anchor, AnchorKind::Filter)?;
    println!("✅ Anchor created\n");

    // Define test IP (twitter.com)
    let test_ip: IpAddr = "172.66.0.227".parse()?;
    println!("🎯 Target IP: {} (twitter.com)", test_ip);

    // Create blocking rule
    println!("📋 Creating blocking rule...");
    let rule = FilterRuleBuilder::default()
        .action(FilterRuleAction::Drop(DropAction::Drop))
        .quick(true)
        .to(Ip::from(test_ip))
        .build()?;

    // Add rule to anchor
    println!("🔗 Adding rule to anchor '{}'...", anchor);
    pf.add_rule(anchor, &rule)?;
    println!("✅ Blocking rule active\n");

    // Instructions
    println!("🧪 TEST INSTRUCTIONS:");
    println!("1. Check Private Relay status in System Settings > Network");
    println!("2. Test blocking: curl -I http://{} --connect-timeout 5", test_ip);
    println!("   (Should timeout if blocking works)");
    println!("3. Check if Private Relay is still enabled");
    println!("4. Browse normally - does Private Relay work?\n");

    println!("⏳ Blocking active for 60 seconds...");
    println!("   (Press Ctrl+C to stop early)");

    // Keep blocking active
    thread::sleep(Duration::from_secs(60));

    // Cleanup
    println!("\n🧹 Cleaning up...");
    pf.flush_rules(anchor, pfctl::RulesetKind::Filter)?;
    println!("✅ Rules removed");

    println!("\n📊 RESULTS:");
    println!("Did blocking work? (curl timeout)");
    println!("Did Private Relay stay enabled?");
    println!("Did Private Relay still function?");

    Ok(())
}
