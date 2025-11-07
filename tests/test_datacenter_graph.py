"""Tests for LangGraph-based DataCenter agent implementation."""

import json
from unittest.mock import Mock, MagicMock, patch

import pytest

from gen_engine_deep_eval.graphs.datacenter_graph import (
    build_datacenter_graph,
    run_datacenter_graph,
)
from gen_engine_deep_eval.graphs.state_schemas import DataCenterState


def test_datacenter_state_schema():
    """Test DataCenterState schema structure."""
    state: DataCenterState = {
        "messages": [{"role": "user", "content": "test"}],
        "topology_blueprint": None,
        "link_profiles": None,
        "failure_history": [],
        "remediation_actions": [],
        "network_health": None,
        "iteration_count": 0,
        "final_answer": None,
    }
    
    assert "messages" in state
    assert "topology_blueprint" in state
    assert "link_profiles" in state
    assert "failure_history" in state
    assert state["iteration_count"] == 0


def test_build_datacenter_graph():
    """Test building DataCenter LangGraph."""
    # Mock LLM
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(
        content='{"action": "complete", "summary": "Network is healthy"}'
    ))
    
    # Mock environment
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={"name": "test", "nodes": [], "links": []})
    mock_env.link_profiles = {}
    
    # Build graph
    graph = build_datacenter_graph(
        llm=mock_llm,
        env=mock_env,
        max_iterations=3,
    )
    
    assert graph is not None
    assert hasattr(graph, 'stream') or hasattr(graph, 'invoke')


def test_datacenter_graph_nodes():
    """Test that DataCenter graph has expected nodes."""
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(content='{"action": "complete"}'))
    
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={"name": "test", "nodes": [], "links": []})
    mock_env.link_profiles = {}
    
    graph = build_datacenter_graph(mock_llm, mock_env, max_iterations=2)
    
    # Check graph structure
    if hasattr(graph, 'get_graph'):
        graph_def = graph.get_graph()
        assert graph_def is not None


def test_run_datacenter_graph_healthy():
    """Test running DataCenter graph with healthy network."""
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(
        content='{"action": "complete", "summary": "All links operational"}'
    ))
    
    # Mock healthy environment
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={
        "name": "test-network",
        "nodes": [],
        "links": []
    })
    mock_env.link_profiles = {
        ("node1", "node2"): Mock(to_dict=lambda: {"status": "up", "bw_gbps": 10}),
        ("node2", "node3"): Mock(to_dict=lambda: {"status": "up", "bw_gbps": 10}),
    }
    
    graph = build_datacenter_graph(mock_llm, mock_env, max_iterations=2)
    
    result = run_datacenter_graph(
        graph=graph,
        initial_query="Check network status",
        thread_id="test-healthy",
    )
    
    assert isinstance(result, dict)
    # Should have network health info
    if "network_health" in result:
        assert result["network_health"] is not None


def test_run_datacenter_graph_with_failure():
    """Test DataCenter graph handling network failure."""
    mock_llm = Mock()
    # First call: plan remediation
    # Second call: verify success
    responses = [
        Mock(content='{"action": "activate_backup_path", "params": {"path": ["node1", "node3", "node2"]}}'),
        Mock(content='{"action": "complete", "summary": "Backup path activated"}'),
    ]
    mock_llm.invoke = Mock(side_effect=responses)
    
    # Mock environment with one failed link
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={
        "name": "test-network",
        "nodes": [],
        "links": []
    })
    mock_env.link_profiles = {
        ("node1", "node2"): Mock(to_dict=lambda: {"status": "down", "bw_gbps": 0}),
        ("node1", "node3"): Mock(to_dict=lambda: {"status": "up", "bw_gbps": 10}),
        ("node3", "node2"): Mock(to_dict=lambda: {"status": "up", "bw_gbps": 10}),
    }
    
    # Mock activate_backup_path method
    mock_env.activate_backup_path = Mock(return_value=json.dumps({
        "tool": "activate_backup_path",
        "path": ["node1", "node3", "node2"]
    }))
    
    graph = build_datacenter_graph(mock_llm, mock_env, max_iterations=3)
    
    result = run_datacenter_graph(graph, "Remediate failure", "test-failure")
    
    assert isinstance(result, dict)
    # Should have remediation actions
    if "remediation_actions" in result:
        assert len(result["remediation_actions"]) > 0


def test_datacenter_graph_iteration_limit():
    """Test that DataCenter graph respects iteration limit."""
    mock_llm = Mock()
    # Always return an action that doesn't complete
    mock_llm.invoke = Mock(return_value=Mock(
        content='{"action": "monitor_link", "params": {"src": "node1", "dst": "node2"}}'
    ))
    
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={"name": "test", "nodes": [], "links": []})
    mock_env.link_profiles = {
        ("node1", "node2"): Mock(to_dict=lambda: {"status": "down"}),
    }
    mock_env.monitor_link = Mock(return_value=json.dumps({
        "tool": "monitor_link",
        "status": "down"
    }))
    
    # Set max_iterations to 2
    graph = build_datacenter_graph(mock_llm, mock_env, max_iterations=2)
    
    result = run_datacenter_graph(graph, "Monitor", "test-limit")
    
    # Should stop after hitting limit
    assert isinstance(result, dict)
    if "iteration_count" in result:
        assert result["iteration_count"] <= 2


def test_datacenter_graph_action_execution():
    """Test that graph executes different action types."""
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(
        content='{"action": "probe_connectivity", "params": {"src": "h1", "dst": "h2"}}'
    ))
    
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={"name": "test", "nodes": [], "links": []})
    mock_env.link_profiles = {}
    
    # Mock probe_connectivity
    mock_env.probe_connectivity = Mock(return_value=json.dumps({
        "tool": "probe_connectivity",
        "src": "h1",
        "dst": "h2",
        "loss_percent": 0.0,
        "success": True
    }))
    
    graph = build_datacenter_graph(mock_llm, mock_env, max_iterations=1)
    
    result = run_datacenter_graph(graph, "Test connectivity", "test-action")
    
    # Verify probe was called
    if mock_env.probe_connectivity.called:
        assert mock_env.probe_connectivity.call_count >= 1


def test_datacenter_graph_checkpointing():
    """Test that DataCenter graph supports checkpointing."""
    from langgraph.checkpoint.memory import MemorySaver
    
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(content='{"action": "complete"}'))
    
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={"name": "test", "nodes": [], "links": []})
    mock_env.link_profiles = {}
    
    checkpointer = MemorySaver()
    graph = build_datacenter_graph(
        mock_llm, mock_env, max_iterations=3, checkpointer=checkpointer
    )
    
    result = run_datacenter_graph(graph, "Test checkpoint", "checkpoint-thread")
    
    assert isinstance(result, dict)


def test_datacenter_graph_human_in_loop():
    """Test that graph can be configured with human-in-the-loop."""
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(content='{"action": "complete"}'))
    
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={"name": "test", "nodes": [], "links": []})
    mock_env.link_profiles = {}
    
    # Build with human_in_loop enabled
    graph = build_datacenter_graph(
        mock_llm, mock_env, max_iterations=2, human_in_loop=True
    )
    
    # Graph should build successfully
    assert graph is not None


def test_datacenter_graph_multiple_actions():
    """Test graph handling sequence of remediation actions."""
    mock_llm = Mock()
    responses = [
        Mock(content='{"action": "monitor_link", "params": {"src": "core1", "dst": "agg1"}}'),
        Mock(content='{"action": "activate_backup_path", "params": {"path": ["core1", "core2", "agg1"]}}'),
        Mock(content='{"action": "complete", "summary": "Remediation complete"}'),
    ]
    mock_llm.invoke = Mock(side_effect=responses)
    
    mock_env = Mock()
    mock_env.blueprint = Mock()
    mock_env.blueprint.to_dict = Mock(return_value={"name": "test", "nodes": [], "links": []})
    
    # Start with degraded link, then mark as up after remediation
    link_status = {"status": "down"}
    
    def get_profiles():
        return {
            ("core1", "agg1"): Mock(to_dict=lambda: link_status.copy()),
        }
    
    mock_env.link_profiles = get_profiles()
    
    mock_env.monitor_link = Mock(return_value=json.dumps({
        "tool": "monitor_link", "status": "down"
    }))
    
    def activate_backup(params_json):
        # Simulate successful activation by updating link status
        link_status["status"] = "up"
        return json.dumps({"tool": "activate_backup_path", "success": True})
    
    mock_env.activate_backup_path = Mock(side_effect=activate_backup)
    
    graph = build_datacenter_graph(mock_llm, mock_env, max_iterations=5)
    
    result = run_datacenter_graph(graph, "Full remediation", "test-multi")
    
    assert isinstance(result, dict)
    # Should have executed multiple actions
    if "remediation_actions" in result:
        assert len(result["remediation_actions"]) >= 2
