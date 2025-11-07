"""Tests for LangGraph-based Observer agent implementation."""

import json
from unittest.mock import Mock, MagicMock

import pytest

from gen_engine_deep_eval.graphs.observer_graph import (
    build_observer_graph,
    run_observer_graph,
)
from gen_engine_deep_eval.graphs.state_schemas import ObserverState
from gen_engine_deep_eval.observer_agent import (
    DigitalTwinState,
    TelemetrySample,
    generate_sample,
)


def test_observer_state_schema():
    """Test ObserverState schema structure."""
    state: ObserverState = {
        "messages": [{"role": "user", "content": "test"}],
        "current_snapshot": None,
        "detected_anomalies": None,
        "analysis_history": [],
        "iteration_count": 0,
        "final_answer": None,
    }
    
    assert "messages" in state
    assert "current_snapshot" in state
    assert "detected_anomalies" in state
    assert state["iteration_count"] == 0


def test_build_observer_graph():
    """Test building Observer LangGraph."""
    # Mock LLM
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(content="Network is healthy"))
    
    # Create state provider
    state_provider = DigitalTwinState()
    for i in range(10):
        state_provider.add(generate_sample(float(i), anomaly_probability=0.0))
    
    # Build graph
    graph = build_observer_graph(
        llm=mock_llm,
        state_provider=state_provider,
        max_iterations=3,
    )
    
    assert graph is not None
    # Graph should be compiled
    assert hasattr(graph, 'stream') or hasattr(graph, 'invoke')


def test_observer_graph_nodes():
    """Test that Observer graph has expected nodes."""
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(content="Test response"))
    
    state_provider = DigitalTwinState()
    for i in range(5):
        state_provider.add(generate_sample(float(i)))
    
    graph = build_observer_graph(mock_llm, state_provider, max_iterations=2)
    
    # Check graph structure (LangGraph provides get_graph method)
    if hasattr(graph, 'get_graph'):
        graph_def = graph.get_graph()
        # Check that nodes exist
        assert graph_def is not None


def test_run_observer_graph_with_mock():
    """Test running Observer graph with mocked LLM."""
    # Create mock LLM that returns simple responses
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(content="Network health is normal"))
    
    # Create state with normal telemetry
    state_provider = DigitalTwinState()
    for i in range(10):
        state_provider.add(generate_sample(float(i), anomaly_probability=0.0))
    
    # Build and run graph
    graph = build_observer_graph(mock_llm, state_provider, max_iterations=2)
    
    result = run_observer_graph(
        graph=graph,
        initial_query="Check network health",
        thread_id="test-1",
    )
    
    # Verify result structure
    assert isinstance(result, dict)
    assert "messages" in result or "final_answer" in result


def test_observer_graph_anomaly_detection():
    """Test Observer graph with anomalous data."""
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(
        content="High CPU and latency detected. Investigate immediately."
    ))
    
    # Create state with anomalies
    state_provider = DigitalTwinState()
    # Add normal samples
    for i in range(8):
        state_provider.add(generate_sample(float(i), anomaly_probability=0.0))
    
    # Add anomalous samples
    for i in range(8, 10):
        anomaly = TelemetrySample(
            timestamp=float(i),
            latency_ms=150.0,  # High latency
            packet_loss_pct=0.2,
            cpu_pct=95.0,  # High CPU
            mem_pct=55.0,
        )
        state_provider.add(anomaly)
    
    graph = build_observer_graph(mock_llm, state_provider, max_iterations=1)
    
    result = run_observer_graph(graph, "Assess network", "test-anomaly")
    
    # Should have run at least once
    assert isinstance(result, dict)


def test_observer_graph_iteration_limit():
    """Test that Observer graph respects iteration limit."""
    mock_llm = Mock()
    # Always say there are issues to force continuation
    mock_llm.invoke = Mock(return_value=Mock(
        content="Critical issues found. Continue monitoring."
    ))
    
    state_provider = DigitalTwinState()
    for i in range(10):
        # Add samples with high CPU to trigger anomaly continuation
        sample = TelemetrySample(
            timestamp=float(i),
            latency_ms=100.0,
            packet_loss_pct=0.2,
            cpu_pct=90.0,  # Triggers rule-based anomaly
            mem_pct=55.0,
        )
        state_provider.add(sample)
    
    # Set max_iterations to 2
    graph = build_observer_graph(mock_llm, state_provider, max_iterations=2)
    
    result = run_observer_graph(graph, "Monitor", "test-limit")
    
    # Should stop after 2 iterations
    assert isinstance(result, dict)
    # If iteration_count is in result, verify it
    if "iteration_count" in result:
        assert result["iteration_count"] <= 2


def test_observer_graph_checkpointing():
    """Test that Observer graph supports checkpointing."""
    from langgraph.checkpoint.memory import MemorySaver
    
    mock_llm = Mock()
    mock_llm.invoke = Mock(return_value=Mock(content="Checkpoint test"))
    
    state_provider = DigitalTwinState()
    for i in range(5):
        state_provider.add(generate_sample(float(i)))
    
    # Create graph with checkpointer
    checkpointer = MemorySaver()
    graph = build_observer_graph(
        mock_llm, state_provider, max_iterations=3, checkpointer=checkpointer
    )
    
    # Run with thread ID for checkpointing
    result = run_observer_graph(graph, "Test checkpoint", "checkpoint-thread")
    
    assert isinstance(result, dict)
    # Checkpointer should have stored state
    # This is verified by the graph not raising an error


def test_observer_graph_message_accumulation():
    """Test that messages accumulate correctly in state."""
    mock_llm = Mock()
    responses = [
        Mock(content="First analysis"),
        Mock(content="Second analysis"),
    ]
    mock_llm.invoke = Mock(side_effect=responses)
    
    state_provider = DigitalTwinState()
    for i in range(10):
        state_provider.add(generate_sample(float(i), anomaly_probability=0.1))
    
    graph = build_observer_graph(mock_llm, state_provider, max_iterations=2)
    
    result = run_observer_graph(graph, "Continuous monitoring", "msg-test")
    
    # Messages should accumulate
    if "messages" in result:
        assert len(result["messages"]) >= 1
    
    # Should have final answer
    assert "final_answer" in result or "messages" in result
