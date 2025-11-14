#!/usr/bin/env python3
"""Test script for GUI topology adapter.

Tests the adapter's ability to fetch and transform GUI topology data.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gen_engine_deep_eval.gui_adapter import GUITopologyAdapter


def test_adapter():
    """Test GUI adapter functionality."""
    
    print("="*80)
    print("GUI TOPOLOGY ADAPTER TEST")
    print("="*80)
    print()
    
    # Initialize adapter
    gui_url = "http://localhost:5000"
    print(f"Connecting to GUI: {gui_url}")
    adapter = GUITopologyAdapter(gui_url)
    
    try:
        # Fetch topology
        print("\n1. Fetching topology...")
        raw_topology = adapter.fetch_topology()
        print(f"   ✓ Fetched: {len(raw_topology['switches'])} switches, "
              f"{len(raw_topology['connections'])} connections, "
              f"{len(raw_topology['hosts'])} hosts")
        
        # Transform to blueprint
        print("\n2. Transforming to TopologyBlueprint...")
        blueprint = adapter.to_blueprint()
        switches = [n for n in blueprint.nodes if n.node_type == "switch"]
        hosts = [n for n in blueprint.nodes if n.node_type == "host"]
        print(f"   ✓ Blueprint: {len(switches)} switches, {len(hosts)} hosts, {len(blueprint.links)} links")
        
        # Show switch details
        print("\n   Switch Details:")
        for switch in switches:
            print(f"     - {switch.name} ({switch.role}): {switch.model}")
        
        # Get link profiles
        print("\n3. Extracting link profiles...")
        profiles = adapter.get_link_profiles()
        up_links = sum(1 for p in profiles.values() if p.status == "up")
        down_links = sum(1 for p in profiles.values() if p.status == "down")
        print(f"   ✓ Link profiles: {up_links} up, {down_links} down")
        
        # Show link utilization
        print("\n   Link Utilization:")
        for (src, dst), profile in list(profiles.items())[:5]:
            print(f"     - {src} ↔ {dst}: {profile.utilisation_percent:.1f}% "
                  f"({profile.bw_gbps} Gbps, {profile.status})")
        
        # Detect failures
        print("\n4. Detecting failures...")
        failures = adapter.detect_failures()
        
        if failures:
            print(f"   ⚠️  Detected {len(failures)} failures:")
            for failure in failures:
                print(f"     - {failure['type']} at {failure.get('switch', failure.get('link', 'N/A'))} "
                      f"[{failure['severity']}]")
        else:
            print(f"   ✓ No failures detected - network healthy")
        
        # Test fetch_and_transform convenience method
        print("\n5. Testing convenience method...")
        blueprint2, profiles2 = adapter.fetch_and_transform()
        print(f"   ✓ Convenience method works: {len(blueprint2.nodes)} nodes, {len(profiles2)} profiles")
        
        print("\n" + "="*80)
        print("✅ ALL TESTS PASSED")
        print("="*80)
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_adapter()
    sys.exit(0 if success else 1)
