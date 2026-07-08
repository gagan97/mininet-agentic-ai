"""LangGraph workflow for GUI-driven datacenter remediation agent.

This module implements a LangGraph StateGraph that:
1. Fetches topology from GUI REST API
2. Detects failures from connection/port states
3. Analyzes network graph to find alternate paths
4. Uses LLM to generate remediation suggestions
5. Uses LLM to classify fixes as auto-fixable vs manual (reasoning-based)
6. Prompts user for approval to apply auto-fixes
7. Executes approved fixes via GUI API

The workflow uses LLM reasoning to determine which fixes can be automated
based on available tools, network topology, and risk assessment.
"""

from __future__ import annotations

import json
import re
import requests
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
    auto_fix_enabled: bool

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
    
    # Auto-fix classification (LLM-driven)
    llm_classification_reasoning: str  # LLM's step-by-step reasoning
    auto_fixable_actions: List[Dict[str, Any]]
    manual_actions: List[Dict[str, Any]]
    fix_proposal: str
    user_approved_fixes: bool
    
    # Execution results
    executed_fixes: List[Dict[str, Any]]
    fix_results: str

    # LLM interaction
    messages: List[HumanMessage | AIMessage | SystemMessage]
    llm_analysis: str

    # Status tracking
    status: Literal["idle", "fetching", "analyzing", "planning", "proposing_fixes", "awaiting_approval", "executing_fixes", "complete", "error"]
    error_message: str | None


def build_gui_datacenter_graph(llm: BaseLanguageModel, interactive_mode: bool = True) -> StateGraph:
    """Build LangGraph workflow for GUI-driven datacenter agent.

    Args:
        llm: Language model for reasoning and runbook generation
        interactive_mode: If True, prompt user for fix approval. If False, skip to complete.

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
    workflow.add_node("classify_fixes", lambda state: classify_fixes_node(state, llm))
    workflow.add_node("propose_fixes", propose_fixes_node)
    workflow.add_node("execute_fixes", execute_fixes_node)

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
    
    if interactive_mode:
        workflow.add_edge("generate_runbook", "classify_fixes")
        workflow.add_edge("classify_fixes", "propose_fixes")
        
        # Conditional routing based on user approval
        workflow.add_conditional_edges(
            "propose_fixes",
            route_by_user_approval,
            {
                "approved": "execute_fixes",
                "rejected": END,
                "no_fixes": END,
            },
        )
        
        workflow.add_edge("execute_fixes", END)
    else:
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
            
            elif failure["type"] == "port_congestion":
                # Port congestion - find alternate paths for load balancing
                switch_id = failure.get("switch")
                
                # Find connections from this switch
                alternate_paths = []
                for link in blueprint.links:
                    if link.src == switch_id:
                        # Try to find parallel paths to same destination
                        try:
                            all_paths = list(nx.all_simple_paths(graph, link.src, link.dst, cutoff=6))
                            if len(all_paths) > 1:  # Multiple paths exist
                                for path in all_paths[1:]:  # Skip primary path
                                    capacity = _calculate_path_capacity(graph, path)
                                    latency = _calculate_path_latency(graph, path)
                                    alternate_paths.append({
                                        "path": path,
                                        "hops": len(path) - 1,
                                        "capacity_gbps": capacity,
                                        "estimated_latency_ms": latency,
                                    })
                        except:
                            pass
                
                remediation_plan.append({
                    "failure": failure,
                    "status": "RESOLVABLE" if alternate_paths else "ACTION_REQUIRED",
                    "alternate_paths": alternate_paths[:3] if alternate_paths else [],
                    "recommendation": (
                        f"Redistribute traffic across {len(alternate_paths)} parallel path(s)"
                        if alternate_paths
                        else "No parallel paths - consider link upgrade or traffic optimization"
                    ),
                })
            
            elif failure["type"] == "vlan_mismatch":
                # VLAN mismatch - configuration issue, typically fixable
                remediation_plan.append({
                    "failure": failure,
                    "status": "RESOLVABLE",
                    "alternate_paths": [],
                    "recommendation": (
                        f"Reconfigure VLAN on {failure.get('switch_name', 'unknown')} "
                        f"port {failure.get('port', 'N/A')} from VLAN {failure.get('currentVlan', '?')} "
                        f"to VLAN {failure.get('expectedVlan', '?')}"
                    ),
                })
            
            elif failure["type"] == "link_flap":
                # Link flapping - find stable alternate path
                if "link" in failure:
                    # Connection-level flapping
                    src, dst = failure["link"]
                    try:
                        all_paths = list(nx.all_simple_paths(graph, src, dst, cutoff=6))
                        # Score paths
                        scored_paths = []
                        for path in all_paths:
                            if len(path) == 2:  # Skip the flapping direct link
                                continue
                            capacity = _calculate_path_capacity(graph, path)
                            latency = _calculate_path_latency(graph, path)
                            scored_paths.append({
                                "path": path,
                                "hops": len(path) - 1,
                                "capacity_gbps": capacity,
                                "estimated_latency_ms": latency,
                            })
                        
                        scored_paths.sort(key=lambda x: (-x["capacity_gbps"], x["hops"]))
                        
                        remediation_plan.append({
                            "failure": failure,
                            "status": "RESOLVABLE" if scored_paths else "ACTION_REQUIRED",
                            "alternate_paths": scored_paths[:3],
                            "recommendation": (
                                f"Switch to stable alternate path: {' → '.join(scored_paths[0]['path'])}"
                                if scored_paths
                                else "No alternate path - investigate physical layer (cable, SFP)"
                            ),
                        })
                    except:
                        remediation_plan.append({
                            "failure": failure,
                            "status": "ACTION_REQUIRED",
                            "alternate_paths": [],
                            "recommendation": "Investigate physical layer issues (cable, SFP, port)",
                        })
                else:
                    # Port-level flapping
                    switch_id = failure.get("switch")
                    remediation_plan.append({
                        "failure": failure,
                        "status": "ACTION_REQUIRED",
                        "alternate_paths": [],
                        "recommendation": f"Check physical connection on {failure.get('switch_name', 'unknown')} port {failure.get('port', 'N/A')}",
                    })
            
            else:
                # Unknown failure type - add generic entry
                logger.warning(f"Unknown failure type: {failure['type']}")
                remediation_plan.append({
                    "failure": failure,
                    "status": "ACTION_REQUIRED",
                    "alternate_paths": [],
                    "recommendation": f"Manual investigation required for {failure['type']} issue",
                })

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


def classify_fixes_node(
    state: GUIDatacenterState, llm: BaseLanguageModel
) -> GUIDatacenterState:
    """Node: Use LLM to classify remediation actions into auto-fixable vs manual.
    
    The LLM reasons about:
    - Available tools and their capabilities
    - Nature of the failure
    - Network topology constraints
    - Risk assessment
    - Feasibility of automated fixes
    """
    logger.info("Using LLM to classify fixes into auto-fixable and manual actions")
    
    try:
        remediation_plan = state["remediation_plan"]
        blueprint = state.get("blueprint")
        
        # Build context about available tools and capabilities
        available_tools = _get_available_tools_description()
        
        # Prepare failure information for LLM
        failures_summary = []
        for i, plan in enumerate(remediation_plan):
            failure = plan["failure"]
            failures_summary.append({
                "index": i,
                "type": failure.get("type"),
                "location": f"{failure.get('switch', 'unknown')} port {failure.get('port', 'N/A')}",
                "details": failure,
                "alternate_paths_available": len(plan.get("alternate_paths", [])),
                "alternate_paths": plan.get("alternate_paths", []),
                "current_status": plan.get("status", "UNKNOWN"),
                "recommendation": plan.get("recommendation", "")
            })
        
        # Create LLM prompt for classification
        classification_prompt = f"""You are a network remediation expert. Analyze these network failures and determine which can be fixed automatically using available tools vs which require manual intervention.

AVAILABLE AUTOMATED REMEDIATION TOOLS:
{available_tools}

NETWORK TOPOLOGY CONTEXT:
- Total switches: {len(blueprint.nodes) if blueprint else 'unknown'}
- Network has redundant paths: {_has_redundancy(state)}
- Current health: {state.get('failure_count', 0)} failures detected

FAILURES TO ANALYZE:
{json.dumps(failures_summary, indent=2)}

REASONING INSTRUCTIONS:
1. For EACH failure, reason about whether it can be fixed automatically
2. Consider:
   - Is this a software/configuration issue or hardware/physical issue?
   - Do we have the right tools available?
   - Are alternate paths available if needed?
   - What is the risk level (LOW/MEDIUM/HIGH)?
   - Will this fix interfere with other services?
3. Physical issues (cable cuts, unplugged cables, hardware failures) CANNOT be fixed remotely
4. Configuration issues (VLAN, routing, traffic distribution) CAN be fixed if tools exist
5. Path-related issues CAN be fixed only if alternate paths exist

OUTPUT FORMAT (JSON):
{{
  "reasoning": "Your step-by-step reasoning about each failure",
  "classifications": [
    {{
      "failure_index": 0,
      "can_autofix": true/false,
      "reasoning": "Why this can or cannot be fixed automatically",
      "action": "tool_name_to_use" or null,
      "risk_level": "LOW/MEDIUM/HIGH",
      "prerequisites": ["list", "of", "conditions"],
      "alternative_if_fails": "What to do if automated fix fails"
    }}
  ]
}}

Think step-by-step and be conservative - if there's significant risk or uncertainty, classify as manual.
"""

        # Get LLM classification
        logger.info("Querying LLM for fix classification reasoning...")
        
        response = llm.invoke([HumanMessage(content=classification_prompt)])
        
        # Parse LLM response (json and re already imported at top of file)
        # Extract JSON from response (handle markdown code blocks)
        response_text = response.content if hasattr(response, 'content') else str(response)
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Try to find JSON object directly
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            json_str = json_match.group(0) if json_match else response_text
        
        try:
            llm_classification = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response text: {response_text[:500]}")
            # Fall back to empty classification
            llm_classification = {"reasoning": "Failed to parse", "classifications": []}
        
        logger.info(f"LLM Reasoning: {llm_classification.get('reasoning', 'N/A')[:200]}...")
        
        # Process LLM classifications
        auto_fixable: List[Dict[str, Any]] = []
        manual: List[Dict[str, Any]] = []
        
        for classification in llm_classification.get("classifications", []):
            failure_idx = classification.get("failure_index")
            if failure_idx is None or failure_idx >= len(remediation_plan):
                continue
                
            plan = remediation_plan[failure_idx]
            failure = plan["failure"]
            
            if classification.get("can_autofix", False):
                # LLM says this can be auto-fixed
                action_name = classification.get("action")
                risk_level = classification.get("risk_level", "MEDIUM")
                
                # Map LLM's action suggestion to our available actions
                action_mapping = {
                    "activate_backup_path": _build_activate_backup_action,
                    "redistribute_traffic": _build_redistribute_traffic_action,
                    "reconfigure_vlan": _build_reconfigure_vlan_action,
                    "stabilize_link": _build_stabilize_link_action,
                    "reroute_traffic": _build_reroute_traffic_action,
                }
                
                if action_name in action_mapping:
                    action = action_mapping[action_name](plan, classification)
                    if action:  # Only add if action was successfully built
                        auto_fixable.append(action)
                else:
                    logger.warning(f"LLM suggested unknown action: {action_name}")
                    # If LLM suggested an action we don't have, mark as manual
                    manual.append({
                        "failure": failure,
                        "reason": f"LLM suggested action '{action_name}' but tool not available",
                        "llm_reasoning": classification.get("reasoning", ""),
                        "description": plan.get("recommendation", "Manual intervention required"),
                    })
            else:
                # LLM says this requires manual intervention
                manual.append({
                    "failure": failure,
                    "reason": classification.get("reasoning", "Manual intervention required"),
                    "llm_reasoning": classification.get("reasoning", ""),
                    "description": plan.get("recommendation", ""),
                    "prerequisites": classification.get("prerequisites", []),
                })
        
        # Store LLM reasoning in state for transparency
        state["llm_classification_reasoning"] = llm_classification.get("reasoning", "")
        state["auto_fixable_actions"] = auto_fixable
        state["manual_actions"] = manual
        state["status"] = "proposing_fixes"
        
        logger.info(f"LLM classified {len(auto_fixable)} auto-fixable and {len(manual)} manual actions")
        
    except Exception as e:
        logger.error(f"Failed to classify fixes with LLM: {e}")
        import traceback
        logger.error(traceback.format_exc())
        state["status"] = "error"
        state["error_message"] = str(e)
    
    return state


def propose_fixes_node(state: GUIDatacenterState) -> GUIDatacenterState:
    """Node: Generate fix proposal for user approval, including LLM reasoning."""
    logger.info("Generating fix proposal for user")
    
    try:
        auto_fixable = state.get("auto_fixable_actions", [])
        manual = state.get("manual_actions", [])
        llm_reasoning = state.get("llm_classification_reasoning", "")
        
        if not auto_fixable:
            state["fix_proposal"] = "No auto-fixable actions available. All issues require manual intervention."
            state["user_approved_fixes"] = False
            state["status"] = "complete"
            return state
        
        # Build proposal text
        proposal_lines = []
        proposal_lines.append("\n" + "="*80)
        proposal_lines.append("AUTOMATED FIX PROPOSAL")
        proposal_lines.append("="*80)
        proposal_lines.append("")
        
        # Add LLM's reasoning for transparency
        if llm_reasoning:
            proposal_lines.append("🤖 AI AGENT REASONING:")
            proposal_lines.append("-" * 80)
            # Truncate reasoning if too long
            reasoning_preview = llm_reasoning[:400] + "..." if len(llm_reasoning) > 400 else llm_reasoning
            proposal_lines.append(reasoning_preview)
            proposal_lines.append("-" * 80)
            proposal_lines.append("")
        
        proposal_lines.append(f"The AI agent has analyzed the failures and identified {len(auto_fixable)} issue(s)")
        proposal_lines.append("that can be automatically fixed:")
        proposal_lines.append("")
        
        for i, action in enumerate(auto_fixable, 1):
            proposal_lines.append(f"{i}. {action['description']}")
            proposal_lines.append(f"   Risk Level: {action['risk']}")
            
            # Show LLM's reasoning for this specific action
            if action.get("llm_reasoning"):
                proposal_lines.append(f"   AI Reasoning: {action['llm_reasoning'][:150]}...")
            
            if action.get("best_path"):
                path_info = action["best_path"]
                proposal_lines.append(
                    f"   Details: Capacity {path_info['capacity_gbps']:.1f} Gbps, "
                    f"{path_info['hops']} hops, +{path_info['estimated_latency_ms']}ms latency"
                )
            elif action.get("details"):
                # Show other relevant details
                details = action["details"]
                detail_str = ", ".join([f"{k}: {v}" for k, v in details.items()])
                proposal_lines.append(f"   Details: {detail_str}")
            
            proposal_lines.append("")
        
        if manual:
            proposal_lines.append(f"Additionally, {len(manual)} issue(s) require manual intervention:")
            proposal_lines.append("")
            for i, action in enumerate(manual, 1):
                proposal_lines.append(f"{i}. {action['description']}")
                proposal_lines.append(f"   Reason: {action['reason']}")
                if action.get("llm_reasoning"):
                    proposal_lines.append(f"   AI Analysis: {action['llm_reasoning'][:150]}...")
                proposal_lines.append("")
        
        proposal_lines.append("="*80)
        proposal_lines.append("🤔 The AI agent has reasoned about available tools, network topology,")
        proposal_lines.append("   and potential risks to determine these fixes are safe to automate.")
        proposal_lines.append("")
        proposal_lines.append("Would you like the agent to apply these automated fixes? (yes/no)")
        proposal_lines.append("="*80)
        
        state["fix_proposal"] = "\n".join(proposal_lines)
        state["status"] = "awaiting_approval"
        
        logger.info("Fix proposal generated with LLM reasoning, awaiting user approval")
        
    except Exception as e:
        logger.error(f"Failed to generate fix proposal: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)
    
    return state


def execute_fixes_node(state: GUIDatacenterState) -> GUIDatacenterState:
    """Node: Execute approved automated fixes via GUI API."""
    logger.info("Executing approved automated fixes")
    
    try:
        auto_fixable = state.get("auto_fixable_actions", [])
        gui_url = state["gui_url"]
        executed: List[Dict[str, Any]] = []
        
        for action in auto_fixable:
            try:
                result = _execute_fix_via_api(gui_url, action)
                executed.append({
                    "action": action,
                    "result": result,
                    "status": "SUCCESS" if result.get("success") else "FAILED",
                })
                logger.info(f"Fix executed: {action['description']} - {result.get('status', 'completed')}")
            except Exception as e:
                executed.append({
                    "action": action,
                    "result": {"error": str(e)},
                    "status": "ERROR",
                })
                logger.error(f"Failed to execute fix: {action['description']} - {e}")
        
        # Generate results summary
        result_lines = []
        result_lines.append("\n" + "="*80)
        result_lines.append("FIX EXECUTION RESULTS")
        result_lines.append("="*80)
        result_lines.append("")
        
        success_count = sum(1 for e in executed if e["status"] == "SUCCESS")
        result_lines.append(f"Executed {len(executed)} fix(es): {success_count} succeeded, {len(executed) - success_count} failed")
        result_lines.append("")
        
        for i, exec_result in enumerate(executed, 1):
            action = exec_result["action"]
            status = exec_result["status"]
            result_lines.append(f"{i}. {action['description']}")
            result_lines.append(f"   Status: {status}")
            if exec_result["result"].get("error"):
                result_lines.append(f"   Error: {exec_result['result']['error']}")
            result_lines.append("")
        
        result_lines.append("="*80)
        result_lines.append("Fixes applied. Please verify network connectivity.")
        result_lines.append("="*80)
        
        state["executed_fixes"] = executed
        state["fix_results"] = "\n".join(result_lines)
        state["status"] = "complete"
        
        logger.info(f"Fix execution complete: {success_count}/{len(executed)} successful")
        
    except Exception as e:
        logger.error(f"Failed to execute fixes: {e}")
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


def route_by_user_approval(state: GUIDatacenterState) -> Literal["approved", "rejected", "no_fixes"]:
    """Route based on user approval of fixes."""
    auto_fixable = state.get("auto_fixable_actions", [])
    
    if not auto_fixable:
        logger.info("No auto-fixable actions available")
        return "no_fixes"
    
    # Check if user approved (set by external caller)
    approved = state.get("user_approved_fixes", False)
    
    if approved:
        logger.info("User approved automated fixes - proceeding with execution")
        return "approved"
    else:
        logger.info("User rejected automated fixes - ending workflow")
        return "rejected"


# Helper functions


def _get_available_tools_description() -> str:
    """Generate description of available automated remediation tools for LLM."""
    return """
1. **activate_backup_path**
   - Purpose: Activate an alternate network path when primary path fails
   - Requirements: Alternate path must exist in topology
   - Capabilities: Can switch traffic to backup route
   - Risk: LOW - Non-disruptive if alternate path is healthy
   - Cannot fix: Physical cable issues, hardware failures

2. **redistribute_traffic**
   - Purpose: Balance network load across parallel paths
   - Requirements: Multiple paths between same endpoints
   - Capabilities: Can reduce congestion by spreading traffic
   - Risk: LOW - Improves performance without service interruption
   - Cannot fix: Issues where no parallel paths exist

3. **reconfigure_vlan**
   - Purpose: Change VLAN assignment on a network port
   - Requirements: Port must be accessible via API
   - Capabilities: Can fix VLAN misconfiguration remotely
   - Risk: MEDIUM - Brief interruption during VLAN change
   - Cannot fix: Physical port issues, SFP problems

4. **stabilize_link**
   - Purpose: Handle flapping links by switching to stable alternate
   - Requirements: Stable alternate path available
   - Capabilities: Can move traffic away from unstable link
   - Risk: LOW - Prevents service degradation from flapping
   - Cannot fix: Physical layer instability, faulty hardware

5. **reroute_traffic**
   - Purpose: Reroute traffic to avoid degraded links
   - Requirements: Alternate path with better performance
   - Capabilities: Can avoid packet loss or high latency links
   - Risk: LOW - Improves service quality
   - Cannot fix: Issues affecting all paths

LIMITATIONS:
- Cannot physically repair cables or hardware
- Cannot replace SFP modules
- Cannot fix issues in devices not accessible via API
- Cannot create new network paths (only use existing ones)
"""


def _has_redundancy(state: GUIDatacenterState) -> bool:
    """Check if network topology has redundant paths."""
    graph = state.get("graph")
    if not graph:
        return False
    
    # Simple check: if graph has cycles, there's redundancy
    import networkx as nx
    try:
        cycles = list(nx.simple_cycles(graph))
        return len(cycles) > 0
    except:
        return False


def _build_activate_backup_action(plan: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
    """Build action dict for activating backup path."""
    if not plan.get("alternate_paths"):
        return None
    
    return {
        "action": "activate_backup_path",
        "failure": plan["failure"],
        "best_path": plan["alternate_paths"][0],
        "description": f"Activate backup path: {' → '.join(plan['alternate_paths'][0]['path'])}",
        "risk": classification.get("risk_level", "LOW"),
        "llm_reasoning": classification.get("reasoning", ""),
    }


def _build_redistribute_traffic_action(plan: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
    """Build action dict for redistributing traffic."""
    if not plan.get("alternate_paths"):
        return None
    
    return {
        "action": "redistribute_traffic",
        "failure": plan["failure"],
        "parallel_paths": plan["alternate_paths"],
        "description": f"Redistribute traffic to reduce congestion",
        "risk": classification.get("risk_level", "LOW"),
        "llm_reasoning": classification.get("reasoning", ""),
        "details": {
            "current_utilization": plan['failure'].get('utilization', '95%'),
            "target_utilization": "50%"
        }
    }


def _build_reconfigure_vlan_action(plan: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
    """Build action dict for reconfiguring VLAN."""
    failure = plan["failure"]
    
    return {
        "action": "reconfigure_vlan",
        "failure": failure,
        "description": f"Reconfigure VLAN on port {failure.get('port')}",
        "risk": classification.get("risk_level", "MEDIUM"),
        "llm_reasoning": classification.get("reasoning", ""),
        "details": {
            "port_id": failure.get('port_id'),
            "current_vlan": failure.get('currentVlan'),
            "target_vlan": failure.get('expectedVlan')
        }
    }


def _build_stabilize_link_action(plan: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
    """Build action dict for stabilizing flapping link."""
    if not plan.get("alternate_paths"):
        return None
    
    return {
        "action": "stabilize_link",
        "failure": plan["failure"],
        "alternate_path": plan["alternate_paths"][0],
        "description": f"Stabilize flapping link by switching to alternate path",
        "risk": classification.get("risk_level", "LOW"),
        "llm_reasoning": classification.get("reasoning", ""),
        "details": {
            "flap_count": plan['failure'].get('flapCount', 'unknown'),
            "connection_id": plan['failure'].get('connection_id')
        }
    }


def _build_reroute_traffic_action(plan: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
    """Build action dict for rerouting traffic."""
    if not plan.get("alternate_paths"):
        return None
    
    return {
        "action": "reroute_traffic",
        "failure": plan["failure"],
        "best_path": plan["alternate_paths"][0],
        "description": f"Reroute traffic via alternate path to avoid degraded link",
        "risk": classification.get("risk_level", "LOW"),
        "llm_reasoning": classification.get("reasoning", ""),
    }


def _execute_fix_via_api(gui_url: str, action: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a fix action via GUI API.
    
    Args:
        gui_url: Base URL of GUI API
        action: Action dictionary with type and parameters
        
    Returns:
        Result dictionary from API
    """
    import requests
    
    action_type = action.get("action")
    
    if action_type == "activate_backup_path":
        # Call API to activate backup path
        path = action["best_path"]["path"]
        
        endpoint = f"{gui_url.rstrip('/')}/api/network/activate-backup-path"
        payload = {
            "path": path,
            "reason": f"Auto-remediation for {action['failure']['type']}",
        }
        
        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"API call failed: {e}")
            return {"success": False, "error": str(e)}
    
    elif action_type == "reroute_traffic":
        # Call API to reroute traffic
        path = action["best_path"]["path"]
        
        endpoint = f"{gui_url.rstrip('/')}/api/network/reroute-traffic"
        payload = {
            "path": path,
            "source": path[0],
            "destination": path[-1],
            "reason": f"Auto-remediation for {action['failure']['type']}",
        }
        
        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"API call failed: {e}")
            return {"success": False, "error": str(e)}
    
    elif action_type == "redistribute_traffic":
        # Call API to redistribute traffic across parallel paths
        failure = action["failure"]
        
        # Extract switch IDs from link tuple
        link = failure.get("link", [])
        if len(link) >= 2:
            src, dst = link[0], link[1]
        else:
            return {"success": False, "error": "Invalid link format in failure data"}
        
        endpoint = f"{gui_url.rstrip('/')}/api/network/redistribute-traffic"
        payload = {
            "congestedLink": {"src": src, "dst": dst},
            "alternatePaths": action.get("parallel_paths", []),
            "flowDistribution": {"primary": 50, "alternate": 50},
            "reason": f"Auto-remediation for port congestion",
        }
        
        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"API call failed: {e}")
            return {"success": False, "error": str(e)}
    
    elif action_type == "reconfigure_vlan":
        # Call API to reconfigure VLAN
        details = action.get("details", {})
        port_id = details.get("port_id")
        target_vlan = details.get("target_vlan")
        
        if not port_id or not target_vlan:
            return {"success": False, "error": "Missing port_id or target_vlan in action details"}
        
        endpoint = f"{gui_url.rstrip('/')}/api/network/port/{port_id}/vlan"
        payload = {
            "vlan": target_vlan,
            "reason": "Auto-remediation for VLAN mismatch",
        }
        
        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"API call failed: {e}")
            return {"success": False, "error": str(e)}
    
    elif action_type == "stabilize_link":
        # Call API to stabilize flapping link
        details = action.get("details", {})
        connection_id = details.get("connection_id")
        alternate_path = action.get("alternate_path", {})
        
        if not connection_id:
            return {"success": False, "error": "Missing connection_id in action details"}
        
        endpoint = f"{gui_url.rstrip('/')}/api/network/stabilize-link"
        payload = {
            "connectionId": connection_id,
            "alternatePath": alternate_path,
            "reason": "Auto-remediation for link flapping",
        }
        
        try:
            response = requests.post(endpoint, json=payload, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"API call failed: {e}")
            return {"success": False, "error": str(e)}
    
    else:
        return {"success": False, "error": f"Unknown action type: {action_type}"}


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

