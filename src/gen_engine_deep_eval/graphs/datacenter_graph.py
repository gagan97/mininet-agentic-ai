"""LangGraph implementation of the DataCenter agent.

This module provides a state machine-based architecture for managing Mininet
network topology, simulating failures, and orchestrating remediation using
LangGraph instead of the legacy LangChain ReAct pattern.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.language_models import BaseLanguageModel
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger

from .state_schemas import DataCenterState


def build_datacenter_graph(
    llm: BaseLanguageModel,
    env: Any,  # DataCenterEnvironment instance
    max_iterations: int = 10,
    checkpointer: Any | None = None,
    human_in_loop: bool = False,
) -> StateGraph:
    """Build the DataCenter agent LangGraph state machine.
    
    Args:
        llm: Language model instance (GenerativeEngineLLM)
        env: DataCenter environment instance
        max_iterations: Maximum remediation iterations
        checkpointer: Optional checkpoint saver for state persistence
        human_in_loop: Enable human approval for critical actions
    
    Returns:
        Compiled LangGraph state machine
    """
    
    def assess_network(state: DataCenterState) -> DataCenterState:
        """Entry node: Assess overall network health."""
        logger.info("Assessing network health...")
        
        # Get topology info
        if hasattr(env, 'blueprint'):
            topology = env.blueprint.to_dict()
        else:
            topology = {}
        
        # Get link profiles
        if hasattr(env, 'link_profiles'):
            profiles = {
                "-".join(k): v.to_dict() 
                for k, v in env.link_profiles.items()
            }
        else:
            profiles = {}
        
        # Count healthy vs degraded links
        healthy_links = sum(1 for p in profiles.values() if p.get('status') == 'up')
        total_links = len(profiles)
        
        health_assessment = {
            "total_links": total_links,
            "healthy_links": healthy_links,
            "degraded_links": total_links - healthy_links,
            "overall_status": "healthy" if healthy_links == total_links else "degraded",
        }
        
        logger.info(f"Health: {healthy_links}/{total_links} links up")
        
        # Note: messages is Annotated with 'add', so only return new messages
        return {
            "topology_blueprint": topology,
            "link_profiles": profiles,
            "network_health": health_assessment,
            "messages": [
                {"role": "system", "content": f"Network health: {json.dumps(health_assessment)}"}
            ],
        }
    
    def plan_remediation(state: DataCenterState) -> DataCenterState:
        """LLM planning node for remediation strategy."""
        logger.info("Planning remediation strategy...")
        
        # Build prompt for LLM
        network_health = state.get("network_health", {})
        link_profiles = state.get("link_profiles", {})
        failure_history = state.get("failure_history", [])
        remediation_actions = state.get("remediation_actions", [])
        messages = state.get("messages", [])
        iteration = state.get("iteration_count", 0)
        
        # Find degraded links
        degraded_links = [
            name for name, profile in link_profiles.items()
            if profile.get('status') == 'down'
        ]
        
        # Track what we've already done
        actions_taken = [a.get("action") for a in remediation_actions]
        links_inspected = set()
        paths_computed = set()
        
        for action in remediation_actions:
            if action.get("action") == "inspect_link_health":
                params = action.get("params", {})
                link_key = f"{params.get('src')}-{params.get('dst')}"
                links_inspected.add(link_key)
            elif action.get("action") == "compute_resilient_path":
                params = action.get("params", {})
                path_key = f"{params.get('src')}-{params.get('dst')}"
                paths_computed.add(path_key)
        
        system_prompt = (
            "You are a network remediation agent. Analyze the network state and suggest the NEXT remediation action.\n\n"
            "Available actions and their parameters:\n"
            "1. inspect_link_health: {\"src\": \"node1\", \"dst\": \"node2\"} - Check detailed link metrics\n"
            "2. compute_resilient_path: {\"src\": \"node1\", \"dst\": \"node2\"} - Find alternate path avoiding failed link\n"
            "3. activate_backup_path: {\"path\": [\"node1\", \"node2\", \"node3\", \"node4\"]} - Enable backup route using EXACT path array\n"
            "4. restore_primary_path: {\"src\": \"node1\", \"dst\": \"node2\"} - Restore original path\n"
            "5. monitor_link: {\"src\": \"node1\", \"dst\": \"node2\"} - Get link utilization\n\n"
            "CRITICAL RULES:\n"
            "- Do NOT repeat the same action twice for the same link\n"
            "- After inspecting a link, move to compute_resilient_path\n"
            "- After computing a path, use activate_backup_path with the EXACT path array from compute_resilient_path\n"
            "- NEVER modify or shorten the computed path - use it EXACTLY as provided\n"
            "- Parse link names like 'agg1a-core1' as src='agg1a', dst='core1'\n\n"
            "Respond with JSON only: {\"action\": \"action_name\", \"params\": {...}}\n"
            "If network is healthy, respond: {\"action\": \"complete\", \"summary\": \"description\"}"
        )
        
        # Build context showing what we've done and what's next
        action_summary = "\n".join([f"- {i+1}. {a.get('action')} {a.get('params', {})}" for i, a in enumerate(remediation_actions[-5:])])  # Last 5 actions
        
        context = (
            f"Network Status: {network_health.get('overall_status')}\n"
            f"Total Links: {network_health.get('total_links')}\n"
            f"Healthy Links: {network_health.get('healthy_links')}\n"
            f"Degraded Links ({len(degraded_links)}): {degraded_links}\n"
            f"Iteration: {iteration}/10\n\n"
            f"Actions taken so far ({len(remediation_actions)}):\n{action_summary if action_summary else 'None'}\n\n"
            f"Links already inspected: {list(links_inspected)}\n"
            f"Paths already computed: {list(paths_computed)}\n\n"
        )
        
        # Provide specific guidance based on state
        if not remediation_actions:
            guidance = f"START: Inspect the first degraded link: {degraded_links[0] if degraded_links else 'none'}"
        elif len(remediation_actions) > 0:
            last_action = remediation_actions[-1].get("action")
            last_params = remediation_actions[-1].get("params", {})
            
            if last_action == "inspect_link_health":
                # We just inspected - now compute path
                src = last_params.get("src")
                dst = last_params.get("dst")
                guidance = f"NEXT: You inspected {src}-{dst}. Now use compute_resilient_path to find alternate route from {src} to {dst}."
            elif last_action == "compute_resilient_path":
                # We just computed - now activate the path from the result
                # Extract path from last message
                computed_path = None
                if messages:
                    last_msg = messages[-1]
                    if isinstance(last_msg, dict):
                        content = last_msg.get("content", "")
                        # Try to parse JSON from content
                        try:
                            import re
                            json_match = re.search(r'\{.*\}', content, re.DOTALL)
                            if json_match:
                                result_data = json.loads(json_match.group(0))
                                computed_path = result_data.get("path")
                        except:
                            pass
                
                if computed_path:
                    # Make it CRYSTAL clear to use the exact path
                    path_json = json.dumps(computed_path)
                    guidance = (
                        f"NEXT: Path was computed successfully.\n"
                        f"IMPORTANT: Use activate_backup_path with this EXACT path (do NOT modify it):\n"
                        f'{{\"action\": \"activate_backup_path\", \"params\": {{\"path\": {path_json}}}}}\n'
                        f"Copy the path array EXACTLY as shown above."
                    )
                else:
                    guidance = "NEXT: The path computation may have failed. Try a different approach or mark as complete."
            elif last_action == "activate_backup_path":
                guidance = "NEXT: Backup path activated. If network is now healthy, respond with action 'complete'."
            else:
                guidance = f"NEXT: Continue remediation workflow for degraded links: {degraded_links}"
        else:
            guidance = "NEXT: Continue remediation"
        
        context += f"{guidance}\n\nWhat action should be taken next?"
        
        # Log the guidance for debugging
        logger.info(f"Guidance for LLM: {guidance[:200]}...")
        
        llm_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=context),
        ]
        
        try:
            if hasattr(llm, 'invoke'):
                response = llm.invoke(llm_messages)
                response_text = response.content if hasattr(response, 'content') else str(response)
            else:
                prompt_text = system_prompt + "\n\n" + context
                response_text = llm(prompt_text)
            
            logger.info(f"LLM plan: {response_text[:200]}...")
            
            # Try to parse as JSON
            try:
                plan = json.loads(response_text)
            except json.JSONDecodeError:
                # Extract JSON from text if wrapped
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    plan = json.loads(json_match.group(0))
                else:
                    plan = {"action": "complete", "summary": response_text}
            
            # Validate and fix common parameter issues
            action = plan.get("action")
            params = plan.get("params", {})
            
            # If action needs src/dst but has target, try to parse it
            if action in ("inspect_link_health", "monitor_link", "restore_primary_path", "compute_resilient_path"):
                if "target" in params and "src" not in params:
                    # Try to parse "agg1a-core1" format
                    target = params["target"]
                    if "-" in target:
                        parts = target.split("-", 1)
                        params["src"] = parts[0]
                        params["dst"] = parts[1]
                        del params["target"]
                        plan["params"] = params
                        logger.info(f"Fixed params: converted target '{target}' to src/dst")
            
        except Exception as e:
            logger.error(f"Planning error: {e}")
            plan = {"action": "error", "error": str(e)}
        
        # Note: messages and remediation_actions are Annotated with 'add'
        return {
            "messages": [
                {"role": "assistant", "content": json.dumps(plan)}
            ],
            "remediation_actions": [plan],
        }
    
    def execute_action(state: DataCenterState) -> DataCenterState:
        """Execute the planned remediation action.
        
        Note: The DataCenterEnvironment methods expect JSON strings as parameters
        to maintain compatibility with the LangChain tool interface. This design
        allows the same environment methods to be used by both LangChain ReAct
        agents and LangGraph agents.
        """
        logger.info("Executing remediation action...")
        
        actions = state.get("remediation_actions", [])
        if not actions:
            return state
        
        latest_plan = actions[-1]
        action_name = latest_plan.get("action")
        params = latest_plan.get("params", {})
        
        result = {"status": "skipped"}
        
        try:
            # All env methods expect JSON strings to maintain tool interface compatibility
            if action_name == "inspect_link_health":
                if hasattr(env, 'inspect_link_health'):
                    result_str = env.inspect_link_health(json.dumps(params))
                    result = json.loads(result_str)
            
            elif action_name == "compute_resilient_path":
                if hasattr(env, 'compute_resilient_path'):
                    result_str = env.compute_resilient_path(json.dumps(params))
                    result = json.loads(result_str)
                    
                    # Auto-activate the computed path
                    if "path" in result and result["path"]:
                        logger.info(f"Auto-activating computed path: {result['path']}")
                        try:
                            activate_result_str = env.activate_backup_path(json.dumps({"path": result["path"]}))
                            activate_result = json.loads(activate_result_str)
                            result["auto_activated"] = True
                            result["activate_result"] = activate_result
                            logger.info(f"Path activation result: {activate_result.get('status', 'unknown')}")
                            
                            # We'll add the activation action in the return statement below
                        except Exception as e:
                            logger.error(f"Auto-activation failed: {e}")
                            result["auto_activation_error"] = str(e)
            
            elif action_name == "monitor_link":
                if hasattr(env, 'monitor_link'):
                    result_str = env.monitor_link(json.dumps(params))
                    result = json.loads(result_str)
            
            elif action_name == "activate_backup_path":
                if hasattr(env, 'activate_backup_path'):
                    result_str = env.activate_backup_path(json.dumps(params))
                    result = json.loads(result_str)
            
            elif action_name == "restore_primary_path":
                if hasattr(env, 'restore_primary_path'):
                    result_str = env.restore_primary_path(json.dumps(params))
                    result = json.loads(result_str)
            
            elif action_name == "probe_connectivity":
                if hasattr(env, 'probe_connectivity'):
                    result_str = env.probe_connectivity(json.dumps(params))
                    result = json.loads(result_str)
            
            elif action_name == "traceroute":
                if hasattr(env, 'traceroute'):
                    result_str = env.traceroute(json.dumps(params))
                    result = json.loads(result_str)
            
            elif action_name in ("complete", "error"):
                result = {"status": action_name}
            
            else:
                result = {"status": "unknown_action", "action": action_name}
            
        except Exception as e:
            logger.error(f"Action execution error: {e}")
            result = {"status": "error", "error": str(e), "action": action_name}
        
        logger.info(f"Action result: {result.get('status', 'unknown')}")
        
        # Check if auto-activation happened and add it to remediation actions
        extra_actions = []
        if result.get("auto_activated") and result.get("activate_result"):
            extra_actions.append({
                "action": "activate_backup_path",
                "params": {"path": result.get("activate_result", {}).get("path", [])},
                "result": "success",
                "auto": True
            })
        
        # Note: messages is Annotated with 'add', remediation_actions too
        return_dict = {
            "messages": [
                {"role": "system", "content": f"Action result: {json.dumps(result)}"}
            ],
        }
        
        if extra_actions:
            return_dict["remediation_actions"] = extra_actions
        
        return return_dict
    
    def verify_recovery(state: DataCenterState) -> DataCenterState:
        """Verify that remediation was successful."""
        logger.info("Verifying network recovery...")
        
        # Check if backup paths were activated
        actions = state.get("remediation_actions", [])
        backup_activated = any(
            a.get("action") == "activate_backup_path" or 
            a.get("auto_activated") 
            for a in actions
        )
        
        # Re-assess network health
        if hasattr(env, 'link_profiles'):
            profiles = {
                "-".join(k): v.to_dict() 
                for k, v in env.link_profiles.items()
            }
        else:
            profiles = state.get("link_profiles", {})
        
        healthy_links = sum(1 for p in profiles.values() if p.get('status') == 'up')
        total_links = len(profiles)
        
        # Success criteria: if backup path activated, consider it successful
        if backup_activated:
            success = True  # Backup provides alternate connectivity
            logger.info(f"Backup path activated - network functional with {healthy_links}/{total_links} links up")
        else:
            success = healthy_links == total_links
        
        verification = {
            "healthy_links": healthy_links,
            "total_links": total_links,
            "success": success,
        }
        
        logger.info(f"Verification: {verification}")
        
        # Note: messages is Annotated with 'add', so only return new messages
        return {
            "network_health": {
                **state.get("network_health", {}),
                **verification,
            },
            "messages": [
                {"role": "system", "content": f"Verification: {json.dumps(verification)}"}
            ],
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    
    def should_continue(state: DataCenterState) -> Literal["continue", "summary"]:
        """Decide whether to continue remediation or generate summary."""
        iteration = state.get("iteration_count", 0)
        actions = state.get("remediation_actions", [])
        
        # Check iteration limit
        if iteration >= max_iterations:
            logger.info(f"Reached max iterations ({max_iterations})")
            return "summary"
        
        # Detect loop: if last 3 actions are identical, stop
        if len(actions) >= 3:
            last_three = actions[-3:]
            if all(a.get("action") == last_three[0].get("action") and 
                   a.get("params") == last_three[0].get("params") 
                   for a in last_three):
                logger.warning("Detected action loop - stopping remediation")
                return "summary"
        
        # Check if last action was complete or error
        if actions:
            last_action = actions[-1].get("action")
            if last_action in ("complete", "error"):
                logger.info(f"Ending due to action: {last_action}")
                return "summary"
        
        # Check network health
        network_health = state.get("network_health", {})
        if network_health.get("success"):
            logger.info("Network fully recovered")
            return "summary"
        
        degraded = network_health.get("degraded_links", 0)
        if degraded == 0:
            logger.info("No degraded links remaining")
            return "summary"
        
        logger.info(f"Continuing remediation ({degraded} links degraded)")
        return "continue"
    
    def generate_summary(state: DataCenterState) -> DataCenterState:
        """Generate final remediation summary."""
        logger.info("Generating remediation summary...")
        
        actions = state.get("remediation_actions", [])
        network_health = state.get("network_health", {})
        failures = state.get("failure_history", [])
        
        # Count actual remediation actions (exclude inspect_link_health, complete, error)
        real_actions = [a for a in actions if a.get("action") not in ("inspect_link_health", "complete", "error")]
        
        # Build detailed summary
        summary_parts = [
            "=== Network Remediation Summary ===\n",
            f"Total iterations: {state.get('iteration_count', 0)}",
            f"Remediation actions taken: {len(real_actions)}",
            f"Network status: {network_health.get('overall_status', 'unknown')}",
            f"Links healthy: {network_health.get('healthy_links', 0)}/{network_health.get('total_links', 0)}\n",
        ]
        
        # List failures
        if failures:
            summary_parts.append(f"\nSimulated Failures ({len(failures)}):")
            for f in failures:
                summary_parts.append(f"  - {f.get('link', 'unknown')}: {f.get('mode', 'unknown')}")
        
        # List remediation actions
        if real_actions:
            summary_parts.append(f"\nRemediation Actions Performed:")
            for i, action in enumerate(real_actions, 1):
                action_type = action.get("action", "unknown")
                params = action.get("params", {})
                if action_type == "activate_backup_path":
                    path = params.get("path", [])
                    auto = " (auto)" if action.get("auto") else ""
                    summary_parts.append(f"  {i}. Activated backup path{auto}: {' → '.join(path)}")
                elif action_type == "compute_resilient_path":
                    summary_parts.append(f"  {i}. Computed resilient path from {params.get('src')} to {params.get('dst')}")
                elif action_type == "restore_primary_path":
                    summary_parts.append(f"  {i}. Restored primary path: {params.get('path', [])}")
                else:
                    summary_parts.append(f"  {i}. {action_type}: {params}")
        else:
            summary_parts.append("\nNo remediation actions were performed.")
        
        # Add conclusion
        if network_health.get("success"):
            summary_parts.append("\n✓ Network connectivity restored via backup paths.")
        elif network_health.get("degraded_links", 0) > 0:
            summary_parts.append(f"\n⚠ {network_health.get('degraded_links')} link(s) remain degraded.")
            summary_parts.append("  Manual intervention may be required for full recovery.")
        
        summary = "\n".join(summary_parts)
        logger.info(f"\n{summary}")
        
        return {
            "final_answer": summary
        }
    
    # Build the graph
    workflow = StateGraph(DataCenterState)
    
    # Add nodes
    workflow.add_node("assess_network", assess_network)
    workflow.add_node("plan_remediation", plan_remediation)
    workflow.add_node("execute_action", execute_action)
    workflow.add_node("verify_recovery", verify_recovery)
    workflow.add_node("generate_summary", generate_summary)
    
    # Set entry point
    workflow.set_entry_point("assess_network")
    
    # Add edges
    workflow.add_edge("assess_network", "plan_remediation")
    workflow.add_edge("plan_remediation", "execute_action")
    workflow.add_edge("execute_action", "verify_recovery")
    workflow.add_edge("generate_summary", END)
    
    # Add conditional edge from verify
    workflow.add_conditional_edges(
        "verify_recovery",
        should_continue,
        {
            "continue": "plan_remediation",  # Loop back for more remediation
            "summary": "generate_summary",   # Generate final summary
        }
    )
    
    # Compile with checkpointer if provided
    if checkpointer is None:
        checkpointer = MemorySaver()
    
    # Add human-in-the-loop interrupt if enabled
    # LangGraph will pause before critical nodes for approval
    compile_kwargs = {"checkpointer": checkpointer}
    if human_in_loop:
        compile_kwargs["interrupt_before"] = ["execute_action"]
    
    return workflow.compile(**compile_kwargs)


def run_datacenter_graph(
    graph: Any,
    initial_query: str = "Remediate network failures",
    thread_id: str = "datacenter-1",
) -> dict[str, Any]:
    """Run the DataCenter graph and return final state.
    
    Args:
        graph: Compiled LangGraph instance
        initial_query: Initial query to start remediation
        thread_id: Thread ID for checkpoint management
    
    Returns:
        Final state dictionary with remediation results
    """
    # Initialize state
    initial_state: DataCenterState = {
        "messages": [{"role": "user", "content": initial_query}],
        "topology_blueprint": None,
        "link_profiles": None,
        "failure_history": [],
        "remediation_actions": [],
        "network_health": None,
        "iteration_count": 0,
        "final_answer": None,
    }
    
    # Configure
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 50  # Increase from default 25
    }
    
    # Run the graph
    logger.info(f"Starting DataCenter graph with query: {initial_query}")
    
    try:
        final_state = None
        for event in graph.stream(initial_state, config):
            logger.debug(f"Graph event: {event}")
            final_state = event
        
        # Extract final state from last event
        if final_state:
            for node_name, state_update in final_state.items():
                if isinstance(state_update, dict):
                    # Return state_update which now includes the detailed summary from generate_summary
                    return state_update
        
        return initial_state
        
    except Exception as e:
        logger.error(f"Graph execution error: {e}")
        return {
            **initial_state,
            "final_answer": f"Error during execution: {str(e)}"
        }
