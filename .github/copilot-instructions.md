# AI Agent Instructions for Generative Engine Deep Eval Project

## Project Overview
This is a **dual-purpose LLM evaluation framework** that combines:
1. **DeepEval integration** - LLM-as-judge evaluation using Capgemini's Generative Engine
2. **Observer Agent PoC** - Agentic SDN network monitoring with anomaly detection

## Core Architecture

### Generative Engine Integration
- **Primary LLM Wrapper**: `src/gen_engine_deep_eval/wrapper.py` - Custom LangChain LLM for Capgemini's Generative Engine v2 API
- **Model Provider Logic**: `helpers.py` maps model names to providers (bedrock, azure, vertexai, liquidai)
- **Response Processing**: `models.py` defines `GenerativeEngineResponse` with session tracking
- **Chain Building**: `llm.py` creates LangChain chains with JSON parsing

### Observer Agent Pattern
- **Main Agent**: `observer_agent.py` implements ReAct agent with tools for telemetry analysis
- **Synthetic Data**: Uses statistical anomaly detection (z-scores) + domain rules for network metrics
- **Tool Architecture**: LangChain Tools for `latest_snapshot` and `detect_anomalies`

### Mininet Data-Center Agent
- **Module**: `datacenter_agent.py` defines a spine-leaf blueprint (core ➝ aggregation ➝ access ➝ host) with switch models, link media, and baseline speed/latency profiles.
- **Import/Export**: `DataCenterEnvironment.export_state()` / `save_state()` persist blueprint + live link metrics; `DataCenterEnvironment.load_state()` restores them for repeatable drills.
- **Failure Simulation**: `simulate_failure` supports `cable_cut`, `cable_unplug`, `latency_spike`, `congestion`, and `packet_loss` modes, adjusting link state, bandwidth, delay, and utilisation.
- **Remediation Tools**: `activate_backup_path` brings alternate paths online; `restore_primary_path` reapplies baseline once healthy; `monitor_link`, `probe_connectivity`, and `traceroute` provide ongoing health signals.

## Development Workflows

### Environment Setup (Critical)
```bash
# Always use uv for dependency management
uv sync

# Environment variables required in .env:
REST_API_BASE=https://api.generative.engine.capgemini.com/
API_KEY="your-api-key-here"  # From Generative Engine portal
GEN_ENGINE_MODEL=anthropic.claude-3-5-sonnet-20240620-v1:0
```

### Testing Commands
```bash
# Run DeepEval tests (references missing tests/test_example.py)
uv run test  # Executes gen_engine_deep_eval.scripts:test

# Alternative direct command mentioned in README
uv run --env-file .env deepeval test run tests/test_example.py

# Run Observer Agent demo
uv run --env-file .env python -m gen_engine_deep_eval.observer_agent

# Run Mininet data-center demo (requires sudo + Mininet)
sudo env REST_API_BASE=$REST_API_BASE API_KEY=$API_KEY \
    uv run python -m gen_engine_deep_eval.datacenter_agent
```

## Key Patterns & Conventions

### API Integration Pattern
- **Always use `GenerativeEngineLLM` wrapper** instead of direct API calls
- **Session management**: Each LLM instance gets unique `session_id` via `uuid4()`
- **Stop token handling**: Critical for ReAct agents - `wrapper.py` properly truncates at stop sequences
- **Error handling**: Logs JSON errors first, falls back to text response

### Model Configuration Approach
```python
# Standard pattern from observer_agent.py
config = Config(
    model="anthropic.claude-3-5-sonnet-20240620-v1:0",
    max_tokens=2048,
    temperature=0.05  # Low temp for structured output
)
```

### Agent Tool Implementation
- **ReAct Format**: Use `ZERO_SHOT_REACT_DESCRIPTION` agent type with strict format enforcement
- **Tool Design**: Return JSON strings, not objects - LangChain parsers expect string responses
- **System Prompts**: Include format policy to prevent parsing errors

### Mininet Topology Patterns
- **Blueprints**: `TopologyBlueprint` + `NodeSpec`/`LinkSpec` capture roles, switch models, link speeds, and media. Always serialise with `to_dict()` before persisting JSON snapshots.
- **Profiles**: `LinkProfile` tracks live bandwidth/latency/loss & utilisation. Mutate through `_apply_link_profile` helpers to keep metadata + Mininet settings in sync.
- **State Persistence**: Prefer `DataCenterEnvironment.save_state()` for repeatable drills; rehydrate via `load_state()` without re-calling `__post_init__()`.
- **Failure Simulation**: Use `simulate_failure` with modes (`cable_cut`, `latency_spike`, `congestion`, `packet_loss`) to adjust both Mininet link status and synthetic utilisation.

### Corporate Network Considerations
- **SSL Certificate Issues**: On corporate networks (XS4OFFICE), manually add Capgemini CAs to `certifi` package
- **HuggingFace Access**: Embedding model downloads may fail due to ZScaler certificate replacement

## Code Quality Standards
- **Line Length**: 88 characters (Ruff configuration)
- **Python Version**: Requires >=3.12
- **Import Organization**: Ruff handles with `["E", "F", "I"]` selection
- **Logging**: Use `loguru` for structured logging throughout

## Project-Specific Anti-Patterns
- **Don't bypass the LLM wrapper** - Always use `GenerativeEngineLLM` for consistency
- **Don't hardcode API endpoints** - Use environment variables for all Generative Engine config
- **Don't ignore stop tokens** - Critical for agent parsing, implemented in `wrapper._call()`
- **Avoid streaming for agents** - Set `"streaming": False` in `modelKwargs` for clean ReAct parsing
- **Avoid manual JSON tweaks** - Use `TopologyBlueprint.to_dict()` / `from_dict()` helpers; editing saved topology files by hand risks schema drift.

## Missing Components (Development Opportunities)
- **Test Suite**: `tests/test_example.py` referenced but not present
- **Scripts Module**: `gen_engine_deep_eval.scripts:test` entry point missing
- **Documentation**: API response schemas could be more detailed

## Integration Points
- **DeepEval Metrics**: Hallucination detection, end-to-end evaluation
- **LangChain Compatibility**: Full integration with chains, agents, and parsers
- **Synthetic Telemetry**: Observer agent uses in-memory data simulation for SDN monitoring