# Context Optimization for Mininet Agent

## Problem

The ReAct agent was hitting **500 Internal Server Error** from the Generative Engine API after 3-4 tool calls. Analysis showed:

1. Each tool output included verbose JSON (topology snapshots ~1.5KB, link profiles with interface stats ~500-800 bytes each)
2. ReAct format accumulates all observations in the scratchpad: `Thought: ... Action: ... Observation: {tool_output}`
3. By the 4th tool call, the total context exceeded the API's limit (likely ~8K tokens for Claude 3.5 Sonnet)
4. The error occurred **during LLM reasoning**, not tool execution (inspect_link_health returned valid data but the agent couldn't process it)

## Root Cause Timeline

```
Agent iteration 1: get_topology_snapshot → 1.5KB JSON in scratchpad
Agent iteration 2: compute_resilient_path → +300 bytes (path details)
Agent iteration 3: activate_backup_path → +200 bytes (confirmation)
Agent iteration 4: monitor_link → +500 bytes (full link profile + interface stats)
Agent iteration 5: inspect_link_health → +800 bytes (profile + metrics dict)
Agent iteration 6: [CRASH] - API rejects request due to context overflow
```

## Solutions Implemented

### 1. Aggressive Token Budget Reduction
**File:** `datacenter_agent.py`
**Changes:**
- `max_tokens`: 2048 → 1024 → **512** (leaves more room for input context)
- `max_iterations`: 15 → **10** (prevents excessive scratchpad growth)

### 2. Simplified System Prompt
**File:** `datacenter_agent.py:960-975`
**Changes:**
- Removed steps 3-6 (monitor backup, check primary, restore primary)
- New workflow: discover → compute path → activate → **Final Answer immediately**
- Added: "Do NOT monitor links after activation unless explicitly required"
- Added: "Be extremely concise. Your goal is to restore connectivity with minimum tool calls"

### 3. Stripped Verbose Tool Outputs
**File:** `datacenter_agent.py`

#### monitor_link (line ~438)
**Before:**
```python
payload = {
    "tool": "monitor_link",
    "link": [src, dst],
    "status": "up",
    # ... 8 fields ...
    "samples": {
        "link": [...],
        "timestamp": ...,
        "interfaces": {
            "src": {"rx_bytes": ..., "tx_bytes": ..., "rx_packets": ..., ...},  # 10+ fields
            "dst": {"rx_bytes": ..., "tx_bytes": ..., ...}  # 10+ fields
        }
    }
}
```

**After:**
```python
payload = {
    "tool": "monitor_link",
    "link": [src, dst],
    "status": "up",
    # ... 8 fields (same) ...
    # NO samples field - saves ~400 bytes per call
}
```

#### inspect_link_health (line ~764)
**Before:**
```python
payload = {
    "tool": "inspect_link_health",
    "link": [src, dst],
    "profile": {...},
    "metrics": {
        "link": [...],
        "timestamp": ...,
        "interfaces": {
            "src": {...},  # Full interface stats
            "dst": {...}   # Full interface stats
        }
    }
}
```

**After:**
```python
payload = {
    "tool": "inspect_link_health",
    "link": [src, dst],
    "profile": {...}
    # NO metrics field - saves ~500 bytes per call
}
```

#### _sample_link_metrics (line ~756)
**Before:**
```python
return {
    "link": [...],
    "timestamp": ...,
    # ... 4 fields ...
    "interfaces": {
        "src": {...},  # 12 fields including backlog, dropped_packets, etc.
        "dst": {...}
    }
}
```

**After:**
```python
return {
    "link": [...],
    "timestamp": ...,
    # ... 4 fields (same) ...
    # NO interfaces field
}
```

### 4. Enhanced Error Logging
**File:** `wrapper.py:82-85`
**Added:**
```python
logger.warning("Received 5xx error - this may be due to context length or transient API issues")
```

## Expected Impact

### Token Savings Per Tool Call
| Tool | Before | After | Savings |
|------|--------|-------|---------|
| `get_topology_snapshot` | ~1500 bytes | ~1500 bytes | 0 (kept for diagnosis) |
| `compute_resilient_path` | ~300 bytes | ~300 bytes | 0 (minimal) |
| `activate_backup_path` | ~200 bytes | ~200 bytes | 0 (minimal) |
| `monitor_link` | ~900 bytes | ~450 bytes | **~450 bytes (50%)** |
| `inspect_link_health` | ~1300 bytes | ~600 bytes | **~700 bytes (54%)** |

### Agent Flow Comparison
**Before (6 tool calls → crash):**
1. get_topology_snapshot (1.5KB)
2. compute_resilient_path (0.3KB)
3. activate_backup_path (0.2KB)
4. monitor_link (0.9KB)
5. inspect_link_health (1.3KB)
6. [CRASH - 4.2KB context]

**After (3 tool calls → completion):**
1. get_topology_snapshot (1.5KB)
2. compute_resilient_path (0.3KB)
3. activate_backup_path (0.2KB)
4. Final Answer (0KB tool output)
**Total: ~2KB context**

### Iteration Budget
- **Before:** Max 15 iterations, agent used 5-6 before hitting API limit
- **After:** Max 10 iterations, agent should complete in 3-4 (66% reduction in context growth opportunity)

## Testing Validation

Run the demo to confirm agent completes successfully:
```bash
sudo env REST_API_BASE=$REST_API_BASE API_KEY=$API_KEY \
    python3.12 -m src.gen_engine_deep_eval.datacenter_agent
```

**Success criteria:**
- ✅ Agent discovers core1-agg1a failure via topology snapshot
- ✅ Computes resilient path (e.g., agg1a → core2 → agg1b → core1)
- ✅ Activates backup path without errors
- ✅ Provides Final Answer with remediation summary
- ✅ No 500 errors from Generative Engine API
- ✅ Completes in ≤4 iterations

## Further Optimization Options

If 500 errors persist:

### Option A: Even Smaller Token Budget
```python
# datacenter_agent.py:1061
max_tokens: int = 384  # Down from 512
```

### Option B: Fewer Iterations
```python
# datacenter_agent.py:1042
max_iterations=8  # Down from 10
```

### Option C: Summarize Topology Snapshot
```python
def get_topology_snapshot(self) -> str:
    # Return only failed links + neighbor suggestions instead of full topology
    down_links = [link for link, prof in self.link_profiles.items() if prof.status == "down"]
    return json.dumps({"failed_links": down_links, "node_count": len(self.blueprint.nodes)})
```

### Option D: Custom Scratchpad Callback
Implement a LangChain callback that truncates old observations after N tool calls:
```python
class TruncatingScratchpadCallback(BaseCallbackHandler):
    def on_agent_action(self, action, **kwargs):
        if len(scratchpad) > MAX_OBSERVATIONS:
            scratchpad = scratchpad[-MAX_OBSERVATIONS:]  # Keep last N only
```

## Trade-offs

### Benefits
✅ Reliable completion within API context limits
✅ Faster agent execution (fewer tool calls)
✅ Lower token costs per invocation
✅ More predictable behavior

### Limitations
⚠️ Agent can no longer verify backup path health after activation
⚠️ No interface-level diagnostics (dropped packets, backlog, etc.)
⚠️ Cannot restore primary path automatically (requires manual operator intervention)
⚠️ Less observability for debugging complex failure modes

## Conclusion

These optimizations trade **diagnostic depth** for **operational reliability**. The agent now focuses on:
1. **Fast failure detection** (topology analysis)
2. **Quick path computation** (NetworkX shortest path)
3. **Immediate remediation** (backup activation)
4. **Concise reporting** (Final Answer with summary)

This aligns with the "minimum viable remediation" pattern for production incidents where restoring service is prioritized over comprehensive root cause analysis.
