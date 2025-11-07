"""State schemas for LangGraph-based agents.

This module defines TypedDict state models for Observer and DataCenter agents,
providing type-safe state management throughout the execution graph.
"""

from __future__ import annotations

from typing import TypedDict, Annotated, Sequence, Any
from operator import add
from dataclasses import asdict


class ObserverState(TypedDict):
    """State for Observer agent analyzing SDN telemetry.
    
    Attributes:
        messages: Conversation history with the LLM
        current_snapshot: Latest telemetry sample
        detected_anomalies: Dict of anomalies with z-scores and rules
        analysis_history: List of past analysis results
        iteration_count: Number of iterations for loop control
        final_answer: Final summary from the agent
    """
    messages: Annotated[Sequence[dict], add]
    current_snapshot: dict[str, Any] | None
    detected_anomalies: dict[str, Any] | None
    analysis_history: Annotated[list[dict], add]
    iteration_count: int
    final_answer: str | None


class DataCenterState(TypedDict):
    """State for DataCenter agent managing Mininet topology.
    
    Attributes:
        messages: Conversation history with the LLM
        topology_blueprint: Current network topology design
        link_profiles: Current state of all network links
        failure_history: List of simulated failures
        remediation_actions: List of actions taken
        network_health: Overall network health assessment
        iteration_count: Number of iterations for loop control
        final_answer: Final summary from the agent
    """
    messages: Annotated[Sequence[dict], add]
    topology_blueprint: dict[str, Any] | None
    link_profiles: dict[str, Any] | None
    failure_history: Annotated[list[dict], add]
    remediation_actions: Annotated[list[dict], add]
    network_health: dict[str, Any] | None
    iteration_count: int
    final_answer: str | None
