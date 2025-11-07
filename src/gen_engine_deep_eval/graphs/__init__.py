"""LangGraph-based agent implementations for Observer and DataCenter agents.

This module provides modern state machine architectures using LangGraph,
replacing the legacy LangChain ReAct agent pattern while maintaining full
compatibility with the GenerativeEngineLLM wrapper.
"""

# Make imports optional to support environments without full dependencies
try:
    from .observer_graph import build_observer_graph
    from .datacenter_graph import build_datacenter_graph
    from .state_schemas import ObserverState, DataCenterState
    
    __all__ = [
        "build_observer_graph",
        "ObserverState",
        "build_datacenter_graph",
        "DataCenterState",
    ]
except ImportError as e:
    # LangGraph dependencies not installed
    import warnings
    warnings.warn(
        f"LangGraph agents require additional dependencies: {e}. "
        "Install with: pip install langgraph langgraph-checkpoint langchain-core"
    )
    __all__ = []

