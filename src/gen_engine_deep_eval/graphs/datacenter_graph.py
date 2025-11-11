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
        
        return {
            **state,
            "topology_blueprint": topology,
            "link_profiles": profiles,
            "network_health": health_assessment,
            "messages": state.get("messages", []) + [
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
        
        # Find degraded links
        degraded_links = [
            name for name, profile in link_profiles.items()
            if profile.get('status') == 'down'
        ]
        
        system_prompt = (
            "You are a network remediation agent. Analyze the network state and suggest remediation actions. "
            "Available actions: activate_backup_path, restore_primary_path, monitor_link, "
            "probe_connectivity, traceroute. "
            "Respond with JSON containing: {\"action\": \"action_name\", \"params\": {...}}. "
            "If network is healthy, respond with: {\"action\": \"complete\", \"summary\": \"...\"}"
        )
        
        context = (
            f"Network Status: {network_health.get('overall_status')}\n"
            f"Total Links: {network_health.get('total_links')}\n"
            f"Healthy Links: {network_health.get('healthy_links')}\n"
            f"Degraded Links: {degraded_links}\n"
            f"Recent Failures: {len(failure_history)}\n\n"
            "Suggest the next remediation action."
        )
        
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
            
        except Exception as e:
            logger.error(f"Planning error: {e}")
            plan = {"action": "error", "error": str(e)}
        
        return {
            **state,
            "messages": state.get("messages", []) + [
                {"role": "assistant", "content": json.dumps(plan)}
            ],
            "remediation_actions": state.get("remediation_actions", []) + [plan],
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
        
        # All env methods expect JSON strings to maintain tool interface compatibility
        if action_name == "monitor_link":
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
        
        logger.info(f"Action result: {result}")
        
        return {
            **state,
            "messages": state.get("messages", []) + [
                {"role": "system", "content": f"Action result: {json.dumps(result)}"}
            ],
        }
    
    def verify_recovery(state: DataCenterState) -> DataCenterState:
        """Verify that remediation was successful."""
        logger.info("Verifying network recovery...")
        
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
        
        verification = {
            "healthy_links": healthy_links,
            "total_links": total_links,
            "success": healthy_links == total_links,
        }
        
        logger.info(f"Verification: {verification}")
        
        return {
            **state,
            "network_health": {
                **state.get("network_health", {}),
                **verification,
            },
            "messages": state.get("messages", []) + [
                {"role": "system", "content": f"Verification: {json.dumps(verification)}"}
            ],
            "iteration_count": state.get("iteration_count", 0) + 1,
        }
    
    def should_continue(state: DataCenterState) -> Literal["continue", "end"]:
        """Decide whether to continue remediation or stop."""
        iteration = state.get("iteration_count", 0)
        
        # Check iteration limit
        if iteration >= max_iterations:
            logger.info(f"Reached max iterations ({max_iterations})")
            return "end"
        
        # Check if last action was complete or error
        actions = state.get("remediation_actions", [])
        if actions:
            last_action = actions[-1].get("action")
            if last_action in ("complete", "error"):
                logger.info(f"Ending due to action: {last_action}")
                return "end"
        
        # Check network health
        network_health = state.get("network_health", {})
        if network_health.get("success"):
            logger.info("Network fully recovered")
            return "end"
        
        degraded = network_health.get("degraded_links", 0)
        if degraded == 0:
            logger.info("No degraded links remaining")
            return "end"
        
        logger.info(f"Continuing remediation ({degraded} links degraded)")
        return "continue"
    
    # Build the graph
    workflow = StateGraph(DataCenterState)
    
    # Add nodes
    workflow.add_node("assess_network", assess_network)
    workflow.add_node("plan_remediation", plan_remediation)
    workflow.add_node("execute_action", execute_action)
    workflow.add_node("verify_recovery", verify_recovery)
    
    # Set entry point
    workflow.set_entry_point("assess_network")
    
    # Add edges
    workflow.add_edge("assess_network", "plan_remediation")
    workflow.add_edge("plan_remediation", "execute_action")
    workflow.add_edge("execute_action", "verify_recovery")
    
    # Add conditional edge from verify
    workflow.add_conditional_edges(
        "verify_recovery",
        should_continue,
        {
            "continue": "plan_remediation",  # Loop back for more remediation
            "end": END,
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
    config = {"configurable": {"thread_id": thread_id}}
    
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
                    # Build final answer from remediation history
                    actions = state_update.get("remediation_actions", [])
                    health = state_update.get("network_health", {})
                    
                    summary = (
                        f"Remediation completed. "
                        f"Actions taken: {len(actions)}. "
                        f"Network status: {health.get('overall_status', 'unknown')}. "
                        f"Links healthy: {health.get('healthy_links', 0)}/{health.get('total_links', 0)}"
                    )
                    
                    return {
                        **state_update,
                        "final_answer": summary,
                    }
        
        return initial_state
        
    except Exception as e:
        logger.error(f"Graph execution error: {e}")
        return {
            **initial_state,
            "final_answer": f"Error during execution: {str(e)}"
        }
