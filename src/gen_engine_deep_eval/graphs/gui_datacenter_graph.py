"""LangGraph workflow for GUI-driven datacenter remediation agent.

This module implements a LangGraph StateGraph that:
1. Fetches topology from GUI REST API
2. Detects failures from connection/port states
3. Analyzes network graph to find alternate paths
4. Uses LLM to generate remediation suggestions
5. Returns human-readable runbook (no actual changes)

The workflow is designed for advisory mode - it suggests fixes but doesn't
execute them, allowing network engineers to review and manually apply changes.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Literal, Tuple, TypedDict

import networkx as nx
from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger

from ..gui_adapter import GUITopologyAdapter
from ..datacenter_agent import LinkProfile, TopologyBlueprint


class GUIDatacenterState(TypedDict, total=False):
    """State for GUI-driven datacenter remediation workflow."""

    # Input configuration
    gui_url: str
    user_query: str | None

    # Fetched data
    raw_topology: Dict[str, Any]
    blueprint: TopologyBlueprint
    link_profiles: Dict[Tuple[str, str], LinkProfile]

    # Analysis results
    failures: List[Dict[str, Any]]
    failure_count: int
    graph: nx.Graph

    # Remediation plan
    remediation_plan: List[Dict[str, Any]]
    runbook: str

    # LLM interaction
    messages: List[HumanMessage | AIMessage | SystemMessage]
    llm_analysis: str

    # Status tracking
    status: Literal["idle", "fetching", "analyzing", "planning", "complete", "error"]
    error_message: str | None


def build_gui_datacenter_graph(llm: BaseLanguageModel) -> StateGraph:
    """Build LangGraph workflow for GUI-driven datacenter agent.

    Args:
        llm: Language model for reasoning and runbook generation

    Returns:
        Compiled StateGraph
    """
    workflow = StateGraph(GUIDatacenterState)

    # Define nodes
    workflow.add_node("fetch_topology", fetch_topology_node)
    workflow.add_node("analyze_failures", analyze_failures_node)
    workflow.add_node("build_graph", build_network_graph_node)
    workflow.add_node("find_paths", find_alternate_paths_node)
    workflow.add_node("llm_analysis", lambda state: llm_analysis_node(state, llm))
    workflow.add_node("generate_runbook", lambda state: generate_runbook_node(state, llm))

    # Define edges
    workflow.add_edge(START, "fetch_topology")
    workflow.add_edge("fetch_topology", "analyze_failures")

    # Conditional routing based on failure count
    workflow.add_conditional_edges(
        "analyze_failures",
        route_by_failures,
        {
            "no_failures": END,
            "has_failures": "build_graph",
        },
    )

    workflow.add_edge("build_graph", "find_paths")
    workflow.add_edge("find_paths", "llm_analysis")
    workflow.add_edge("llm_analysis", "generate_runbook")
    workflow.add_edge("generate_runbook", END)

    return workflow.compile()


# Node implementations


def fetch_topology_node(state: GUIDatacenterState) -> GUIDatacenterState:
    """Node: Fetch topology from GUI API."""
    logger.info(f"Fetching topology from GUI: {state['gui_url']}")

    try:
        state["status"] = "fetching"
        adapter = GUITopologyAdapter(state["gui_url"])

        # Fetch and transform topology
        blueprint, link_profiles = adapter.fetch_and_transform()

        state["raw_topology"] = adapter._raw_topology
        state["blueprint"] = blueprint
        state["link_profiles"] = link_profiles
        state["status"] = "analyzing"

        logger.info(
            f"Topology fetched: {len(blueprint.nodes)} nodes, {len(blueprint.links)} links"
        )

    except Exception as e:
        logger.error(f"Failed to fetch topology: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)

    return state


def analyze_failures_node(state: GUIDatacenterState) -> GUIDatacenterState:
    """Node: Detect and classify failures from GUI state."""
    logger.info("Analyzing failures from GUI topology state")

    try:
        adapter = GUITopologyAdapter(state["gui_url"])
        failures = adapter.detect_failures(state["raw_topology"])

        state["failures"] = failures
        state["failure_count"] = len(failures)

        # Log failure summary
        if failures:
            logger.warning(f"Detected {len(failures)} failures:")
            for failure in failures:
                logger.warning(
                    f"  - {failure['type']} at {failure.get('switch', failure.get('link', 'unknown'))} "
                    f"[{failure['severity']}]"
                )
        else:
            logger.info("No failures detected - network is healthy")

    except Exception as e:
        logger.error(f"Failed to analyze failures: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)

    return state


def build_network_graph_node(state: GUIDatacenterState) -> GUIDatacenterState:
    """Node: Build NetworkX graph from topology for path analysis."""
    logger.info("Building network graph for path analysis")

    try:
        blueprint = state["blueprint"]
        link_profiles = state["link_profiles"]

        # Create directed graph
        graph = nx.Graph()

        # Add nodes
        for node in blueprint.nodes:
            graph.add_node(
                node.name,
                role=node.role,
                model=node.model,
                node_type=node.node_type,
                metadata=node.metadata,
            )

        # Add edges with capacity and status
        for link in blueprint.links:
            key = tuple(sorted([link.src, link.dst]))
            profile = link_profiles.get(key)

            if profile and profile.status == "up":
                graph.add_edge(
                    link.src,
                    link.dst,
                    capacity_gbps=profile.bw_gbps,
                    delay_ms=profile.delay_ms,
                    utilization=profile.utilisation_percent,
                    medium=link.medium,
                )

        state["graph"] = graph
        logger.info(
            f"Graph built: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges"
        )

    except Exception as e:
        logger.error(f"Failed to build graph: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)

    return state


def find_alternate_paths_node(state: GUIDatacenterState) -> GUIDatacenterState:
    """Node: Find alternate paths for each failure."""
    logger.info("Finding alternate paths for failures")

    try:
        graph = state["graph"]
        failures = state["failures"]
        blueprint = state["blueprint"]
        remediation_plan: List[Dict[str, Any]] = []

        # Get all host nodes for end-to-end connectivity analysis
        host_nodes = [n.name for n in blueprint.nodes if n.node_type == "host"]
        
        for failure in failures:
            if failure["type"] == "connection_down":
                src, dst = failure["link"]

                # Find all paths between src and dst
                try:
                    all_paths = list(nx.all_simple_paths(graph, src, dst, cutoff=6))

                    # Score paths by capacity and hop count
                    scored_paths = []
                    for path in all_paths:
                        capacity = _calculate_path_capacity(graph, path)
                        latency = _calculate_path_latency(graph, path)

                        scored_paths.append(
                            {
                                "path": path,
                                "hops": len(path) - 1,
                                "capacity_gbps": capacity,
                                "estimated_latency_ms": latency,
                            }
                        )

                    # Sort by capacity (descending), then hops (ascending)
                    scored_paths.sort(key=lambda x: (-x["capacity_gbps"], x["hops"]))

                    remediation_plan.append(
                        {
                            "failure": failure,
                            "status": "RESOLVABLE" if scored_paths else "CRITICAL",
                            "alternate_paths": scored_paths[:3],  # Top 3 paths
                            "recommendation": (
                                f"Use backup path: {' → '.join(scored_paths[0]['path'])}"
                                if scored_paths
                                else "No alternate path available - requires physical repair"
                            ),
                        }
                    )
                    
                    # Check end-to-end connectivity for hosts after this failure
                    if not scored_paths:
                        # Connection is down with no alternate - check host impact
                        affected_hosts = _find_affected_hosts(graph, blueprint, src, dst)
                        if affected_hosts:
                            remediation_plan[-1]["affected_hosts"] = affected_hosts
                            remediation_plan[-1]["impact"] = (
                                f"CRITICAL: {len(affected_hosts)} host(s) may lose connectivity"
                            )

                except nx.NetworkXNoPath:
                    # Check which hosts are affected by this failure
                    affected_hosts = _find_affected_hosts(graph, blueprint, src, dst)
                    
                    remediation_plan.append(
                        {
                            "failure": failure,
                            "status": "CRITICAL",
                            "alternate_paths": [],
                            "recommendation": "No alternate path available - requires physical repair",
                            "affected_hosts": affected_hosts,
                            "impact": f"CRITICAL: {len(affected_hosts)} host(s) may lose connectivity" if affected_hosts else "Switch-to-switch connectivity lost"
                        }
                    )

            elif failure["type"] in ("plugged_out", "cable_cut", "traffic_drop"):
                # Port-specific failures - check connectivity impact
                switch_id = failure.get("switch")
                
                # Find which connections are affected
                affected_connections = []
                for link in blueprint.links:
                    if link.src == switch_id or link.dst == switch_id:
                        affected_connections.append((link.src, link.dst))
                
                remediation_plan.append(
                    {
                        "failure": failure,
                        "status": "ACTION_REQUIRED",
                        "recommendation": _generate_port_failure_recommendation(failure),
                        "affected_connections": affected_connections,
                        "impact": f"May affect {len(affected_connections)} connection(s)"
                    }
                )

        # Add overall connectivity analysis
        if host_nodes:
            connectivity_matrix = _analyze_host_connectivity(graph, host_nodes)
            state["connectivity_matrix"] = connectivity_matrix
            
            # Count disconnected pairs
            total_pairs = len(host_nodes) * (len(host_nodes) - 1) // 2
            connected_pairs = sum(1 for row in connectivity_matrix.values() 
                                for can_reach in row.values() if can_reach)
            
            logger.info(f"Host connectivity: {connected_pairs}/{total_pairs} pairs can reach each other")

        state["remediation_plan"] = remediation_plan
        state["status"] = "planning"

        logger.info(f"Generated remediation plan with {len(remediation_plan)} items")

    except Exception as e:
        logger.error(f"Failed to find alternate paths: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)

    return state


def llm_analysis_node(
    state: GUIDatacenterState, llm: BaseLanguageModel
) -> GUIDatacenterState:
    """Node: Use LLM to analyze failures and suggest remediation approach."""
    logger.info("Requesting LLM analysis of failures")

    try:
        failures = state["failures"]
        remediation_plan = state["remediation_plan"]

        # Build prompt
        system_prompt = """You are a network operations expert analyzing datacenter network failures.
Your role is to provide clear, actionable analysis and prioritize remediation steps.

Focus on:
1. Impact assessment (which services/hosts are affected)
2. Root cause analysis
3. Priority ranking of fixes
4. Risk assessment of proposed changes
5. Verification steps after remediation

Be concise and technical."""

        failure_summary = "\n".join(
            [
                f"- {f['type']} at {f.get('switch', f.get('link', 'unknown'))} [{f['severity']}]"
                for f in failures
            ]
        )

        remediation_summary = "\n".join(
            [
                f"- {plan['failure']['type']}: {plan['recommendation']}"
                for plan in remediation_plan
            ]
        )

        user_query = state.get("user_query", "Analyze these network failures and provide remediation guidance.")

        prompt = f"""Network Topology Analysis Request:
{user_query}

Detected Failures:
{failure_summary}

Proposed Remediation:
{remediation_summary}

Please provide:
1. Impact assessment
2. Priority ranking
3. Risk analysis
4. Detailed remediation steps
"""

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]

        response = llm.invoke(messages)
        llm_analysis = response.content if hasattr(response, "content") else str(response)

        state["llm_analysis"] = llm_analysis
        state["messages"] = messages + [AIMessage(content=llm_analysis)]

        logger.info("LLM analysis complete")

    except Exception as e:
        logger.error(f"LLM analysis failed: {e}")
        state["llm_analysis"] = f"LLM analysis unavailable: {e}"

    return state


def generate_runbook_node(
    state: GUIDatacenterState, llm: BaseLanguageModel
) -> GUIDatacenterState:
    """Node: Generate human-readable remediation runbook."""
    logger.info("Generating remediation runbook")

    try:
        blueprint = state["blueprint"]
        failures = state["failures"]
        remediation_plan = state["remediation_plan"]
        llm_analysis = state.get("llm_analysis", "")

        # Build runbook sections
        sections = []

        # Header
        sections.append("=" * 80)
        sections.append("NETWORK REMEDIATION RUNBOOK")
        sections.append("=" * 80)
        sections.append("")
        sections.append(f"Topology: {blueprint.name}")
        sections.append(
            f"Nodes: {len(blueprint.nodes)} ({len([n for n in blueprint.nodes if n.node_type == 'switch'])} switches)"
        )
        sections.append(f"Links: {len(blueprint.links)}")
        sections.append(f"Failures Detected: {len(failures)}")
        sections.append("")

        # Executive Summary
        sections.append("EXECUTIVE SUMMARY")
        sections.append("-" * 80)
        sections.append(llm_analysis.split("\n\n")[0] if llm_analysis else "Analysis pending")
        sections.append("")

        # Failures Detail
        sections.append("DETECTED FAILURES")
        sections.append("-" * 80)
        for i, failure in enumerate(failures, 1):
            sections.append(f"{i}. {failure['type'].upper()}")
            sections.append(f"   Location: {failure.get('switch', failure.get('link', 'N/A'))}")
            sections.append(f"   Severity: {failure['severity']}")
            sections.append(f"   Detected From: {failure['detected_from']}")
            sections.append("")

        # Remediation Steps
        sections.append("REMEDIATION PLAN")
        sections.append("-" * 80)
        for i, plan in enumerate(remediation_plan, 1):
            failure = plan["failure"]
            sections.append(f"{i}. {failure['type'].upper()}")
            sections.append(f"   Status: {plan['status']}")
            sections.append(f"   Recommendation: {plan['recommendation']}")

            if "alternate_paths" in plan and plan["alternate_paths"]:
                sections.append("")
                sections.append("   Alternate Paths:")
                for j, path_info in enumerate(plan["alternate_paths"][:3], 1):
                    path = " → ".join(path_info["path"])
                    sections.append(
                        f"      Option {j}: {path} "
                        f"(Capacity: {path_info['capacity_gbps']:.1f} Gbps, "
                        f"Hops: {path_info['hops']}, "
                        f"Latency: +{path_info['estimated_latency_ms']}ms)"
                    )

            sections.append("")

        # LLM Analysis
        sections.append("DETAILED ANALYSIS")
        sections.append("-" * 80)
        sections.append(llm_analysis or "No detailed analysis available")
        sections.append("")

        # Footer
        sections.append("=" * 80)
        sections.append("END OF RUNBOOK")
        sections.append("")
        sections.append("⚠️  NOTE: This is an advisory report. No changes have been made to the network.")
        sections.append("    Review recommendations carefully before applying changes.")
        sections.append("=" * 80)

        runbook = "\n".join(sections)
        state["runbook"] = runbook
        state["status"] = "complete"

        logger.info("Runbook generated successfully")

    except Exception as e:
        logger.error(f"Failed to generate runbook: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)

    return state


# Routing functions


def route_by_failures(state: GUIDatacenterState) -> Literal["no_failures", "has_failures"]:
    """Route based on whether failures were detected."""
    failure_count = state.get("failure_count", 0)

    if failure_count == 0:
        logger.info("No failures detected - ending workflow")
        return "no_failures"

    logger.info(f"Detected {failure_count} failures - proceeding with remediation")
    return "has_failures"


# Helper functions


def _calculate_path_capacity(graph: nx.Graph, path: List[str]) -> float:
    """Calculate bottleneck capacity along a path."""
    if len(path) < 2:
        return 0.0

    capacities = []
    for i in range(len(path) - 1):
        edge_data = graph.get_edge_data(path[i], path[i + 1])
        if edge_data:
            capacities.append(edge_data.get("capacity_gbps", 10.0))

    return min(capacities) if capacities else 0.0


def _calculate_path_latency(graph: nx.Graph, path: List[str]) -> int:
    """Calculate total latency along a path."""
    if len(path) < 2:
        return 0

    total_latency = 0
    for i in range(len(path) - 1):
        edge_data = graph.get_edge_data(path[i], path[i + 1])
        if edge_data:
            total_latency += edge_data.get("delay_ms", 2)

    return total_latency


def _generate_port_failure_recommendation(failure: Dict[str, Any]) -> str:
    """Generate recommendation for port-level failures."""
    failure_type = failure["type"]
    switch = failure.get("switch_name", failure.get("switch", "unknown"))
    port = failure.get("port", "unknown")

    if failure_type == "plugged_out":
        return (
            f"Physical inspection required: Cable unplugged from {switch} port {port}. "
            "Verify cable is properly seated and SFP module is correctly installed."
        )
    elif failure_type == "cable_cut":
        return (
            f"Cable replacement required: {switch} port {port} has a severed cable. "
            "Replace cable and verify physical layer integrity."
        )
    elif failure_type == "traffic_drop":
        return (
            f"Traffic anomaly detected on {switch} port {port}. "
            "Check for: CRC errors, duplex mismatch, congestion, or faulty hardware."
        )
    else:
        return f"Unknown failure type '{failure_type}' on {switch} port {port}"


def _find_affected_hosts(graph: nx.Graph, blueprint, failed_switch_a: str, failed_switch_b: str) -> List[str]:
    """Find hosts that may lose connectivity due to a switch-to-switch link failure."""
    affected = []
    
    # Get all host nodes
    host_nodes = [n for n in blueprint.nodes if n.node_type == "host"]
    
    for host in host_nodes:
        # Check if this host depends on the failed link for connectivity
        # to other parts of the network
        try:
            # Find the switch this host connects to
            host_switch = host.metadata.get("switch_id")
            
            if not host_switch:
                continue
                
            # If host is connected to one of the failed switches,
            # it might be affected
            if host_switch in (failed_switch_a, failed_switch_b):
                # Try to find alternate path to other side
                other_switch = failed_switch_b if host_switch == failed_switch_a else failed_switch_a
                
                if not nx.has_path(graph, host_switch, other_switch):
                    affected.append(host.name)
                    
        except Exception as e:
            logger.warning(f"Error checking host {host.name}: {e}")
            continue
    
    return affected


def _analyze_host_connectivity(graph: nx.Graph, host_nodes: List[str]) -> Dict[str, Dict[str, bool]]:
    """Analyze which hosts can reach which other hosts."""
    connectivity = {}
    
    for src_host in host_nodes:
        connectivity[src_host] = {}
        for dst_host in host_nodes:
            if src_host == dst_host:
                connectivity[src_host][dst_host] = True
            else:
                # Check if path exists (considering current graph state)
                try:
                    connectivity[src_host][dst_host] = nx.has_path(graph, src_host, dst_host)
                except nx.NodeNotFound:
                    connectivity[src_host][dst_host] = False
    
    return connectivity

