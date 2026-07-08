# Containernet Setup Guide

This guide provides detailed instructions for installing and configuring Containernet on Ubuntu Linux for use with the Mininet Agentic AI project.

## What is Containernet?

Containernet is a fork of Mininet that adds Docker container support while maintaining full API compatibility with Mininet. It's actively maintained and provides:

- Full Mininet API compatibility (existing code works without changes)
- Docker container integration for realistic network emulation
- Active development and community support
- Better tooling and debugging capabilities

**Official Repository**: https://github.com/containernet/containernet

## Why Containernet Instead of Mininet?

- **Active Maintenance**: Containernet is actively developed, while Mininet development has slowed
- **API Compatible**: Drop-in replacement - no code changes needed
- **Docker Integration**: Can run containers as network nodes for more realistic scenarios
- **Better Tooling**: Improved debugging and monitoring capabilities
- **Community Support**: Active community and regular updates

## Prerequisites

- Ubuntu 20.04 or later (recommended: Ubuntu 22.04 LTS)
- Root/sudo access
- At least 4GB RAM (8GB recommended)
- 20GB free disk space
- Python 3.8 or later (Python 3.12+ for this project)

## Installation Methods

### Method 1: Docker-based Installation (Recommended)

This is the easiest method and doesn't require installing dependencies on your host system.

```bash
# Install Docker if not already installed
sudo apt-get update
sudo apt-get install -y docker.io docker-compose
sudo systemctl enable docker
sudo systemctl start docker

# Add your user to docker group (logout/login required after this)
sudo usermod -aG docker $USER

# Pull Containernet Docker image
docker pull containernet/containernet

# Run Containernet container with network privileges
docker run -it --rm --privileged --pid='host' \
    -v /var/run/docker.sock:/var/run/docker.sock \
    containernet/containernet /bin/bash
```

### Method 2: Native Installation (For Development)

For development work where you need to modify and test code directly:

#### Step 1: Install System Dependencies

```bash
# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install required packages
sudo apt-get install -y \
    git \
    ansible \
    aptitude \
    build-essential \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-venv
```

#### Step 2: Clone and Install Containernet

```bash
# Clone Containernet repository
cd ~
git clone https://github.com/containernet/containernet.git
cd containernet

# Install using Ansible (recommended)
sudo ansible-playbook -i "localhost," -c local install.yml

# OR install using the install script
# sudo util/install.sh
```

#### Step 3: Verify Installation

```bash
# Test Containernet installation
sudo python3 -c "from mininet.net import Containernet; print('Containernet imported successfully')"

# Run basic test
sudo python3 examples/containernet_example.py
```

### Method 3: From Source (Advanced)

For the latest features or custom builds:

```bash
# Clone repository
git clone https://github.com/containernet/containernet.git
cd containernet

# Install Python package in development mode
sudo pip3 install -e .

# Install Mininet core (if not already installed)
cd ~
git clone https://github.com/mininet/mininet.git
cd mininet
sudo PYTHON=python3 util/install.sh -n
```

## Configuration for This Project

### Step 1: Install Project Dependencies

```bash
cd /path/to/mininet-agentic-ai

# Create virtual environment (if not using Docker)
python3.12 -m venv .venv
source .venv/bin/activate

# Install project dependencies
pip install -r requirements.txt
pip install -r requirements-langgraph.txt  # For LangGraph features
```

### Step 2: Configure Environment Variables

```bash
# Copy environment template
cp .env.local .env

# Edit .env and add your Generative Engine credentials
# REST_API_BASE=https://api.generative.engine.capgemini.com/
# API_KEY=your-api-key-here
# GEN_ENGINE_MODEL=anthropic.claude-3-5-sonnet-20240620-v1:0

# Load environment variables
source .env
```

### Step 3: Verify Setup

```bash
# Test Containernet import (requires sudo)
sudo -E python3.12 -c "from mininet.net import Containernet; print('Success!')"

# Run unit tests (don't require Containernet)
pytest tests/test_mininet_agent.py -v

# Test Observer agent (doesn't require Containernet)
python -m gen_engine_deep_eval.observer_agent
```

## Running the DataCenter Agent

The DataCenter agent requires root privileges to create virtual networks:

```bash
# Ensure environment variables are set
source .env

# Run with sudo, preserving environment variables
sudo -E python3.12 -m gen_engine_deep_eval.datacenter_agent
```

**Important**: The `-E` flag preserves environment variables (like API keys) when running with sudo.

## Docker-based Workflow (Recommended for Production)

For production deployments, use the Docker approach:

### Step 1: Create Project Dockerfile

```dockerfile
FROM containernet/containernet:latest

# Install Python 3.12 and project dependencies
RUN apt-get update && apt-get install -y software-properties-common
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update && apt-get install -y python3.12 python3.12-venv python3.12-dev

# Copy project files
WORKDIR /app
COPY . /app

# Install dependencies
RUN python3.12 -m pip install -r requirements.txt

# Set environment variables (use Docker secrets in production)
ENV REST_API_BASE=""
ENV API_KEY=""

CMD ["python3.12", "-m", "gen_engine_deep_eval.datacenter_agent"]
```

### Step 2: Build and Run

```bash
# Build Docker image
docker build -t mininet-agentic-ai .

# Run container with network privileges
docker run -it --rm --privileged \
    -e REST_API_BASE="https://api.generative.engine.capgemini.com/" \
    -e API_KEY="your-api-key" \
    mininet-agentic-ai
```

## Troubleshooting

### Issue: "Cannot connect to Docker daemon"

```bash
# Start Docker service
sudo systemctl start docker

# Check Docker status
sudo systemctl status docker

# Add user to docker group (requires logout/login)
sudo usermod -aG docker $USER
```

### Issue: "Permission denied" when running Containernet

Containernet requires root privileges to create network namespaces:

```bash
# Always run with sudo
sudo -E python3.12 -m gen_engine_deep_eval.datacenter_agent
```

### Issue: "ModuleNotFoundError: No module named 'mininet'"

```bash
# Verify Containernet installation
sudo python3 -c "import mininet; print(mininet.__file__)"

# If missing, reinstall Containernet
cd ~/containernet
sudo ansible-playbook -i "localhost," -c local install.yml
```

### Issue: OVS (Open vSwitch) not running

```bash
# Start OVS service
sudo systemctl start openvswitch-switch

# Enable on boot
sudo systemctl enable openvswitch-switch

# Check status
sudo systemctl status openvswitch-switch
```

### Issue: "Address already in use" errors

```bash
# Clean up previous Containernet instances
sudo mn -c

# Kill any lingering processes
sudo pkill -9 -f mininet
```

### Issue: Python package conflicts

```bash
# Create clean virtual environment
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Testing the Installation

### Basic Containernet Test

```python
#!/usr/bin/env python3
"""Test Containernet basic functionality."""
from mininet.net import Containernet
from mininet.node import Controller
from mininet.cli import CLI
from mininet.link import TCLink

def test_containernet():
    net = Containernet(controller=Controller)
    
    # Add controller
    net.addController('c0')
    
    # Add hosts
    h1 = net.addHost('h1')
    h2 = net.addHost('h2')
    
    # Add switch
    s1 = net.addSwitch('s1')
    
    # Add links
    net.addLink(h1, s1)
    net.addLink(h2, s1)
    
    # Start network
    net.start()
    
    # Test connectivity
    print("Testing connectivity...")
    result = net.ping([h1, h2])
    
    # Stop network
    net.stop()
    
    print(f"Ping test: {'PASSED' if result == 0 else 'FAILED'}")
    return result == 0

if __name__ == '__main__':
    import sys
    if test_containernet():
        print("✓ Containernet is working correctly!")
        sys.exit(0)
    else:
        print("✗ Containernet test failed")
        sys.exit(1)
```

Save as `test_containernet.py` and run:

```bash
sudo python3 test_containernet.py
```

### Test DataCenter Agent

```bash
# Run DataCenter agent with Containernet
sudo -E python3.12 -m gen_engine_deep_eval.datacenter_agent

# Expected output:
# - Network topology created
# - LLM agent analyzes network
# - Remediation actions executed
# - Final summary provided
```

## Performance Tips

1. **Memory**: Allocate at least 4GB RAM for Docker containers
2. **CPU**: Use multiple cores for better performance
3. **Disk I/O**: Use SSD storage for faster container operations
4. **Network**: Disable unnecessary network interfaces to avoid conflicts

## Security Considerations

1. **Root Access**: Containernet requires root - use in isolated environments
2. **API Keys**: Never commit API keys to version control
3. **Docker Security**: Follow Docker security best practices
4. **Network Isolation**: Use Docker networks to isolate Containernet instances

## Additional Resources

- **Containernet Documentation**: https://containernet.github.io/
- **Mininet Documentation**: http://mininet.org/ (API reference still applies)
- **Docker Documentation**: https://docs.docker.com/
- **Open vSwitch**: http://www.openvswitch.org/

## Getting Help

- **Containernet Issues**: https://github.com/containernet/containernet/issues
- **Project Issues**: Open an issue in this repository
- **Community**: Join Containernet Slack/Discord channels

## Next Steps

After installing Containernet:

1. Run the Observer agent demo (no Containernet needed):
   ```bash
   python -m gen_engine_deep_eval.examples.run_observer_graph
   ```

2. Test the DataCenter agent:
   ```bash
   sudo -E python3.12 -m gen_engine_deep_eval.datacenter_agent
   ```

3. Explore LangGraph features:
   - See `LANGGRAPH_MIGRATION.md` for migration guide
   - Check `QUICKSTART.md` for usage examples

4. Build your own network scenarios:
   - Modify `build_datacenter_blueprint()` in `datacenter_agent.py`
   - Add custom failure scenarios
   - Implement domain-specific remediation strategies
