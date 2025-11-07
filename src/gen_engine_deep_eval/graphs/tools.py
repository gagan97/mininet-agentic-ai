"""LangGraph-compatible tool definitions for Observer and DataCenter agents.

This module provides tool wrappers that work with LangGraph's tool calling
mechanism while maintaining compatibility with existing tool implementations.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


# --------------------------- Observer Agent Tools --------------------------- #


@tool
def latest_snapshot_tool(state_provider: Any = None) -> str:
    """Get the most recent telemetry sample.
    
    Returns JSON with latency_ms, packet_loss_pct, cpu_pct, mem_pct.
    
    Note: This tool is designed to be partially applied with a state_provider
    before being used in a LangGraph. See observer_graph.py for usage example.
    
    Args:
        state_provider: Required - DigitalTwinState instance for accessing telemetry
    
    Returns:
        JSON string with latest telemetry snapshot
    """
    if state_provider is None:
        return json.dumps({"error": "state_provider is required"})
    
    if hasattr(state_provider, 'latest'):
        latest = state_provider.latest()
        return json.dumps(latest.__dict__ if latest else {})
    return json.dumps({})


@tool
def detect_anomalies_tool(
    state_provider: Any = None, threshold: float = 3.0
) -> str:
    """Analyze telemetry window and detect anomalies.
    
    Uses statistical z-scores and domain-specific rules to identify issues
    with latency, CPU, packet loss, and memory.
    
    Note: This tool is designed to be partially applied with a state_provider
    before being used in a LangGraph. See observer_graph.py for usage example.
    
    Args:
        state_provider: Required - DigitalTwinState instance for accessing telemetry
        threshold: Z-score threshold for anomaly detection (default 3.0)
    
    Returns:
        JSON string with anomalies and latest sample
    """
    if state_provider is None:
        return json.dumps({"error": "state_provider is required"})
    
    if hasattr(state_provider, 'as_dict_series'):
        from ..observer_agent import _z_scores
        
        series = state_provider.as_dict_series()
        anomalies: dict[str, Any] = {}
        
        for metric, values in series.items():
            if len(values) < 5:
                continue
            zs = _z_scores(values)
            if abs(zs[-1]) >= threshold:
                anomalies[metric] = {
                    "current": values[-1],
                    "z_score": round(zs[-1], 2),
                    "threshold": threshold,
                }
            # Domain thresholds
            if metric == "cpu_pct" and values[-1] > 80:
                anomalies.setdefault(metric, {"current": values[-1]}).update(
                    {"rule": ">80% cpu"}
                )
            if metric == "latency_ms" and values[-1] > 80:
                anomalies.setdefault(metric, {"current": values[-1]}).update(
                    {"rule": ">80ms latency"}
                )
        
        latest = state_provider.latest()
        return json.dumps({
            "anomalies": anomalies,
            "latest": latest.__dict__ if latest else None
        })
    
    return json.dumps({"anomalies": {}, "latest": None})


# ------------------------ DataCenter Agent Tools ---------------------------- #


@tool
def inspect_link_health_tool(link_name: str, env: Any = None) -> str:
    """Inspect health metrics for a specific network link.
    
    Args:
        link_name: Link identifier (e.g., "core1-agg1a")
        env: DataCenter environment instance
    
    Returns:
        JSON string with bandwidth, latency, utilization, and status
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    # Delegate to environment's method
    try:
        if hasattr(env, 'inspect_link_health'):
            return env.inspect_link_health(link_name)
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def monitor_link_tool(link_name: str, env: Any = None) -> str:
    """Monitor a network link and return current metrics.
    
    Args:
        link_name: Link identifier (e.g., "core1-agg1a")
        env: DataCenter environment instance
    
    Returns:
        JSON string with link metrics or error
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    try:
        if hasattr(env, 'monitor_link'):
            return env.monitor_link(link_name)
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def compute_resilient_path_tool(
    source: str, destination: str, avoid: list[str] | None = None, env: Any = None
) -> str:
    """Compute alternate path avoiding failed links.
    
    Args:
        source: Source node name
        destination: Destination node name
        avoid: List of link pairs to avoid (e.g., ["core1-agg1a"])
        env: DataCenter environment instance
    
    Returns:
        JSON string with path nodes and total latency
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    try:
        if hasattr(env, 'compute_resilient_path'):
            return env.compute_resilient_path(source, destination, avoid or [])
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def activate_backup_path_tool(path_nodes: list[str], env: Any = None) -> str:
    """Activate a backup network path.
    
    Args:
        path_nodes: List of node names forming the path
        env: DataCenter environment instance
    
    Returns:
        JSON string with activation result
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    try:
        if hasattr(env, 'activate_backup_path'):
            return env.activate_backup_path(path_nodes)
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def restore_primary_path_tool(link_name: str, env: Any = None) -> str:
    """Restore a primary network path after failure recovery.
    
    Args:
        link_name: Link identifier to restore
        env: DataCenter environment instance
    
    Returns:
        JSON string with restoration result
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    try:
        if hasattr(env, 'restore_primary_path'):
            return env.restore_primary_path(link_name)
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def probe_connectivity_tool(source: str, destination: str, env: Any = None) -> str:
    """Probe network connectivity between two hosts.
    
    Args:
        source: Source host name
        destination: Destination host name
        env: DataCenter environment instance
    
    Returns:
        JSON string with connectivity test results
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    try:
        if hasattr(env, 'probe_connectivity'):
            return env.probe_connectivity(source, destination)
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def traceroute_tool(source: str, destination: str, env: Any = None) -> str:
    """Perform traceroute between two hosts.
    
    Args:
        source: Source host name
        destination: Destination host name
        env: DataCenter environment instance
    
    Returns:
        JSON string with traceroute path information
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    try:
        if hasattr(env, 'traceroute'):
            return env.traceroute(source, destination)
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def simulate_failure_tool(
    link_name: str, mode: str = "cable_cut", env: Any = None
) -> str:
    """Simulate a network failure.
    
    Args:
        link_name: Link to fail
        mode: Failure mode (cable_cut, latency_spike, congestion, packet_loss)
        env: DataCenter environment instance
    
    Returns:
        JSON string with simulation result
    """
    if env is None:
        return json.dumps({"error": "Environment not available"})
    
    try:
        if hasattr(env, 'simulate_failure'):
            return env.simulate_failure(link_name, mode)
        return json.dumps({"error": "Method not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})
