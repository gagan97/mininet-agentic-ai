"""Integration example showing both Observer and DataCenter agents with LangGraph.

This example demonstrates:
1. Observer agent monitoring network telemetry
2. DataCenter agent responding to detected issues
3. State sharing between agents
4. Checkpoint/resume capabilities

Note: This is a conceptual example. In production, you would:
- Run Observer agent continuously
- Trigger DataCenter agent based on Observer findings
- Use persistent checkpointing (database, file system)
- Implement proper error handling and logging
"""

from __future__ import annotations

import time
from os import getenv

from loguru import logger
from pydantic.v1 import BaseModel

# Import wrapper
from gen_engine_deep_eval.wrapper import GenerativeEngineLLM

# Import Observer components
from gen_engine_deep_eval.observer_agent import (
    DigitalTwinState,
    generate_sample,
    TelemetrySample,
)

# Import LangGraph components (requires langgraph dependencies)
try:
    from gen_engine_deep_eval.graphs.observer_graph import (
        build_observer_graph,
        run_observer_graph,
    )
    from gen_engine_deep_eval.graphs.datacenter_graph import (
        build_datacenter_graph,
        run_datacenter_graph,
    )
    LANGGRAPH_AVAILABLE = True
except ImportError:
    logger.warning("LangGraph not available. Install with: pip install -r requirements-langgraph.txt")
    LANGGRAPH_AVAILABLE = False


def load_llm() -> GenerativeEngineLLM:
    """Load GenerativeEngineLLM."""
    
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


def seed_normal_telemetry(state: DigitalTwinState, n: int = 20):
    """Seed normal telemetry data."""
    t0 = time.time()
    for i in range(n):
        state.add(generate_sample(t0 + i, anomaly_probability=0.0))
    logger.info(f"Seeded {n} normal telemetry samples")


def inject_critical_anomaly(state: DigitalTwinState):
    """Inject a critical anomaly that should trigger remediation."""
    t = time.time()
    critical = TelemetrySample(
        timestamp=t,
        latency_ms=200.0,  # Very high latency
        packet_loss_pct=5.0,  # High packet loss
        cpu_pct=95.0,  # Critical CPU
        mem_pct=90.0,  # High memory
    )
    state.add(critical)
    logger.warning("Injected critical anomaly")


def run_integrated_demo():
    """Run integrated demo of Observer → DataCenter workflow."""
    
    if not LANGGRAPH_AVAILABLE:
        logger.error("This demo requires LangGraph. Install dependencies first.")
        return
    
    logger.info("=== Integrated Agent Demo ===")
    logger.info("Scenario: Observer detects critical anomaly → triggers DataCenter remediation")
    
    # Phase 1: Observer Agent Monitoring
    logger.info("\n--- Phase 1: Network Monitoring ---")
    
    # Setup telemetry
    telemetry_state = DigitalTwinState(window_size=60)
    seed_normal_telemetry(telemetry_state, n=15)
    
    # Load LLM (shared across agents)
    llm = load_llm()
    
    # Build Observer graph
    observer_graph = build_observer_graph(
        llm=llm,
        state_provider=telemetry_state,
        max_iterations=3,
    )
    
    # Initial monitoring (should show healthy state)
    logger.info("Initial health check...")
    result1 = run_observer_graph(
        graph=observer_graph,
        initial_query="Perform initial network health assessment",
        thread_id="monitoring-session-1",
    )
    
    logger.info(f"Initial Assessment: {result1.get('final_answer', 'N/A')[:200]}")
    
    # Phase 2: Anomaly Detection
    logger.info("\n--- Phase 2: Anomaly Injection ---")
    
    # Inject critical issue
    inject_critical_anomaly(telemetry_state)
    
    # Observer detects the anomaly
    logger.info("Running anomaly detection...")
    result2 = run_observer_graph(
        graph=observer_graph,
        initial_query="Urgent: Check for critical anomalies",
        thread_id="monitoring-session-1",  # Same session - resumes from checkpoint
    )
    
    detected_anomalies = result2.get('detected_anomalies', {}).get('anomalies', {})
    logger.warning(f"Detected Anomalies: {list(detected_anomalies.keys())}")
    logger.info(f"Assessment: {result2.get('final_answer', 'N/A')[:200]}")
    
    # Phase 3: Automated Remediation (Conceptual - requires Mininet)
    logger.info("\n--- Phase 3: Remediation Planning ---")
    
    # In a real scenario with Mininet:
    # 1. Observer detects high latency/packet loss
    # 2. DataCenter agent diagnoses network issues
    # 3. Agent activates backup paths
    # 4. Agent verifies recovery
    
    logger.info("DataCenter remediation would execute here (requires Mininet):")
    logger.info("  1. Assess network topology")
    logger.info("  2. Identify failed links causing latency")
    logger.info("  3. Compute alternate paths")
    logger.info("  4. Activate backup routes")
    logger.info("  5. Verify connectivity restored")
    
    # Simulate what the DataCenter agent would do
    if False:  # Set to True if Mininet is available
        from gen_engine_deep_eval.datacenter_agent import DataCenterEnvironment
        
        logger.info("\nExecuting DataCenter agent remediation...")
        with DataCenterEnvironment() as env:
            env.__enter__()
            
            datacenter_graph = build_datacenter_graph(
                llm=llm,
                env=env,
                max_iterations=5,
                human_in_loop=False,  # Automated response
            )
            
            remediation_result = run_datacenter_graph(
                graph=datacenter_graph,
                initial_query=f"Remediate network issues: {detected_anomalies}",
                thread_id="remediation-session-1",
            )
            
            logger.info(f"Remediation Result: {remediation_result.get('final_answer')}")
    
    # Phase 4: Verification
    logger.info("\n--- Phase 4: Post-Remediation Verification ---")
    
    # In production:
    # 1. Wait for network to stabilize
    # 2. Observer re-checks telemetry
    # 3. Confirms anomalies cleared
    # 4. Returns to normal monitoring
    
    logger.info("Verification steps (conceptual):")
    logger.info("  1. Wait 30s for network stabilization")
    logger.info("  2. Re-run Observer health check")
    logger.info("  3. Confirm metrics within normal range")
    logger.info("  4. Resume continuous monitoring")
    
    # Summary
    logger.info("\n=== Demo Complete ===")
    logger.info("Summary:")
    logger.info(f"  - Initial state: Healthy")
    logger.info(f"  - Anomalies detected: {len(detected_anomalies)}")
    logger.info(f"  - Remediation: Would activate backup paths (requires Mininet)")
    logger.info(f"  - Final state: Awaiting verification")
    
    logger.info("\nNext steps:")
    logger.info("  1. Install Mininet to run full remediation")
    logger.info("  2. Set up persistent checkpointing (database)")
    logger.info("  3. Implement alerting/notification system")
    logger.info("  4. Deploy as continuous monitoring service")


def main():
    """Run the integrated demo."""
    try:
        run_integrated_demo()
    except Exception as e:
        logger.exception(f"Demo failed: {e}")
        raise


if __name__ == "__main__":
    main()
