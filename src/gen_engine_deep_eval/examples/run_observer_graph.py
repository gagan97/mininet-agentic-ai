"""Example script demonstrating Observer agent with LangGraph.

This script shows how to use the LangGraph-based Observer agent for
monitoring SDN telemetry and detecting anomalies.

Usage:
    python -m gen_engine_deep_eval.examples.run_observer_graph
"""

from __future__ import annotations

import os
import time
from os import getenv

from loguru import logger
from pydantic.v1 import BaseModel

from gen_engine_deep_eval.wrapper import GenerativeEngineLLM
from gen_engine_deep_eval.observer_agent import (
    DigitalTwinState,
    generate_sample,
)
from gen_engine_deep_eval.graphs.observer_graph import (
    build_observer_graph,
    run_observer_graph,
)


def load_llm() -> GenerativeEngineLLM:
    """Load GenerativeEngineLLM for Observer agent."""
    
    class Config(BaseModel):
        model: str
        api_base: str | None = getenv("REST_API_BASE")
        api_key: str | None = getenv("API_KEY")
        max_tokens: int
        temperature: float

    config = Config(
        model="anthropic.claude-3-5-sonnet-20240620-v1:0",
        max_tokens=2048,
        temperature=0.05
    )

    return GenerativeEngineLLM(
        model=config.model,
        api_base=config.api_base,
        api_key=config.api_key,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
    )


def seed_telemetry_data(state: DigitalTwinState, n: int = 30):
    """Seed the telemetry state with synthetic data."""
    t0 = time.time()
    for i in range(n):
        state.add(generate_sample(t0 + i, anomaly_probability=0.15))
    logger.info(f"Seeded {n} telemetry samples")


def main():
    """Run Observer agent demo with LangGraph."""
    logger.info("=== Observer Agent with LangGraph Demo ===")
    
    # Initialize telemetry state
    telemetry_state = DigitalTwinState(window_size=60)
    seed_telemetry_data(telemetry_state)
    
    # Load LLM
    logger.info("Loading GenerativeEngineLLM...")
    llm = load_llm()
    
    # Build LangGraph
    logger.info("Building Observer LangGraph...")
    graph = build_observer_graph(
        llm=llm,
        state_provider=telemetry_state,
        max_iterations=5,
    )
    
    # Visualize graph structure (if graphviz available)
    try:
        if hasattr(graph, 'get_graph'):
            graph_def = graph.get_graph()
            if hasattr(graph_def, 'draw_mermaid'):
                mermaid = graph_def.draw_mermaid()
                logger.info(f"Graph structure:\n{mermaid}")
    except Exception as e:
        logger.debug(f"Could not visualize graph: {e}")
    
    # Run analysis
    logger.info("Running network health assessment...")
    result = run_observer_graph(
        graph=graph,
        initial_query="Assess current network health and detect anomalies",
        thread_id="demo-run-1",
    )
    
    # Display results
    logger.info("\n=== Analysis Results ===")
    logger.info(f"Iterations: {result.get('iteration_count', 'N/A')}")
    logger.info(f"Anomalies detected: {result.get('detected_anomalies', {}).get('anomalies', {})}")
    logger.info(f"\nFinal Assessment:\n{result.get('final_answer', 'No answer')}")
    
    # Show analysis history
    history = result.get("analysis_history", [])
    if history:
        logger.info(f"\n=== Analysis History ({len(history)} entries) ===")
        for idx, entry in enumerate(history, 1):
            logger.info(f"\nIteration {idx}:")
            logger.info(f"  Anomalies: {list(entry.get('anomalies', {}).get('anomalies', {}).keys())}")
            logger.info(f"  Assessment: {entry.get('assessment', 'N/A')[:100]}...")
    
    logger.info("\n=== Demo Complete ===")


if __name__ == "__main__":
    main()
