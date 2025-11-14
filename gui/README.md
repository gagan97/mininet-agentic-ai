# 🌐 Network Simulation Tool for AI Agents - Complete Documentation

A comprehensive tool for simulating network outages and providing RESTful APIs for AI agents to interact with network infrastructure simulations. This tool transforms original HTML simulation files into a production-ready API that AI agents can interact with.

## 📁 Project Structure

```
ai_gent_tool/
├── 📄 app.py                          # Main Flask API server
├── 📄 requirements.txt               # Python dependencies
├── 📄 demo.py                        # Simple demo script
├── 📄 test_api.py                    # Comprehensive API test
├── 📄 quick_test.py                  # Quick endpoint validation
├── 📂 public/
│   └── 📄 index.html                 # Modern web interface
├── 📄 dt-cable-pluggeout.html        # Original simulation (legacy)
└── 📄 dt-sfp-pluggedout.html         # Original SFP simulation (legacy)
```

## 🚀 Features & Capabilities

### Core Features
- **Interactive Web Interface**: Visual representation of network topology with real-time status updates
- **RESTful API**: Well-documented endpoints for AI agents to query and manipulate network state
- **Persistent State Management**: In-memory storage of network state and issues
- **Real-time Monitoring**: Live updates of network health and statistics
- **Cross-Platform**: Python-based, runs anywhere
- **Zero Configuration**: Works out of the box

### Network Simulation Types
- **Cable Issues**: Plug-out, Cut, Traffic Drop
- **SFP Problems**: Type mismatches (SR/LR/ZR)
- **State Tracking**: Real-time issue logging with timestamps and severity levels
- **Health Monitoring**: HEALTHY/DEGRADED/CRITICAL status transitions

### Network Topology
- **3 Switches** (Switch 1, Switch 2, Switch 3)
- **8 Ports per Switch** (24 total ports)
- **SFP Types**: SR (Short Range), LR (Long Range), ZR (Extended Range)
- **Port States**: Connected, Plugged Out, Cable Cut, Traffic Drop
- **Issue Severity Levels**: WARNING, ERROR, CRITICAL

## 🛠️ Installation & Quick Start

### 1. Installation
```bash
# Navigate to project directory
cd "c:\Users\gaggupta\Development\GenAI\Example\ai_gent_tool"

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Start the Server
```bash
python app.py
```

The server will start on http://localhost:5000 with:
- 🚀 Main Interface: http://localhost:5000
- 📚 API Documentation: http://localhost:5000/api/docs
- 🌐 Web Interface: http://localhost:5000


# To install and run with uv
GUI requirements installed with:

     cd /home/azureuser/mininet-agentic-ai/gui
     uv pip install -r requirements.txt

To run the GUI :

     # From project root
     cd /home/azureuser/mininet-agentic-ai
     uv run --directory gui python app.py

     # Or from gui directory
     cd /home/azureuser/mininet-agentic-ai/gui
     uv run python app.py

   To run in background (detached):

     cd /home/azureuser/mininet-agentic-ai
     nohup uv run --directory gui python app.py > gui.log 2>&1 &


### 3. Quick Validation
```bash
# Check network status
curl http://localhost:5000/api/network/status

# Simulate a cable issue
curl -X POST http://localhost:5000/api/network/simulate/cable-plugout

# View current issues
curl http://localhost:5000/api/network/issues?resolved=false
```

## 📖 Complete API Reference

### Base URL: `http://localhost:5000/api`

### Query Endpoints

#### Network Status
```
GET /network/status
```
Get network overview and health statistics

**Response Example:**
```json
{
  "success": true,
  "data": {
    "id": "unique-session-id",
    "timestamp": "2025-09-23T10:30:00.000Z",
    "overview": {
      "totalSwitches": 3,
      "totalPorts": 24,
      "activePorts": 22,
      "faultyPorts": 2,
      "totalIssues": 2
    },
    "healthStatus": "DEGRADED"
  }
}
```

#### Network Topology
```
GET /network/topology
```
Get complete network topology with all switches and ports

#### Network Issues
```
GET /network/issues
GET /network/issues?resolved=false
```
Get all network issues (filterable by resolution status)

#### Switch & Port Details
```
GET /network/ports/{switchId}    # Get all ports for a specific switch
GET /network/port/{portId}       # Get detailed information about a specific port
```

### Simulation Endpoints

#### Cable Simulations
```
POST /network/simulate/cable-plugout    # Simulate cable being unplugged (WARNING)
POST /network/simulate/cable-cut        # Simulate cable being cut (CRITICAL)
POST /network/simulate/traffic-drop     # Simulate traffic drop (WARNING)
```

#### SFP Simulations
```
POST /network/simulate/sfp-mismatch     # Simulate wrong SFP type (ERROR)
```

**Simulation Request Body (Optional):**
```json
{
  "switchId": "switch-0",        // Optional: target specific switch
  "portNumber": 1,               // Optional: target specific port  
  "wrongSfpType": "LR"          // Optional: for SFP mismatch simulation
}
```

**Simulation Response Example:**
```json
{
  "success": true,
  "message": "Cable plug-out simulation executed",
  "data": {
    "affectedSwitch": "Switch 1",
    "affectedPort": 3,
    "portId": "switch-0-port-2",
    "issue": {
      "id": "issue-uuid",
      "type": "CABLE_PLUGGED_OUT",
      "description": "Cable unplugged from Port 3 on Switch 1",
      "timestamp": "2025-09-23T10:30:00.000Z",
      "severity": "WARNING",
      "resolved": false
    }
  }
}
```

### Management Endpoints
```
POST /network/reset              # Reset network to healthy state
GET /docs                        # Get complete API documentation
```

## 🤖 AI Agent Integration

### OpenAI Function Schema
```json
{
  "name": "network_simulation_tool",
  "description": "Simulate network outages and query network infrastructure state. Supports cable failures, SFP mismatches, and traffic issues.",
  "parameters": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": [
          "query_status",
          "query_topology", 
          "query_issues",
          "simulate_cable_plugout",
          "simulate_cable_cut", 
          "simulate_traffic_drop",
          "simulate_sfp_mismatch",
          "reset_network"
        ],
        "description": "The action to perform on the network simulation"
      },
      "target_switch": {
        "type": "string",
        "enum": ["switch-0", "switch-1", "switch-2"],
        "description": "Optional: Specific switch to target for simulations"
      },
      "target_port": {
        "type": "integer",
        "minimum": 1,
        "maximum": 8,
        "description": "Optional: Specific port number to target (1-8)"
      },
      "sfp_type": {
        "type": "string",
        "enum": ["SR", "LR", "ZR"],
        "description": "Optional: SFP type for mismatch simulation (SR=Short Range, LR=Long Range, ZR=Extended Range)"
      }
    },
    "required": ["action"]
  }
}
```

### Anthropic Tool Schema
```json
{
  "name": "network_simulation_tool",
  "description": "A tool for simulating network infrastructure issues and querying current network state. Useful for testing incident response, monitoring network health, and simulating various failure scenarios.",
  "input_schema": {
    "type": "object",
    "properties": {
      "action": {
        "type": "string",
        "enum": [
          "query_status",
          "query_topology",
          "query_issues", 
          "simulate_cable_plugout",
          "simulate_cable_cut",
          "simulate_traffic_drop",
          "simulate_sfp_mismatch",
          "reset_network"
        ],
        "description": "The specific action to perform"
      },
      "target_switch": {
        "type": "string",
        "description": "Switch identifier (switch-0, switch-1, switch-2). If not specified, random selection will be used for simulations."
      },
      "target_port": {
        "type": "integer",
        "description": "Port number (1-8). If not specified, random selection will be used for simulations."
      },
      "sfp_type": {
        "type": "string",
        "description": "SFP type for mismatch simulation: SR (Short Range), LR (Long Range), ZR (Extended Range)"
      }
    },
    "required": ["action"]
  }
}
```

### Python Client Implementation
```python
import requests
import json

class NetworkSimulationTool:
    def __init__(self, base_url="http://localhost:5000/api"):
        self.base_url = base_url
    
    def execute(self, action, target_switch=None, target_port=None, sfp_type=None):
        """Execute network simulation tool action"""
        
        if action == "query_status":
            return self._get_request("/network/status")
        
        elif action == "query_topology":
            return self._get_request("/network/topology")
        
        elif action == "query_issues":
            return self._get_request("/network/issues?resolved=false")
        
        elif action == "reset_network":
            return self._post_request("/network/reset")
        
        elif action.startswith("simulate_"):
            simulation_type = action.replace("simulate_", "").replace("_", "-")
            endpoint = f"/network/simulate/{simulation_type}"
            
            payload = {}
            if target_switch:
                payload["switchId"] = target_switch
            if target_port:
                payload["portNumber"] = target_port
            if sfp_type and action == "simulate_sfp_mismatch":
                payload["wrongSfpType"] = sfp_type
            
            return self._post_request(endpoint, payload)
        
        else:
            return {"error": f"Unknown action: {action}"}
    
    def _get_request(self, endpoint):
        try:
            response = requests.get(f"{self.base_url}{endpoint}")
            return response.json()
        except Exception as e:
            return {"error": str(e)}
    
    def _post_request(self, endpoint, payload=None):
        try:
            response = requests.post(
                f"{self.base_url}{endpoint}",
                json=payload or {},
                headers={"Content-Type": "application/json"}
            )
            return response.json()
        except Exception as e:
            return {"error": str(e)}

# Usage Examples
tool = NetworkSimulationTool()

# Check network status
status = tool.execute("query_status")
print(f"Network Health: {status['data']['healthStatus']}")

# Simulate a cable issue on specific port
result = tool.execute("simulate_cable_cut", target_switch="switch-0", target_port=1)
print(f"Simulation Result: {result['message']}")

# Query current issues
issues = tool.execute("query_issues")
print(f"Active Issues: {len(issues['data'])}")

# Reset network
reset_result = tool.execute("reset_network")
print(f"Reset: {reset_result['message']}")
```

### JavaScript/Node.js Client Implementation
```javascript
class NetworkSimulationTool {
    constructor(baseUrl = 'http://localhost:5000/api') {
        this.baseUrl = baseUrl;
    }

    async execute(action, options = {}) {
        const { target_switch, target_port, sfp_type } = options;
        
        try {
            switch (action) {
                case 'query_status':
                    return await this.get('/network/status');
                
                case 'query_topology':
                    return await this.get('/network/topology');
                
                case 'query_issues':
                    return await this.get('/network/issues?resolved=false');
                
                case 'reset_network':
                    return await this.post('/network/reset');
                
                default:
                    if (action.startsWith('simulate_')) {
                        const simulationType = action.replace('simulate_', '').replace('_', '-');
                        const endpoint = `/network/simulate/${simulationType}`;
                        
                        const payload = {};
                        if (target_switch) payload.switchId = target_switch;
                        if (target_port) payload.portNumber = target_port;
                        if (sfp_type && action === 'simulate_sfp_mismatch') {
                            payload.wrongSfpType = sfp_type;
                        }
                        
                        return await this.post(endpoint, payload);
                    }
                    throw new Error(`Unknown action: ${action}`);
            }
        } catch (error) {
            return { error: error.message };
        }
    }

    async get(endpoint) {
        const response = await fetch(`${this.baseUrl}${endpoint}`);
        return await response.json();
    }

    async post(endpoint, payload = {}) {
        const response = await fetch(`${this.baseUrl}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        return await response.json();
    }
}

// Usage Example
const tool = new NetworkSimulationTool();

async function exampleUsage() {
    // Monitor network health
    const status = await tool.execute('query_status');
    console.log(`Network Status: ${status.data.healthStatus}`);
    
    // Simulate random cable failure
    const simulation = await tool.execute('simulate_cable_plugout');
    console.log(`Simulation: ${simulation.message}`);
    
    // Check for issues
    const issues = await tool.execute('query_issues');
    console.log(`Current Issues: ${issues.data.length}`);
}
```

## 🎮 Web Interface Features

- **Real-time Visualization**: Live network topology with color-coded port statuses
- **Interactive Controls**: Buttons to trigger various simulation scenarios
- **Statistics Dashboard**: Overview of network health and issue counts
- **Issue Timeline**: Chronological list of all network events with timestamps
- **API Documentation**: Built-in documentation browser
- **Auto-refresh**: Real-time updates every 10 seconds

## 🎯 Use Cases for AI Agents

### 1. Network Monitoring Agent
```python
def monitor_network_health():
    status = tool.execute("query_status")
    if status['data']['healthStatus'] != 'HEALTHY':
        issues = tool.execute("query_issues")
        return f"ALERT: Network {status['data']['healthStatus']} - {len(issues['data'])} issues detected"
    return "Network healthy"
```

### 2. Incident Simulation Agent  
```python
def simulate_incident_scenario():
    # Start with clean state
    tool.execute("reset_network")
    
    # Simulate cascading failures
    tool.execute("simulate_cable_cut", target_switch="switch-0", target_port=1)
    tool.execute("simulate_traffic_drop", target_switch="switch-1", target_port=3)
    
    # Assess impact
    status = tool.execute("query_status")
    return status['data']
```

### 3. Incident Response Training
- Simulate network failures for AI training
- Automatically detect and categorize network problems
- Generate reports on network incidents and patterns

### 4. Automated Testing
- Validate network management systems
- Test monitoring and alerting systems
- Verify incident response procedures

### 5. Documentation Generation
- Create incident reports with timestamps
- Analyze failure patterns and trends
- Generate network health summaries

## 🧪 Comprehensive Testing

The project includes a unified test suite (`comprehensive_test.py`) that combines all testing scenarios without redundancy.

### Test Modes Available

#### 1. Basic Demo Mode
```bash
python comprehensive_test.py --mode demo
```
- Simple workflow demonstration
- Basic functionality validation
- Perfect for quick verification

#### 2. Comprehensive Mode
```bash
python comprehensive_test.py --mode comprehensive
```
- Complete endpoint testing
- Error scenario validation
- Performance metrics
- Edge case testing

#### 3. AI Agent Scenarios
```bash
python comprehensive_test.py --mode scenarios
```
- **Network Monitoring Agent**: Health monitoring simulation
- **Incident Response Agent**: Multi-issue response testing
- **Automated Testing Agent**: Systematic port testing
- **Health Checking Agent**: State transition validation

#### 4. Full Test Suite (Default)
```bash
python comprehensive_test.py
# or
python comprehensive_test.py --mode all
```

### Advanced Test Options

```bash
# Custom server URL
python comprehensive_test.py --url http://localhost:8080/api

# Disable colored output
python comprehensive_test.py --no-color

# Custom timeout (default: 10s)
python comprehensive_test.py --timeout 30

# Help and options
python comprehensive_test.py --help
```

### Test Categories Covered

1. **Query Endpoints** - All GET operations (status, topology, issues, ports)
2. **Simulation Endpoints** - All POST simulation operations with various parameters
3. **Management Endpoints** - Reset and utility operations
4. **Edge Cases** - Invalid parameters, boundary conditions
5. **Error Scenarios** - Malformed requests, invalid JSON, 404s
6. **AI Agent Scenarios** - Real-world AI usage patterns

### Sample Test Output

```
🚀 COMPREHENSIVE API ENDPOINT TEST SUITE
======================================================================
🎯 Target: http://localhost:5000/api
🕐 Started: 2025-09-23 18:45:00

🔍 TESTING QUERY ENDPOINTS
======================================================================
🧪 Test: Get network status
📍 GET /network/status
✅ SUCCESS: Network status retrieved
📈 Network: 24/24 active, 0 faulty
🏥 Health: HEALTHY

📊 COMPREHENSIVE TEST REPORT
======================================================================
📈 Total Tests: 25
✅ Passed: 25 (100.0%)
❌ Failed: 0
⏱️  Total Time: 3.45s
⚡ Avg Response Time: 0.012s

🎉 EXCELLENT: All tests passed! API is working perfectly.
```

### Integration with CI/CD

The test suite returns appropriate exit codes for automation:
- **Exit 0**: All tests passed
- **Exit 1**: Some tests failed or errors occurred

```bash
# In CI/CD pipeline
python comprehensive_test.py --no-color
if [ $? -eq 0 ]; then
    echo "✅ All tests passed"
else
    echo "❌ Tests failed"
    exit 1
fi
```

## 🔧 Advanced Configuration

### Custom Simulation Types
The tool is fully extensible. To add new simulation types:

1. **Add endpoint in app.py**:
```python
@app.route('/api/network/simulate/custom-issue', methods=['POST'])
def simulate_custom_issue():
    # Implementation here
    pass
```

2. **Update web interface** in `public/index.html`
3. **Add to AI agent schemas** for framework integration

### Error Handling
All endpoints include comprehensive error handling:
```json
{
  "success": false,
  "message": "Error description",
  "error": "Detailed error information"
}
```

### Logging and Debugging
- **Console Logging**: Real-time debug information
- **Timestamps**: All events include precise timestamps
- **Issue Tracking**: Unique IDs for all network issues
- **State Persistence**: In-memory state maintained across requests

## 📊 Network Health States

- **HEALTHY**: All ports operational (0 issues)
- **DEGRADED**: Some issues present (1-2 issues) 
- **CRITICAL**: Multiple serious issues (3+ issues)

## 🔐 Security & Best Practices

### For Development
- Tool designed for development, testing, and simulation
- No authentication required for local development
- CORS enabled for web interface access

### For Production (Recommendations)
- Add proper authentication and authorization
- Implement rate limiting to prevent abuse
- Use HTTPS for secure communication
- Add input validation and sanitization
- Consider database persistence instead of in-memory storage

### AI Agent Best Practices
1. **Always check network status first** before making changes
2. **Use specific targeting** when testing particular scenarios
3. **Monitor issues after simulations** to understand impact
4. **Reset network state** between test sequences
5. **Handle errors gracefully** and retry if needed
6. **Respect rate limits** - avoid rapid successive calls

## 🚀 Getting Started Examples

### Basic Health Check
```bash
curl http://localhost:5000/api/network/status
```

### Simulate Specific Issue
```bash
curl -X POST http://localhost:5000/api/network/simulate/cable-cut \
  -H "Content-Type: application/json" \
  -d '{"switchId": "switch-0", "portNumber": 1}'
```

### Query All Issues
```bash
curl http://localhost:5000/api/network/issues?resolved=false
```

### Reset Environment
```bash
curl -X POST http://localhost:5000/api/network/reset
```

## 🎉 Success Indicators

✅ **RESTful API** with comprehensive documentation  
✅ **Interactive web interface** with real-time updates  
✅ **AI-ready integration** with example schemas  
✅ **Multiple simulation scenarios** (cables, SFP, traffic)  
✅ **State management** and issue tracking  
✅ **Production-ready codebase** with error handling  
✅ **Cross-platform compatibility** (Python-based)  
✅ **Zero external dependencies** for core functionality  

## 📝 License

MIT License - Feel free to modify and distribute as needed.

---

**🚀 Your AI Agent Network Simulation Tool is ready to use!** 🤖

This comprehensive tool provides everything needed for AI agents to interact with network simulation scenarios, making it ideal for testing incident response systems, training monitoring agents, and validating network management automation.:
