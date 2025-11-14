# Generative Engine Deep Eval & Agentic Network Lab

This repository demonstrates two complementary workflows built on Capgemini's Generative Engine:

- **DeepEval integration** – run Generative Engine as an LLM-as-judge through a LangChain-compatible wrapper.
- **Agentic network remediation** – orchestrate a ReAct agent that inspects, diagnoses, and repairs a Containernet-based data-center topology using structured tools.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Generative Engine credentials with API access
- (For the DataCenter demo) A Linux host with [Containernet](https://github.com/containernet/containernet) installed and `sudo` access
  - Containernet is an actively maintained fork of Mininet with Docker support
  - See [CONTAINERNET_SETUP.md](CONTAINERNET_SETUP.md) for detailed installation instructions

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

### Core Infrastructure
- `src/gen_engine_deep_eval/wrapper.py` – LangChain-ready `GenerativeEngineLLM` wrapper with stop token handling and session tracking.
- `src/gen_engine_deep_eval/helpers.py` / `models.py` – provider selection and response dataclasses.
- `src/gen_engine_deep_eval/llm.py` – convenience pipeline composing the wrapper with LangChain parsers for DeepEval harnesses.

### Legacy ReAct Agents (Deprecated - use LangGraph versions)
- `src/gen_engine_deep_eval/observer_agent.py` – synthetic telemetry monitor using ReAct + anomaly detection tools.
- `src/gen_engine_deep_eval/datacenter_agent.py` – Mininet automation, telemetry sampling, NetworkX topology graphing, and the expanded toolbelt (`inspect_link_health`, `compute_resilient_path`, `monitor_link`, `simulate_failure`, etc.).

### LangGraph-based Agents (Recommended)
- `src/gen_engine_deep_eval/graphs/observer_graph.py` – Observer agent with state machine architecture, checkpointing, and structured state management.
- `src/gen_engine_deep_eval/graphs/datacenter_graph.py` – DataCenter agent with graph-based remediation workflow, human-in-the-loop support, and state persistence.
- `src/gen_engine_deep_eval/graphs/gui_datacenter_graph.py` – **NEW**: GUI-driven datacenter agent with dynamic topology discovery (see [GUI Integration](#gui-integration) below).
- `src/gen_engine_deep_eval/graphs/state_schemas.py` – TypedDict state models for type-safe agent state management.
- `src/gen_engine_deep_eval/graphs/tools.py` – LangGraph-compatible tool definitions.
- `src/gen_engine_deep_eval/examples/run_observer_graph.py` – Example demonstrating Observer agent with LangGraph.

### GUI Integration (NEW!)
- `src/gen_engine_deep_eval/gui_adapter.py` – REST API adapter to transform GUI topology JSON into agent's internal format.
- `gui/app.py` – Flask-based network simulation tool with web interface and REST API.
- `gui/datacenter_topology.json` / `gui/datacenter_topology_large.json` – Sample topology files for GUI.
- **Documentation**:
  - [GUI_INTEGRATION_GUIDE.md](GUI_INTEGRATION_GUIDE.md) – Complete user guide for GUI mode
  - [GUI_INTEGRATION_ANALYSIS.md](GUI_INTEGRATION_ANALYSIS.md) – Technical design analysis
  - [GUI_IMPLEMENTATION_SUMMARY.md](GUI_IMPLEMENTATION_SUMMARY.md) – Implementation details

### Tests
- `tests/test_mininet_agent.py` – unit coverage for prompt wiring, credential validation, topology graph filters, and JSON tool contracts.
- `tests/test_observer_graph.py` – LangGraph Observer agent tests with mocked LLM and telemetry.
- `tests/test_datacenter_graph.py` – LangGraph DataCenter agent tests with mocked environment.

## Running tests

Execute the fast unit suite (includes graph/pathing checks for the new tools and LangGraph implementations):

```bash
uv run pytest
```

Or with pip:

```bash
pytest tests/
```

Run specific test suites:

```bash
# Test LangGraph Observer agent
pytest tests/test_observer_graph.py -v

# Test LangGraph DataCenter agent
pytest tests/test_datacenter_graph.py -v

# Test legacy Mininet agent
pytest tests/test_mininet_agent.py -v
```

DeepEval jobs can be wired into CI once the `gen_engine_deep_eval.scripts:test` entry point is published. Until then, use the LangChain chain in `llm.py` directly or wrap it inside your own DeepEval scenario.

## LangGraph Agent Architecture (Recommended)

The repository now includes modern state machine-based agents using LangGraph, offering superior observability, state management, and control flow compared to the legacy ReAct pattern.

### Observer Agent with LangGraph

The LangGraph-based Observer agent provides:
- **State Machine Architecture**: Explicit nodes for telemetry analysis, anomaly detection, and reasoning
- **Checkpointing**: Built-in state persistence for resuming analysis
- **Streaming Support**: Real-time visibility into agent reasoning
- **Type-Safe State**: TypedDict schemas for reliable state management

Run the LangGraph Observer demo:

```bash
python -m gen_engine_deep_eval.examples.run_observer_graph
```

**Graph Structure:**
- `analyze_telemetry` → Fetch latest telemetry snapshot
- `detect_issues` → Run z-score and rule-based anomaly detection
- `reason` → LLM analyzes findings and recommends actions
- `should_continue` → Conditional edge based on anomaly severity

**Key Features:**
- Iteration limit control (prevents infinite loops)
- Analysis history tracking
- Configurable anomaly thresholds
- Checkpoint/resume capability via thread IDs

### DataCenter Agent with LangGraph

The LangGraph DataCenter agent adds:
- **Human-in-the-Loop**: Interrupt points before critical remediation actions
- **State Persistence**: Integration with Mininet state export/load
- **Parallel Remediation**: Support for multiple concurrent failure scenarios
- **Verification Loop**: Automatic recovery validation

**Graph Structure:**
- `assess_network` → Evaluate overall network health
- `plan_remediation` → LLM generates remediation strategy
- `execute_action` → Execute planned actions (backup paths, monitoring, etc.)
- `verify_recovery` → Confirm successful remediation
- `should_continue` → Loop until network healthy or max iterations

**Available Actions:**
- `monitor_link` - Check link health and metrics
- `activate_backup_path` - Bring alternate paths online
- `restore_primary_path` - Restore failed links after recovery
- `probe_connectivity` - Test end-to-end connectivity
- `traceroute` - Trace packet paths through topology
- `simulate_failure` - Inject failures for testing (cable_cut, latency_spike, congestion, packet_loss)

**Graph Visualization:**

Both agents support Mermaid diagram export:

```python
from gen_engine_deep_eval.graphs.observer_graph import build_observer_graph

graph = build_observer_graph(llm, state_provider)
mermaid_diagram = graph.get_graph().draw_mermaid()
print(mermaid_diagram)
```

## Legacy Observer Agent Demo (Deprecated)

The legacy observer agent seeds a synthetic telemetry window and asks the LLM to decide when to call structured tools (`latest_snapshot`, `detect_anomalies`) before summarising findings.

```bash
uv run --env-file .env python -m gen_engine_deep_eval.observer_agent
```

Highlights:

- Z-score anomaly detection combined with domain thresholds (latency, CPU, packet loss).
- Strict ReAct prompt enforcing alternating `Thought`/`Action` steps and a single `Final Answer`.
- Stop-token aware wrapper prevents the model from streaming partial final answers.

**Note:** This implementation is maintained for backward compatibility but new projects should use the LangGraph version.

## Legacy Mininet Data-Center Remediation Demo (Deprecated)

The data-center agent extends the environment with richer telemetry and path-planning capabilities:

- Live link profiles track bandwidth, latency, utilisation, and loss via `_sample_link_metrics`.
- A cached NetworkX graph (`_get_topology_graph`) drives shortest-path calculations and supports avoiding failed edges.
- New LangChain tools expose these insights to the LLM:
  - `inspect_link_health` – return current metrics and status for any link.
   - `compute_resilient_path` – compute latency- or capacity-aware alternate paths between nodes (supports `avoid` entries as `[src, dst]` pairs or strings like `"src-dst"`).
   - `monitor_link` now returns structured errors with suggested neighbour links if you reference a non-existent edge.
  - Existing tooling (`monitor_link`, `simulate_failure`, `activate_backup_path`, `restore_primary_path`, `probe_connectivity`, `traceroute`) remains available.

Run the end-to-end scenario (requires Linux + sudo + Containernet):

```bash
# LangGraph mode (default, recommended)
sudo env REST_API_BASE=$REST_API_BASE API_KEY=$API_KEY \
  uv run python -m gen_engine_deep_eval.datacenter_agent

# Legacy ReAct mode
sudo env REST_API_BASE=$REST_API_BASE API_KEY=$API_KEY \
  uv run python -m gen_engine_deep_eval.datacenter_agent --react
```

**Note:** This agent now uses **Containernet** (an actively maintained fork of Mininet with Docker support). Containernet is API-compatible with Mininet, so no code changes were needed. See [CONTAINERNET_SETUP.md](CONTAINERNET_SETUP.md) for installation instructions.

### LangGraph Mode (Default - Recommended)

The datacenter agent now supports **LangGraph state machine architecture** for superior observability and control:

- **State Machine Flow**: `assess_network → plan_remediation → execute_action → verify_recovery`
- **Type-Safe State**: TypedDict schema with network health tracking
- **Checkpointing**: Save/resume remediation sessions
- **Human-in-the-Loop**: Optional approval for critical changes
- **Better Debugging**: Clear node boundaries and state transitions

See [DATACENTER_LANGGRAPH.md](DATACENTER_LANGGRAPH.md) for detailed migration guide and usage examples.

### Legacy ReAct Mode

The agent boots a spine–leaf fabric, simulates a spine-to-aggregation failure, and autonomously:
1. Discovers the failure by analyzing topology and link health
2. Uses `compute_resilient_path` to identify the best alternate route
3. Activates the backup path to restore connectivity
4. Provides a concise `Final Answer` summary of actions taken

**Performance constraints:**
- Agent limited to **10 iterations** (down from 15) and **5 minutes** execution time
- Model `max_tokens` reduced to **512** (from 2048) to leave more room for ReAct scratchpad
- Tool outputs now **exclude verbose interface statistics** to minimize context growth
- System prompt instructs agent to **skip post-activation monitoring** and provide Final Answer immediately

**Troubleshooting 500 errors:**
If you still encounter `Internal Server Error` from the Generative Engine API:
1. The ReAct scratchpad has exceeded the model's context window (typically after 3-4 tool calls)
2. Try reducing `max_iterations` to 8 in `datacenter_agent.py`
3. Consider further reducing `max_tokens` to 384
4. Simplify the `investigation_prompt` in `MininetScenario` to request fewer diagnostic steps
5. Monitor the agent logs – if you see repeated tool calls, the system prompt may need stricter early-termination guidance
6. **Recommended**: Switch to LangGraph mode which handles context better

## SSL errors when connecting to HuggingFace

Corporate networks (e.g. XS4OFFICE) may intercept TLS traffic and cause `SSLError` messages when HuggingFace models are downloaded. Because `certifi` ships its own CA bundle, export the Capgemini root and intermediate certificates and append them to `.venv/Lib/site-packages/certifi/cacert.pem` (on Windows) or the equivalent path on your platform. After updating the bundle, retry the command and the download should succeed.

## Next steps

- Publish the missing `gen_engine_deep_eval.scripts:test` entry point so `uv run test` triggers the DeepEval flow automatically.
- Extend unit coverage to the observer agent once deterministic telemetry fixtures are available.

## Setup environment and run the application

### GUI Mode (Recommended - No sudo required!)

The easiest way to get started is using GUI mode, which doesn't require Mininet/Containernet:

```bash
# 1. Start GUI simulation tool
cd gui && uv run python app.py
# GUI available at http://localhost:5000

# 2. In another terminal, run agent in GUI mode
uv run python -m gen_engine_deep_eval.datacenter_agent --gui

# 3. Or run the interactive demo
./demo_gui_integration.sh
```

**See [GUI_INTEGRATION_GUIDE.md](GUI_INTEGRATION_GUIDE.md) for complete documentation.**

### Mininet/Containernet Mode (Advanced)

For actual network simulation with Mininet/Containernet:

This application now uses **Containernet** instead of Mininet. Containernet is an actively maintained fork with Docker support and full API compatibility.

**See [CONTAINERNET_SETUP.md](CONTAINERNET_SETUP.md) for complete installation instructions.**

Quick install (Ubuntu/Debian):

```bash
# Install dependencies
sudo apt update
sudo apt install git ansible aptitude

# Clone Containernet repository
git clone https://github.com/containernet/containernet.git
cd containernet

# Install using Ansible (recommended)
sudo ansible-playbook -i "localhost," -c local install.yml
```

### Install project requirements

```bash
# Go to project folder
cd /path/to/mininet-agentic-ai

# Install Python dependencies
pip3.12 install -r requirements.txt

# Run the DataCenter agent with Containernet
sudo -E python3.12 -m gen_engine_deep_eval.datacenter_agent
```

**Note**: The `-E` flag preserves environment variables when running with sudo.
