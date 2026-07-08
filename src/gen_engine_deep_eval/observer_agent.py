"""Observer Agent PoC (Phase 1)

Goal:
  Monitor (simulated) SDN Digital Twin telemetry (latency, packet_loss, cpu, memory)
  Detect anomalies (e.g. latency spikes, cpu threshold breaches)
  Summarize findings & suggested next investigative steps.

Notes:
  - Uses existing GenerativeEngineLLM wrapper for LangChain.
  - Keeps everything in‑memory with synthetic data (replace data collection layer
    with real interfaces to SDN controllers / telemetry buses later).
  - Implements an Agent with tools (agentic pattern) so the LLM can choose when
    to call structured functions vs freeform reasoning.

Env variables expected (add to .env):
  GEN_ENGINE_MODEL      e.g. "openai-gpt4o-mini" (whatever appears in portal)
  GEN_ENGINE_API_BASE   e.g. "https://generative.engine.capgemini.com/api"
  GEN_ENGINE_API_KEY    API key

Run:
  uv run --env-file .env python -m gen_engine_deep_eval.observer_agent
"""
from __future__ import annotations

import os
from os import getenv
import random
import time
from dataclasses import dataclass, field
import json
from typing import List, Dict, Any

from loguru import logger

from pydantic.v1 import BaseModel

# LangChain (0.3.x) compatibility imports
from langchain_classic.agents import Tool, AgentType, initialize_agent
from langchain_core.callbacks import CallbackManagerForLLMRun

from .wrapper import GenerativeEngineLLM

# --------------------------- Data Simulation Layer --------------------------- #

@dataclass
class TelemetrySample:
    timestamp: float
    latency_ms: float
    packet_loss_pct: float
    cpu_pct: float
    mem_pct: float


def generate_sample(t: float, anomaly_probability: float = 0.1) -> TelemetrySample:
    """Generate a synthetic sample; occasionally inject anomalies."""
    # Baselines
    latency = random.gauss(25, 3)
    packet_loss = max(0.0, random.gauss(0.2, 0.05))
    cpu = random.gauss(45, 5)
    mem = random.gauss(55, 4)

    if random.random() < anomaly_probability:
        choice = random.choice(["latency", "cpu", "packet_loss", "mem"])
        if choice == "latency":
            latency *= random.uniform(2.5, 4.0)  # spike
        elif choice == "cpu":
            cpu = random.uniform(85, 97)
        elif choice == "packet_loss":
            packet_loss = random.uniform(2.0, 6.0)
        else:
            mem = random.uniform(85, 95)

    return TelemetrySample(t, latency, packet_loss, cpu, mem)


@dataclass
class DigitalTwinState:
    window_size: int = 60  # sliding window length
    samples: List[TelemetrySample] = field(default_factory=list)

    def add(self, sample: TelemetrySample):
        self.samples.append(sample)
        if len(self.samples) > self.window_size:
            self.samples.pop(0)

    def latest(self) -> TelemetrySample | None:
        return self.samples[-1] if self.samples else None

    def as_dict_series(self) -> Dict[str, List[float]]:
        return {
            "latency_ms": [s.latency_ms for s in self.samples],
            "packet_loss_pct": [s.packet_loss_pct for s in self.samples],
            "cpu_pct": [s.cpu_pct for s in self.samples],
            "mem_pct": [s.mem_pct for s in self.samples],
        }


STATE = DigitalTwinState()

# --------------------------- Anomaly Detection Tool ------------------------- #

def _z_scores(values: List[float]) -> List[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / max(1, len(values) - 1)
    std = var ** 0.5 or 1e-9
    return [(v - mean) / std for v in values]


def detect_anomalies_impl(threshold: float = 3.0) -> Dict[str, Any]:
    series = STATE.as_dict_series()
    anomalies: Dict[str, Any] = {}
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
    return {"anomalies": anomalies, "latest": STATE.latest().__dict__ if STATE.latest() else None}


# Wrap as LangChain Tool
detect_anomalies_tool = Tool(
    name="detect_anomalies",
    description="Analyze the latest telemetry window and return any anomalies with statistical z-scores and rule breaches. Returns JSON.",
    func=lambda _: json.dumps(detect_anomalies_impl()),  # input ignored
)


def latest_snapshot_impl() -> Dict[str, Any]:
    latest = STATE.latest()
    return latest.__dict__ if latest else {}


snapshot_tool = Tool(
    name="latest_snapshot",
    description="Get the most recent telemetry sample (latency_ms, packet_loss_pct, cpu_pct, mem_pct). Returns JSON.",
    func=lambda _: json.dumps(latest_snapshot_impl()),
)

# --------------------------- LLM / Agent Setup ----------------------------- #

def load_llm() -> GenerativeEngineLLM:
    class Config(BaseModel):
        model: str
        api_base: str | None = getenv("REST_API_BASE")
        api_key: str | None = getenv("API_KEY")
        max_tokens: int
        temperature: float


    config = Config(
        model="anthropic.claude-3-5-sonnet-20240620-v1:0", max_tokens=2048, temperature=0.05
    )


    return GenerativeEngineLLM(
            model=config.model,
            api_base=config.api_base,
            api_key=config.api_key,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )

    # model = os.getenv("GEN_ENGINE_MODEL", "openai-gpt4o-mini")
    # api_base = os.getenv("GEN_ENGINE_API_BASE")
    # api_key = os.getenv("GEN_ENGINE_API_KEY")
    # if not api_base or not api_key:
    #     raise RuntimeError("Missing GEN_ENGINE_API_BASE or GEN_ENGINE_API_KEY in env")
    # return GenerativeEngineLLM(
    #     model=model,
    #     api_base=api_base,
    #     api_key=api_key,
    #     max_tokens=512,
    #     temperature=0.2,
    # )


AGENT_SYSTEM_PROMPT = (
    "ROLE: Observer Agent for an SDN digital twin.\n"
    "STRICT FORMAT POLICY:\n"
    "Repeat the following loop UNTIL you have gathered enough information:\n"
    "Thought: <concise reasoning>\n"
    "Action: <one of latest_snapshot|detect_anomalies>\n"
    "Action Input: <empty string>\n"
    "Do NOT output Observation yourself. Wait for the tool result.\n"
    "Never invent tool output.\n"
    "Only when no further tool calls are needed output exactly one final line:\n"
    "Final Answer: <summary with anomalies (if any) and next actions>.\n"
    "Never include both an Action and Final Answer in the same turn.\n"
)


def build_agent(llm: GenerativeEngineLLM):
    # Legacy ZERO_SHOT_REACT_DESCRIPTION agent allows tool calling with simple LLMs.
    tools = [snapshot_tool, detect_anomalies_tool]
    agent = initialize_agent(
        tools=tools,
        llm=llm,
        agent=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
        verbose=True,
        handle_parsing_errors=True,
        agent_kwargs={"system_message": AGENT_SYSTEM_PROMPT},
    )
    return agent


# --------------------------- Run Loop / Demo -------------------------------- #

def seed_data(n: int = 30):
    t0 = time.time()
    for i in range(n):
        STATE.add(generate_sample(t0 + i))


def run_observer(iterations: int = 5, delay_sec: float = 2.0):
    llm = load_llm()
    agent = build_agent(llm)

    logger.info("Starting Observer Agent demo...")
    for i in range(iterations):
        # Ingest new telemetry
        STATE.add(generate_sample(time.time()))
        # Ask agent to evaluate
        query = (
            "Assess current network health. Follow the STRICT FORMAT POLICY. Begin by calling latest_snapshot."
        )
        try:
            # Provide stop tokens to cut off early Final Answer attempts mid generation
            result = agent.invoke({"input": query, "stop": ["Final Answer:"]})
            logger.info(f"Cycle {i+1}: {result['output']}")
        except Exception as e:
            logger.error(f"Agent error: {e}")
        time.sleep(delay_sec)


def main():  # pragma: no cover
    seed_data()
    run_observer()


if __name__ == "__main__":  # pragma: no cover
    main()
