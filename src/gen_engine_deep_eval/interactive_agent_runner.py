"""Interactive runner for conversational datacenter agent.

This module provides a command-line interface for natural language interaction
with the datacenter remediation agent. It supports:
- Multi-turn conversations
- Natural language queries
- Interactive fix approval and refinement
- Post-fix verification assistance
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Dict

from loguru import logger

from .graphs.interactive_datacenter_graph import (
    InteractiveDatacenterState,
    build_interactive_datacenter_graph,
)
from .wrapper import GenerativeEngineLLM


def print_banner():
    """Print welcome banner."""
    print("\n" + "="*80)
    print("🤖 INTERACTIVE DATACENTER AGENT")
    print("="*80)
    print("An AI-powered network remediation assistant that can:")
    print("  • Analyze topology failures")
    print("  • Suggest automated fixes")
    print("  • Provide manual troubleshooting guidance")
    print("  • Answer your questions in natural language")
    print("\nType 'help' for commands, 'exit' to quit")
    print("="*80 + "\n")


def print_help():
    """Print help text."""
    help_text = """
📖 AVAILABLE COMMANDS:
  
  During Analysis:
  • 'yes' / 'apply'      - Apply suggested automated fixes
  • 'no' / 'skip'        - Skip automated fixes
  • 'explain <topic>'    - Get detailed explanation
  • 'alternatives'       - See alternative remediation options
  • 'status'             - Check current network status
  
  After Fixes:
  • 'verify'             - Verify fix results
  • 'status'             - Check link states
  • 'done'               - Exit conversation
  
  General:
  • 'help'               - Show this help
  • 'exit' / 'quit'      - Exit the agent
  
  You can also ask natural language questions like:
  • "Why did this link fail?"
  • "What's the risk of applying fix #2?"
  • "Show me the alternate paths"
  • "What happens if the fix doesn't work?"
"""
    print(help_text)


def run_interactive_session(
    gui_url: str = "http://localhost:5000",
    user_query: str | None = None,
    max_turns: int = 20,
) -> None:
    """Run interactive conversational session with datacenter agent.
    
    Args:
        gui_url: Base URL of GUI simulation tool
        user_query: Optional initial query
        max_turns: Maximum conversation turns before exit
    """
    
    # Get API credentials from environment
    api_base = os.getenv("REST_API_BASE") or os.getenv("GEN_ENGINE_API_BASE")
    api_key = os.getenv("API_KEY") or os.getenv("GEN_ENGINE_API_KEY")
    
    if not api_base or not api_key:
        logger.error("API credentials not found in environment variables")
        print("\n❌ ERROR: API credentials required")
        print("\nPlease set environment variables:")
        print("  export REST_API_BASE='https://api.generative.engine.capgemini.com/'")
        print("  export API_KEY='your-api-key'")
        return
    
    # Initialize LLM
    llm = GenerativeEngineLLM(
        api_base=api_base,
        api_key=api_key,
        model="anthropic.claude-3-5-sonnet-20240620-v1:0",
        max_tokens=4096,
        temperature=0.1,  # Slightly higher for more natural conversation
    )
    
    # Build interactive graph
    graph = build_interactive_datacenter_graph(llm, enable_continuous_chat=True)
    
    print_banner()
    
    # Initialize state
    initial_state: InteractiveDatacenterState = {
        "gui_url": gui_url,
        "user_query": user_query or "Analyze network topology and identify any failures requiring remediation.",
        "status": "idle",
        "conversation_history": [],
        "awaiting_user_input": False,
        "conversation_phase": "initial_analysis",
    }
    
    print(f"🔍 Connecting to topology at: {gui_url}")
    print("⏳ Analyzing network...\n")
    
    try:
        # Run initial analysis
        result = graph.invoke(initial_state)
        
        # Check for errors
        if result.get("status") == "error":
            print(f"❌ ERROR: {result.get('error_message', 'Unknown error')}")
            return
        
        # Display initial analysis
        conversation_history = result.get("conversation_history", [])
        
        # Print all agent messages from initial analysis
        for msg in conversation_history:
            if msg["role"] == "assistant":
                print(f"\n{msg['content']}\n")
        
        # Check if network is healthy
        failure_count = result.get("failure_count", 0)
        if failure_count == 0:
            print("\n✅ Network Status: HEALTHY")
            print("No failures detected. Network is operating normally.")
            return
        
        # Enter conversation loop
        turn_count = 0
        current_state = result
        
        while turn_count < max_turns:
            # Check if we're awaiting user input
            if not current_state.get("awaiting_user_input"):
                # Agent has finished, check if we should continue
                phase = current_state.get("conversation_phase")
                if phase == "complete" or phase == "executing_fixes":
                    break
                
                # Agent says something without awaiting input
                agent_response = current_state.get("agent_response")
                if agent_response:
                    print(f"\n{agent_response}\n")
                break
            
            # Get user input
            try:
                user_input = input("You: ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n\n👋 Exiting conversation. Goodbye!")
                break
            
            if not user_input:
                continue
            
            # Check for exit commands
            if user_input.lower() in ["exit", "quit", "bye"]:
                print("\n👋 Goodbye!")
                break
            
            # Check for help
            if user_input.lower() == "help":
                print_help()
                continue
            
            turn_count += 1
            
            # Update state with user input
            current_state["user_input"] = user_input
            current_state["awaiting_user_input"] = False
            
            # Process through graph
            try:
                current_state = graph.invoke(current_state)
            except Exception as e:
                logger.error(f"Error processing user input: {e}")
                print(f"\n❌ Sorry, I encountered an error: {e}")
                print("Let's try continuing...\n")
                continue
            
            # Display agent's response
            agent_response = current_state.get("agent_response")
            if agent_response:
                print(f"\n🤖 Agent: {agent_response}\n")
            
            # Check if fixes were approved and executed
            if current_state.get("user_approved_fixes") and current_state.get("executed_fixes"):
                print("\n✅ Fixes have been applied!")
                
                # Display fix results
                fix_results = current_state.get("fix_results")
                if fix_results:
                    print(fix_results)
                
                # Check if we're in post-fix chat
                if current_state.get("conversation_phase") == "post_fix_verification":
                    continue
                else:
                    break
            
            # Check if conversation should end
            if not current_state.get("awaiting_user_input"):
                phase = current_state.get("conversation_phase")
                if phase == "complete":
                    print("\n✅ Conversation complete. Have a great day!")
                    break
        
        # Final summary
        if turn_count >= max_turns:
            print(f"\n⏰ Reached maximum conversation turns ({max_turns})")
        
        print("\n" + "="*80)
        print("SESSION SUMMARY")
        print("="*80)
        print(f"Failures detected: {current_state.get('failure_count', 0)}")
        print(f"Fixes proposed: {len(current_state.get('auto_fixable_actions', []))}")
        print(f"Fixes executed: {len(current_state.get('executed_fixes', []))}")
        print(f"Conversation turns: {turn_count}")
        print("="*80 + "\n")
        
    except KeyboardInterrupt:
        print("\n\n⏸️  Conversation interrupted by user")
    except Exception as e:
        logger.error(f"Session failed: {e}")
        import traceback
        traceback.print_exc()
        print(f"\n❌ Session error: {e}")


def run_batch_mode(
    gui_url: str = "http://localhost:5000",
    user_query: str | None = None,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """Run agent in batch mode (non-interactive).
    
    Args:
        gui_url: Base URL of GUI simulation tool
        user_query: Optional query to guide analysis
        auto_approve: If True, automatically approve all fixes
    
    Returns:
        Final state dictionary with results
    """
    
    api_base = os.getenv("REST_API_BASE") or os.getenv("GEN_ENGINE_API_BASE")
    api_key = os.getenv("API_KEY") or os.getenv("GEN_ENGINE_API_KEY")
    
    if not api_base or not api_key:
        raise RuntimeError("API credentials required (REST_API_BASE and API_KEY)")
    
    llm = GenerativeEngineLLM(
        api_base=api_base,
        api_key=api_key,
        model="anthropic.claude-3-5-sonnet-20240620-v1:0",
        max_tokens=4096,
        temperature=0.05,
    )
    
    # Build graph without continuous chat for batch mode
    graph = build_interactive_datacenter_graph(llm, enable_continuous_chat=False)
    
    initial_state: InteractiveDatacenterState = {
        "gui_url": gui_url,
        "user_query": user_query or "Analyze network and remediate failures.",
        "status": "idle",
        "conversation_history": [],
        "awaiting_user_input": False,
        "user_approved_fixes": auto_approve,
    }
    
    logger.info("Running in batch mode (non-interactive)")
    result = graph.invoke(initial_state)
    
    return result


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Interactive Datacenter Agent")
    parser.add_argument(
        "--gui-url",
        default="http://localhost:5000",
        help="GUI simulation URL (default: http://localhost:5000)",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Initial query for the agent",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Run in batch mode (non-interactive)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve fixes in batch mode",
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=20,
        help="Maximum conversation turns (default: 20)",
    )
    
    args = parser.parse_args()
    
    if args.batch:
        result = run_batch_mode(
            gui_url=args.gui_url,
            user_query=args.query,
            auto_approve=args.auto_approve,
        )
        print("\n📊 BATCH RESULT:")
        print(f"Status: {result.get('status')}")
        print(f"Failures: {result.get('failure_count', 0)}")
        print(f"Auto-fixable: {len(result.get('auto_fixable_actions', []))}")
        print(f"Manual actions: {len(result.get('manual_actions', []))}")
    else:
        run_interactive_session(
            gui_url=args.gui_url,
            user_query=args.query,
            max_turns=args.max_turns,
        )
