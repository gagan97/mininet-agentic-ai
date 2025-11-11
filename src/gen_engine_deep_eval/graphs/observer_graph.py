"""LangGraph implementation of the Observer agent.

This module provides a state machine-based architecture for monitoring SDN
telemetry, detecting anomalies, and reasoning about network health using
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

from .state_schemas import ObserverState
from ..observer_agent import DigitalTwinState, detect_anomalies_impl, latest_snapshot_impl


def build_observer_graph(
    llm: BaseLanguageModel,
    state_provider: DigitalTwinState,
    max_iterations: int = 10,
    checkpointer: Any | None = None,
) -> StateGraph:
    """Build the Observer agent LangGraph state machine.
    
    Args:
        llm: Language model instance (GenerativeEngineLLM)
        state_provider: Telemetry state provider
        max_iterations: Maximum analysis iterations
        checkpointer: Optional checkpoint saver for state persistence
    
    Returns:
        Compiled LangGraph state machine
    """
    # Define the graph nodes
    def analyze_telemetry(state: ObserverState) -> ObserverState:
        """Entry node: Fetch latest telemetry snapshot."""
        logger.info("Analyzing telemetry snapshot...")
        
        # Use the state_provider passed to build_observer_graph
        latest = state_provider.latest()
        snapshot = latest.__dict__ if latest else {}
        
        # Add to state
        # Note: messages is Annotated with 'add', so only return new messages
        return {
            "current_snapshot": snapshot,
            "messages": [
                {"role": "system", "content": f"Latest snapshot: {json.dumps(snapshot)}"}
            ],
        }
    
    def detect_issues(state: ObserverState) -> ObserverState:
        """Run anomaly detection on current snapshot."""
        logger.info("Detecting anomalies...")
        
        # Use the state_provider for anomaly detection
        from ..observer_agent import _z_scores
        
        series = state_provider.as_dict_series()
        anomalies: dict[str, Any] = {}
        threshold = 3.0
        
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
            # Domain thresholds (custom rule layer)
            if metric == "cpu_pct" and values[-1] > 80:
                anomalies.setdefault(metric, {"current": values[-1]}).update(
                    {"rule": ">80% cpu"}
                )
            if metric == "latency_ms" and values[-1] > 80:
                anomalies.setdefault(metric, {"current": values[-1]}).update(
                    {"rule": ">80ms latency"}
                )
        
        latest = state_provider.latest()
        anomaly_result = {
            "anomalies": anomalies,
            "latest": latest.__dict__ if latest else None
        }
        
        # Note: messages is Annotated with 'add', so only return new messages
        return {
            "detected_anomalies": anomaly_result,
            "messages": [
                {"role": "system", "content": f"Anomaly detection: {json.dumps(anomaly_result)}"}
            ],
        }
    
    def reason(state: ObserverState) -> ObserverState:
        """LLM reasoning node using GenerativeEngineLLM."""
        logger.info("LLM reasoning about network health...")
        
        # Build prompt with current state
        messages = state.get("messages", [])
        
        # Create system prompt
        system_prompt = (
            "You are an SDN network observer agent. Analyze the telemetry data and anomalies provided. "
            "Summarize the current network health status and recommend next actions if anomalies are found. "
            "Be concise and specific."
        )
        
        # Prepare messages for LLM
        llm_messages = [SystemMessage(content=system_prompt)]
        
        # Add conversation history
        for msg in messages[-5:]:  # Keep last 5 messages for context
            if msg.get("role") == "system":
                llm_messages.append(SystemMessage(content=msg["content"]))
            elif msg.get("role") == "assistant":
                llm_messages.append(AIMessage(content=msg["content"]))
            elif msg.get("role") == "user":
                llm_messages.append(HumanMessage(content=msg["content"]))
        
        # Add analysis request
        current_snapshot = state.get("current_snapshot", {})
        detected_anomalies = state.get("detected_anomalies", {})
        
        analysis_request = (
            f"Current telemetry: {json.dumps(current_snapshot)}\n"
            f"Detected anomalies: {json.dumps(detected_anomalies)}\n\n"
            "Provide a brief assessment of network health and recommend actions."
        )
        llm_messages.append(HumanMessage(content=analysis_request))
        
        # Call LLM
        try:
            # LangGraph expects invoke to work with messages
            if hasattr(llm, 'invoke'):
                response = llm.invoke(llm_messages)
                # Handle different response types
                if hasattr(response, 'content'):
                    response_text = response.content
                else:
                    response_text = str(response)
            else:
                # Fallback for older LangChain versions
                prompt_text = "\n".join([m.content if hasattr(m, 'content') else str(m) for m in llm_messages])
                response_text = llm(prompt_text)
            
            logger.info(f"LLM response: {response_text[:200]}...")
            
        except Exception as e:
            logger.error(f"LLM error: {e}")
            response_text = f"Error during analysis: {str(e)}"
        
        # Add to analysis history
        analysis_entry = {
            "iteration": state.get("iteration_count", 0),
            "snapshot": current_snapshot,
            "anomalies": detected_anomalies,
            "assessment": response_text,
        }
        
        # Note: messages and analysis_history are Annotated with 'add', so only return new items
        return {
            "messages": [
                {"role": "assistant", "content": response_text}
            ],
            "analysis_history": [analysis_entry],
            "iteration_count": state.get("iteration_count", 0) + 1,
            "final_answer": response_text,  # Store as potential final answer
        }
    
    def should_continue(state: ObserverState) -> Literal["continue", "end"]:
        """Conditional edge: decide whether to continue or stop."""
        iteration = state.get("iteration_count", 0)
        
        # Check iteration limit
        if iteration >= max_iterations:
            logger.info(f"Reached max iterations ({max_iterations})")
            return "end"
        
        # Check if anomalies are critical (simplified logic)
        anomalies = state.get("detected_anomalies", {}).get("anomalies", {})
        
        # If no anomalies, we can stop
        if not anomalies:
            logger.info("No anomalies detected, ending analysis")
            return "end"
        
        # Check severity (simplified - look for high z-scores or rule breaches)
        has_critical = False
        for metric, details in anomalies.items():
            z_score = details.get("z_score", 0)
            if abs(z_score) > 5 or "rule" in details:
                has_critical = True
                break
        
        if has_critical:
            logger.info("Critical anomalies detected, continuing analysis")
            return "continue"
        
        logger.info("No critical issues, ending analysis")
        return "end"
    
    # Build the graph
    workflow = StateGraph(ObserverState)
    
    # Add nodes
    workflow.add_node("analyze_telemetry", analyze_telemetry)
    workflow.add_node("detect_issues", detect_issues)
    workflow.add_node("reason", reason)
    
    # Set entry point
    workflow.set_entry_point("analyze_telemetry")
    
    # Add edges
    workflow.add_edge("analyze_telemetry", "detect_issues")
    workflow.add_edge("detect_issues", "reason")
    
    # Add conditional edge from reason
    workflow.add_conditional_edges(
        "reason",
        should_continue,
        {
            "continue": "analyze_telemetry",  # Loop back for more analysis
            "end": END,
        }
    )
    
    # Compile with checkpointer if provided
    if checkpointer is None:
        checkpointer = MemorySaver()
    
    return workflow.compile(checkpointer=checkpointer)


def run_observer_graph(
    graph: Any,
    initial_query: str = "Assess current network health",
    thread_id: str = "observer-1",
) -> dict[str, Any]:
    """Run the Observer graph and return final state.
    
    Args:
        graph: Compiled LangGraph instance
        initial_query: Initial query to start analysis
        thread_id: Thread ID for checkpoint management
    
    Returns:
        Final state dictionary with analysis results
    """
    # Initialize state
    initial_state: ObserverState = {
        "messages": [{"role": "user", "content": initial_query}],
        "current_snapshot": None,
        "detected_anomalies": None,
        "analysis_history": [],
        "iteration_count": 0,
        "final_answer": None,
    }
    
    # Configure for streaming or batch
    config = {"configurable": {"thread_id": thread_id}}
    
    # Run the graph
    logger.info(f"Starting Observer graph with query: {initial_query}")
    
    try:
        # Stream events for visibility
        final_state = None
        for event in graph.stream(initial_state, config):
            logger.debug(f"Graph event: {event}")
            final_state = event
        
        # Return the last state
        if final_state:
            # Extract the actual state from the event
            # Events come as {node_name: state_update}
            for node_name, state_update in final_state.items():
                if isinstance(state_update, dict):
                    return state_update
        
        return initial_state
        
    except Exception as e:
        logger.error(f"Graph execution error: {e}")
        return {
            **initial_state,
            "final_answer": f"Error during execution: {str(e)}"
        }
