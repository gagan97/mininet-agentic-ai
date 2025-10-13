# Generative Engine Deep Eval & Agentic Mininet Lab

This repository demonstrates two complementary workflows built on Capgemini's Generative Engine:

- **DeepEval integration** – run Generative Engine as an LLM-as-judge through a LangChain-compatible wrapper.
- **Agentic network remediation** – orchestrate a ReAct agent that inspects, diagnoses, and repairs a Mininet-based data-center topology using structured tools.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Generative Engine credentials with API access
- (For the Mininet demo) A Linux host with [Mininet](https://github.com/mininet/mininet) installed and `sudo` access

## Quick start

1. Install dependencies:

   ```bash
   uv sync
   ```

   If you prefer requirements files, replicate the same environment with:

   ```bash
   uv pip install -r requirements.txt
   ```

2. Copy the sample environment file and add your credentials:

   ```bash
   cp .env.local .env
   ```

   Populate the following keys:

   - `REST_API_BASE` – e.g. `https://api.generative.engine.capgemini.com/`
   - `API_KEY` – personal Generative Engine API key (never commit this file)
   - `GEN_ENGINE_MODEL` – optional override for the default model selection

   The observer agent also honours `GEN_ENGINE_API_BASE` / `GEN_ENGINE_API_KEY` for backwards compatibility.

   run command source .env to load the variables into your shell.

3. Activate the environment before running any commands:

   ```bash
   source .venv/bin/activate
   ```

## Repository tour

- `src/gen_engine_deep_eval/wrapper.py` – LangChain-ready `GenerativeEngineLLM` wrapper with stop token handling and session tracking.
- `src/gen_engine_deep_eval/helpers.py` / `models.py` – provider selection and response dataclasses.
- `src/gen_engine_deep_eval/llm.py` – convenience pipeline composing the wrapper with LangChain parsers for DeepEval harnesses.
- `src/gen_engine_deep_eval/observer_agent.py` – synthetic telemetry monitor using ReAct + anomaly detection tools.
- `src/gen_engine_deep_eval/datacenter_agent.py` – Mininet automation, telemetry sampling, NetworkX topology graphing, and the expanded toolbelt (`inspect_link_health`, `compute_resilient_path`, `monitor_link`, `simulate_failure`, etc.).
- `tests/test_mininet_agent.py` – unit coverage for prompt wiring, credential validation, topology graph filters, and JSON tool contracts.

## Running tests

Execute the fast unit suite (includes graph/pathing checks for the new tools):

```bash
uv run pytest
```

DeepEval jobs can be wired into CI once the `gen_engine_deep_eval.scripts:test` entry point is published. Until then, use the LangChain chain in `llm.py` directly or wrap it inside your own DeepEval scenario.

## Observer agent demo

The observer agent seeds a synthetic telemetry window and asks the LLM to decide when to call structured tools (`latest_snapshot`, `detect_anomalies`) before summarising findings.

```bash
uv run --env-file .env python -m gen_engine_deep_eval.observer_agent
```

Highlights:

- Z-score anomaly detection combined with domain thresholds (latency, CPU, packet loss).
- Strict ReAct prompt enforcing alternating `Thought`/`Action` steps and a single `Final Answer`.
- Stop-token aware wrapper prevents the model from streaming partial final answers.

## Mininet data-center remediation demo

The data-center agent extends the environment with richer telemetry and path-planning capabilities:

- Live link profiles track bandwidth, latency, utilisation, and loss via `_sample_link_metrics`.
- A cached NetworkX graph (`_get_topology_graph`) drives shortest-path calculations and supports avoiding failed edges.
- New LangChain tools expose these insights to the LLM:
  - `inspect_link_health` – return current metrics and status for any link.
   - `compute_resilient_path` – compute latency- or capacity-aware alternate paths between nodes (supports `avoid` entries as `[src, dst]` pairs or strings like `"src-dst"`).
   - `monitor_link` now returns structured errors with suggested neighbour links if you reference a non-existent edge.
  - Existing tooling (`monitor_link`, `simulate_failure`, `activate_backup_path`, `restore_primary_path`, `probe_connectivity`, `traceroute`) remains available.

Run the end-to-end scenario (requires Linux + sudo):

```bash
sudo env REST_API_BASE=$REST_API_BASE API_KEY=$API_KEY \
  uv run python -m gen_engine_deep_eval.datacenter_agent
```

The agent boots a spine–leaf fabric, simulates a spine-to-aggregation failure, and autonomously:
1. Discovers the failure by analyzing topology and link health
2. Uses `compute_resilient_path` to identify the best alternate route
3. Activates the backup path to restore connectivity
4. Monitors both primary and backup paths
5. Restores the primary design once the link recovers
6. Reports a concise `Final Answer` summary of all actions taken

## SSL errors when connecting to HuggingFace

Corporate networks (e.g. XS4OFFICE) may intercept TLS traffic and cause `SSLError` messages when HuggingFace models are downloaded. Because `certifi` ships its own CA bundle, export the Capgemini root and intermediate certificates and append them to `.venv/Lib/site-packages/certifi/cacert.pem` (on Windows) or the equivalent path on your platform. After updating the bundle, retry the command and the download should succeed.

## Next steps

- Publish the missing `gen_engine_deep_eval.scripts:test` entry point so `uv run test` triggers the DeepEval flow automatically.
- Extend unit coverage to the observer agent once deterministic telemetry fixtures are available.

## to run the application
to install the requirments

pip3.12 install -r requirements.txt

sudo -E python3.12 -m src.gen_engine_deep_eval.datacenter_agent