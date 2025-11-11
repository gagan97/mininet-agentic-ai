# Development Setup Guide

This guide walks through setting up the development environment for the Mininet Agentic AI project with LangGraph support and Containernet.

## Prerequisites

- Python 3.12+
- Linux system (required for Containernet)
- sudo access (required for Containernet)
- Git

## Installation Steps

### 1. Install System Dependencies

```bash
sudo apt update
sudo apt install git python3-dev python3-pip build-essential
```

### 2. Install Containernet (Optional - only for DataCenter agent)

**Containernet** is an actively maintained fork of Mininet with Docker support. It's fully API-compatible with Mininet.

**For detailed installation instructions, see [CONTAINERNET_SETUP.md](CONTAINERNET_SETUP.md).**

Quick install:

```bash
# Install Ansible
sudo apt-get install ansible aptitude

# Clone Containernet repository
git clone https://github.com/containernet/containernet.git
cd containernet

# Install using Ansible (recommended method)
sudo ansible-playbook -i "localhost," -c local install.yml

# Return to project directory
cd ../mininet-agentic-ai
```

### 3. Set Up Python Environment

#### Option A: Using uv (Recommended)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies
uv sync

# Activate environment
source .venv/bin/activate
```

#### Option B: Using pip

```bash
# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install core dependencies
pip install -r requirements.txt

# Install LangGraph dependencies
pip install -r requirements-langgraph.txt
```

### 4. Configure Environment Variables

```bash
# Copy template
cp .env.local .env

# Edit .env and add your credentials:
# REST_API_BASE=https://api.generative.engine.capgemini.com/
# API_KEY=your-api-key-here
# GEN_ENGINE_MODEL=anthropic.claude-3-5-sonnet-20240620-v1:0

# Load environment
source .env
```

## Verify Installation

### Test Containernet Imports

```bash
python3.12 -c "
from gen_engine_deep_eval.wrapper import GenerativeEngineLLM
from gen_engine_deep_eval.observer_agent import DigitalTwinState
print('Core imports OK')
"
```

### Test LangGraph Imports

```bash
python3.12 -c "
from gen_engine_deep_eval.graphs.state_schemas import ObserverState
from gen_engine_deep_eval.graphs.observer_graph import build_observer_graph
print('LangGraph imports OK')
"
```

### Run Tests

```bash
# Run all tests
pytest

# Run specific test suites
pytest tests/test_observer_graph.py -v
pytest tests/test_datacenter_graph.py -v
pytest tests/test_mininet_agent.py -v
```

## Running the Agents

### Observer Agent (Legacy ReAct)

```bash
python -m gen_engine_deep_eval.observer_agent
```

### Observer Agent (LangGraph)

```bash
python -m gen_engine_deep_eval.examples.run_observer_graph
```

### DataCenter Agent (Legacy ReAct - requires Containernet)

```bash
sudo -E python -m gen_engine_deep_eval.datacenter_agent
```

### DataCenter Agent (LangGraph - requires Containernet)

Coming soon - example script in development.

## Development Workflow

### 1. Code Style

The project uses Ruff for linting:

```bash
# Install Ruff
pip install ruff

# Check code style
ruff check src/ tests/

# Auto-fix issues
ruff check --fix src/ tests/
```

### 2. Type Checking

```bash
# Install mypy
pip install mypy

# Run type checker
mypy src/gen_engine_deep_eval/graphs/
```

### 3. Running Tests Iteratively

```bash
# Run tests with verbose output
pytest -v

# Run specific test file
pytest tests/test_observer_graph.py -v

# Run specific test function
pytest tests/test_observer_graph.py::test_build_observer_graph -v

# Run with coverage
pytest --cov=gen_engine_deep_eval --cov-report=html
```

### 4. Visualizing Graphs

```python
from gen_engine_deep_eval.wrapper import GenerativeEngineLLM
from gen_engine_deep_eval.observer_agent import DigitalTwinState
from gen_engine_deep_eval.graphs.observer_graph import build_observer_graph

# Setup
llm = GenerativeEngineLLM(model="...", api_base="...", api_key="...")
state_provider = DigitalTwinState()

# Build graph
graph = build_observer_graph(llm, state_provider)

# Get Mermaid diagram
mermaid = graph.get_graph().draw_mermaid()
print(mermaid)

# Save to file
with open("graph.mmd", "w") as f:
    f.write(mermaid)
```

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'langgraph'"

**Solution:**
```bash
pip install langgraph langgraph-checkpoint
```

### Issue: "ModuleNotFoundError: No module named 'mininet'"

**Solution:**
Containernet uses the `mininet` Python module namespace for API compatibility. Install Containernet:

```bash
# Follow detailed instructions in CONTAINERNET_SETUP.md
git clone https://github.com/containernet/containernet.git
cd containernet
sudo ansible-playbook -i "localhost," -c local install.yml
```

### Issue: "HTTPSConnectionPool timeout" during pip install

**Solution:**
```bash
# Increase timeout
pip install --timeout=300 -r requirements.txt

# Or use a different index
pip install -i https://pypi.python.org/simple -r requirements.txt
```

### Issue: SSL errors with corporate proxy

**Solution:**
On corporate networks (e.g., XS4OFFICE), manually add CA certificates:

```bash
# Export corporate root and intermediate certificates
# Append to certifi bundle
cat corporate-ca.crt >> .venv/lib/python3.12/site-packages/certifi/cacert.pem
```

### Issue: "Permission denied" when running Containernet agent

**Solution:**
Containernet requires sudo:
```bash
sudo -E python -m gen_engine_deep_eval.datacenter_agent
```

The `-E` flag preserves environment variables (API keys).

## Project Structure

```
mininet-agentic-ai/
├── src/gen_engine_deep_eval/
│   ├── wrapper.py              # GenerativeEngineLLM wrapper
│   ├── observer_agent.py       # Legacy Observer agent
│   ├── datacenter_agent.py     # Legacy DataCenter agent
│   ├── graphs/                 # LangGraph implementations
│   │   ├── __init__.py
│   │   ├── state_schemas.py    # TypedDict state models
│   │   ├── observer_graph.py   # Observer state machine
│   │   ├── datacenter_graph.py # DataCenter state machine
│   │   └── tools.py            # LangGraph-compatible tools
│   └── examples/               # Usage examples
│       └── run_observer_graph.py
├── tests/
│   ├── test_mininet_agent.py   # Legacy agent tests
│   ├── test_observer_graph.py  # Observer graph tests
│   └── test_datacenter_graph.py # DataCenter graph tests
├── requirements.txt            # Core dependencies
├── requirements-langgraph.txt  # LangGraph dependencies
├── pyproject.toml             # Project metadata
├── README.md                  # Project overview
├── LANGGRAPH_MIGRATION.md     # Migration guide
└── SETUP.md                   # This file
```

## Next Steps

1. Review [LANGGRAPH_MIGRATION.md](LANGGRAPH_MIGRATION.md) for migration guide
2. Read [README.md](README.md) for project overview
3. Run tests to verify setup
4. Try example scripts
5. Start developing!

## Resources

- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Containernet Documentation](https://containernet.github.io/)
- [Containernet GitHub](https://github.com/containernet/containernet)
- [Generative Engine Documentation](https://generative.engine.capgemini.com/studio/documentation)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)

## Getting Help

- Check existing tests for usage examples
- Review the migration guide
- Consult LangGraph documentation
- Open an issue on GitHub
