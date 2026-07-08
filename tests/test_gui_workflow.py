#!/usr/bin/env python3
"""Test GUI datacenter agent workflow without LLM (dry run).

This test validates the graph structure and adapter integration without
requiring LLM API calls.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from gen_engine_deep_eval.graphs.gui_datacenter_graph import (
    fetch_topology_node,
    analyze_failures_node,
    build_network_graph_node,
    find_alternate_paths_node,
    GUIDatacenterState,
)


def test_workflow_nodes():
    """Test individual workflow nodes."""
    
    print("="*80)
    print("GUI DATACENTER WORKFLOW TEST (Dry Run)")
    print("="*80)
    print()
    
    # Initialize state
    state: GUIDatacenterState = {
        "gui_url": "http://localhost:5000",
        "user_query": "Test query",
        "status": "idle",
    }
    
    try:
        # Test 1: Fetch topology
        print("1. Testing fetch_topology_node...")
        state = fetch_topology_node(state)
        
        if state["status"] == "error":
            print(f"   ❌ Failed: {state['error_message']}")
            return False
        
        blueprint = state["blueprint"]
        print(f"   ✓ Fetched: {len(blueprint.nodes)} nodes, {len(blueprint.links)} links")
        
        # Test 2: Analyze failures
        print("\n2. Testing analyze_failures_node...")
        state = analyze_failures_node(state)
        
        if state["status"] == "error":
            print(f"   ❌ Failed: {state['error_message']}")
            return False
        
        failures = state["failures"]
        print(f"   ✓ Detected {len(failures)} failures")
        
        if failures:
            for failure in failures[:3]:  # Show first 3
                print(f"      - {failure['type']} at {failure.get('switch', failure.get('link', 'N/A'))}")
        
        # Test 3: Build graph (only if failures exist)
        if state["failure_count"] > 0:
            print("\n3. Testing build_network_graph_node...")
            state = build_network_graph_node(state)
            
            if state["status"] == "error":
                print(f"   ❌ Failed: {state['error_message']}")
                return False
            
            graph = state["graph"]
            print(f"   ✓ Built graph: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
            
            # Test 4: Find alternate paths
            print("\n4. Testing find_alternate_paths_node...")
            state = find_alternate_paths_node(state)
            
            if state["status"] == "error":
                print(f"   ❌ Failed: {state['error_message']}")
                return False
            
            remediation_plan = state["remediation_plan"]
            print(f"   ✓ Generated remediation plan: {len(remediation_plan)} items")
            
            for plan in remediation_plan[:3]:  # Show first 3
                print(f"      - {plan['failure']['type']}: {plan['status']}")
                if plan.get("alternate_paths"):
                    best_path = plan["alternate_paths"][0]
                    print(f"        Path: {' → '.join(best_path['path'])}")
        else:
            print("\n3-4. Skipping path analysis (no failures)")
        
        print("\n" + "="*80)
        print("✅ ALL WORKFLOW NODES PASSED")
        print("="*80)
        
        return True
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_workflow_nodes()
    sys.exit(0 if success else 1)
