"""Enhanced interactive LangGraph workflow for datacenter remediation agent.

This module extends the GUI datacenter graph with:
1. Natural language conversation capabilities
2. Interactive fix proposal and refinement
3. Multi-turn dialogue for user questions
4. Alternative suggestion when auto-fixes unavailable
5. Post-fix verification and follow-up assistance
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal

from langchain_core.language_models import BaseLanguageModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from loguru import logger

from .gui_datacenter_graph import (
    GUIDatacenterState,
    analyze_failures_node,
    build_network_graph_node,
    classify_fixes_node,
    execute_fixes_node,
    fetch_topology_node,
    find_alternate_paths_node,
    llm_analysis_node,
    route_by_failures,
)


class InteractiveDatacenterState(GUIDatacenterState, total=False):
    """Extended state for interactive agent with conversational capabilities."""
    
    # Conversation management
    conversation_history: List[Dict[str, str]]
    user_input: str | None
    agent_response: str
    awaiting_user_input: bool
    conversation_phase: Literal[
        "initial_analysis",
        "proposing_fixes",
        "discussing_alternatives",
        "executing_fixes",
        "post_fix_verification",
        "complete",
    ]
    
    # Enhanced interaction
    alternative_suggestions: List[Dict[str, Any]]
    user_questions: List[str]
    clarifications_needed: List[str]


def build_interactive_datacenter_graph(
    llm: BaseLanguageModel, enable_continuous_chat: bool = True
) -> StateGraph:
    """Build enhanced interactive LangGraph workflow.
    
    Args:
        llm: Language model for reasoning and conversation
        enable_continuous_chat: If True, enable multi-turn conversation after initial analysis
    
    Returns:
        Compiled StateGraph with conversational capabilities
    """
    workflow = StateGraph(InteractiveDatacenterState)
    
    # Define nodes
    workflow.add_node("fetch_topology", fetch_topology_node)
    workflow.add_node("analyze_failures", analyze_failures_node)
    workflow.add_node("build_graph", build_network_graph_node)
    workflow.add_node("find_paths", find_alternate_paths_node)
    workflow.add_node("llm_analysis", lambda state: llm_analysis_node(state, llm))
    workflow.add_node("generate_interactive_runbook", lambda state: generate_interactive_runbook_node(state, llm))
    workflow.add_node("classify_fixes", lambda state: classify_fixes_node(state, llm))
    workflow.add_node("propose_fixes_conversational", lambda state: propose_fixes_conversational_node(state, llm))
    workflow.add_node("handle_user_response", lambda state: handle_user_response_node(state, llm))
    workflow.add_node("suggest_alternatives", lambda state: suggest_alternatives_node(state, llm))
    workflow.add_node("execute_fixes", execute_fixes_node)
    workflow.add_node("post_fix_chat", lambda state: post_fix_chat_node(state, llm))
    
    # Define edges
    workflow.add_edge(START, "fetch_topology")
    workflow.add_edge("fetch_topology", "analyze_failures")
    
    # Conditional routing based on failure count
    workflow.add_conditional_edges(
        "analyze_failures",
        route_by_failures,
        {
            "no_failures": END,
            "has_failures": "build_graph",
        },
    )
    
    workflow.add_edge("build_graph", "find_paths")
    workflow.add_edge("find_paths", "llm_analysis")
    workflow.add_edge("llm_analysis", "generate_interactive_runbook")
    workflow.add_edge("generate_interactive_runbook", "classify_fixes")
    workflow.add_edge("classify_fixes", "propose_fixes_conversational")
    
    # Conversational routing
    workflow.add_conditional_edges(
        "propose_fixes_conversational",
        route_conversation,
        {
            "await_user_input": "handle_user_response",
            "no_fixes_suggest_alternatives": "suggest_alternatives",
            "end": END,
        },
    )
    
    workflow.add_conditional_edges(
        "handle_user_response",
        route_after_user_response,
        {
            "execute_fixes": "execute_fixes",
            "more_questions": "propose_fixes_conversational",
            "alternatives": "suggest_alternatives",
            "end": END,
        },
    )
    
    workflow.add_conditional_edges(
        "suggest_alternatives",
        route_after_alternatives,
        {
            "await_user_input": "handle_user_response",
            "end": END,
        },
    )
    
    if enable_continuous_chat:
        workflow.add_edge("execute_fixes", "post_fix_chat")
        workflow.add_conditional_edges(
            "post_fix_chat",
            route_post_fix,
            {
                "continue_chat": "handle_user_response",
                "end": END,
            },
        )
    else:
        workflow.add_edge("execute_fixes", END)
    
    return workflow.compile()


def generate_interactive_runbook_node(
    state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> InteractiveDatacenterState:
    """Generate runbook with conversational framing."""
    logger.info("Generating interactive runbook")
    
    try:
        blueprint = state["blueprint"]
        failures = state["failures"]
        remediation_plan = state["remediation_plan"]
        llm_analysis = state.get("llm_analysis", "")
        
        # Build conversational runbook
        sections = []
        
        sections.append("🤖 **NETWORK ANALYSIS COMPLETE**\n")
        sections.append(f"I've analyzed your datacenter topology ({blueprint.name}) and identified **{len(failures)} issue(s)**.\n")
        
        # Summarize failures
        sections.append("**Issues Found:**")
        for i, failure in enumerate(failures, 1):
            sections.append(f"{i}. {failure['type']} at {failure.get('switch', failure.get('link', 'unknown'))} ({failure['severity']})")
        
        sections.append("\n**My Analysis:**")
        sections.append(llm_analysis[:500] + "..." if len(llm_analysis) > 500 else llm_analysis)
        
        runbook = "\n".join(sections)
        state["runbook"] = runbook
        state["conversation_phase"] = "initial_analysis"
        
        # Initialize conversation history
        if "conversation_history" not in state:
            state["conversation_history"] = []
        
        state["conversation_history"].append({
            "role": "assistant",
            "content": runbook,
        })
        
        logger.info("Interactive runbook generated")
        
    except Exception as e:
        logger.error(f"Failed to generate interactive runbook: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)
    
    return state


def propose_fixes_conversational_node(
    state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> InteractiveDatacenterState:
    """Propose fixes with natural language conversation."""
    logger.info("Generating conversational fix proposal")
    
    try:
        auto_fixable = state.get("auto_fixable_actions", [])
        manual = state.get("manual_actions", [])
        llm_reasoning = state.get("llm_classification_reasoning", "")
        
        if not auto_fixable and not manual:
            # Edge case: no actions at all
            state["agent_response"] = (
                "\n⚠️ I couldn't determine any specific remediation actions. "
                "This might require deeper investigation. Would you like me to:\n"
                "1. Provide more detailed diagnostics\n"
                "2. Suggest manual troubleshooting steps\n"
                "3. Focus on a specific failure type"
            )
            state["awaiting_user_input"] = True
            state["conversation_phase"] = "discussing_alternatives"
            state["status"] = "awaiting_approval"
            return state
        
        if not auto_fixable:
            # No auto-fixes available - trigger alternative suggestions
            state["conversation_phase"] = "discussing_alternatives"
            state["awaiting_user_input"] = True
            return state
        
        # Build conversational proposal
        proposal_lines = []
        proposal_lines.append("\n🔧 **REMEDIATION PROPOSAL**\n")
        
        # Agent's reasoning
        if llm_reasoning:
            proposal_lines.append("**My Reasoning:**")
            reasoning_preview = llm_reasoning[:300] + "..." if len(llm_reasoning) > 300 else llm_reasoning
            proposal_lines.append(reasoning_preview)
            proposal_lines.append("")
        
        proposal_lines.append(f"I've identified **{len(auto_fixable)} fix(es)** that I can apply automatically:")
        proposal_lines.append("")
        
        for i, action in enumerate(auto_fixable, 1):
            proposal_lines.append(f"**{i}. {action['description']}**")
            proposal_lines.append(f"   • Risk Level: {action['risk']}")
            
            if action.get("best_path"):
                path_info = action["best_path"]
                path_str = " → ".join(path_info.get("path", []))
                proposal_lines.append(f"   • Path: {path_str}")
                proposal_lines.append(
                    f"   • Capacity: {path_info['capacity_gbps']:.1f} Gbps, "
                    f"Latency: +{path_info['estimated_latency_ms']}ms"
                )
            
            if action.get("llm_reasoning"):
                proposal_lines.append(f"   • Why: {action['llm_reasoning'][:100]}...")
            
            proposal_lines.append("")
        
        if manual:
            proposal_lines.append(f"\nAdditionally, **{len(manual)} issue(s)** require manual intervention:")
            for i, action in enumerate(manual, 1):
                proposal_lines.append(f"{i}. {action['description']}")
                proposal_lines.append(f"   Reason: {action['reason'][:100]}...")
            proposal_lines.append("")
        
        proposal_lines.append("\n**What would you like to do?**")
        proposal_lines.append("• Type 'yes' or 'apply' to execute these fixes")
        proposal_lines.append("• Type 'explain' to learn more about a specific fix")
        proposal_lines.append("• Type 'alternatives' to see other options")
        proposal_lines.append("• Ask me anything about the failures or proposed fixes")
        
        proposal_text = "\n".join(proposal_lines)
        
        state["agent_response"] = proposal_text
        state["awaiting_user_input"] = True
        state["conversation_phase"] = "proposing_fixes"
        state["status"] = "awaiting_approval"
        
        state["conversation_history"].append({
            "role": "assistant",
            "content": proposal_text,
        })
        
        logger.info("Conversational fix proposal generated")
        
    except Exception as e:
        logger.error(f"Failed to generate conversational proposal: {e}")
        state["status"] = "error"
        state["error_message"] = str(e)
    
    return state


def handle_user_response_node(
    state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> InteractiveDatacenterState:
    """Process user's natural language response."""
    logger.info("Processing user response")
    
    try:
        user_input = state.get("user_input", "").strip().lower()
        
        if not user_input:
            state["agent_response"] = "I didn't receive any input. Could you please respond?"
            state["awaiting_user_input"] = True
            return state
        
        # Add to conversation history
        state["conversation_history"].append({
            "role": "user",
            "content": user_input,
        })
        
        # Parse intent with LLM
        intent = _parse_user_intent(user_input, state, llm)
        
        if intent["type"] == "approve_fixes":
            state["user_approved_fixes"] = True
            state["awaiting_user_input"] = False
            state["conversation_phase"] = "executing_fixes"
            state["agent_response"] = "✅ Understood. Applying fixes now..."
            
        elif intent["type"] == "reject_fixes":
            state["user_approved_fixes"] = False
            state["awaiting_user_input"] = False
            state["agent_response"] = "Understood. No changes will be made. Let me know if you'd like to discuss alternatives."
            
        elif intent["type"] == "request_explanation":
            # Generate explanation
            explanation = _generate_explanation(intent.get("topic"), state, llm)
            state["agent_response"] = explanation
            state["awaiting_user_input"] = True
            
        elif intent["type"] == "request_alternatives":
            state["conversation_phase"] = "discussing_alternatives"
            state["awaiting_user_input"] = True
            
        elif intent["type"] == "ask_question":
            # Answer general question about network/failures
            answer = _answer_network_question(user_input, state, llm)
            state["agent_response"] = answer
            state["awaiting_user_input"] = True
            
        else:
            # Unclear intent
            state["agent_response"] = (
                "I'm not sure I understood. Could you:\n"
                "• Say 'yes' to apply the fixes\n"
                "• Say 'no' to cancel\n"
                "• Ask me a specific question\n"
                "• Request 'alternatives'"
            )
            state["awaiting_user_input"] = True
        
        state["conversation_history"].append({
            "role": "assistant",
            "content": state["agent_response"],
        })
        
    except Exception as e:
        logger.error(f"Failed to handle user response: {e}")
        state["agent_response"] = f"Sorry, I encountered an error: {e}"
        state["awaiting_user_input"] = True
    
    return state


def suggest_alternatives_node(
    state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> InteractiveDatacenterState:
    """Suggest manual alternatives when auto-fixes are unavailable."""
    logger.info("Generating alternative suggestions")
    
    try:
        manual_actions = state.get("manual_actions", [])
        remediation_plan = state.get("remediation_plan", [])
        blueprint = state.get("blueprint")
        
        # Use LLM to generate helpful manual guidance
        prompt = f"""You are a helpful network engineer assistant. The user has network failures that cannot be fixed automatically.
        
Failures requiring manual intervention:
{json.dumps(manual_actions[:5], indent=2)}

Network context:
- Topology: {blueprint.name if blueprint else 'unknown'}
- Total failures: {len(state.get('failures', []))}

Generate a helpful, conversational response that:
1. Explains WHY these issues need manual intervention
2. Provides step-by-step guidance for each issue
3. Suggests tools/commands the user could run
4. Offers to help with specific diagnostic steps
5. Maintains an encouraging, supportive tone

Be concise but thorough. Use bullet points and clear formatting.
"""
        
        response = llm.invoke([HumanMessage(content=prompt)])
        alternatives_text = response.content if hasattr(response, "content") else str(response)
        
        # Frame it conversationally
        suggestion_lines = []
        suggestion_lines.append("\n🔍 **MANUAL REMEDIATION GUIDANCE**\n")
        suggestion_lines.append(alternatives_text)
        suggestion_lines.append("\n**How can I help you?**")
        suggestion_lines.append("• Ask me about a specific failure")
        suggestion_lines.append("• Request diagnostic commands")
        suggestion_lines.append("• Discuss troubleshooting approach")
        suggestion_lines.append("• Get vendor-specific guidance")
        
        suggestion_response = "\n".join(suggestion_lines)
        
        state["agent_response"] = suggestion_response
        state["alternative_suggestions"] = manual_actions
        state["awaiting_user_input"] = True
        state["conversation_phase"] = "discussing_alternatives"
        
        state["conversation_history"].append({
            "role": "assistant",
            "content": suggestion_response,
        })
        
        logger.info("Alternative suggestions generated")
        
    except Exception as e:
        logger.error(f"Failed to generate alternatives: {e}")
        state["agent_response"] = (
            "I encountered an error generating alternatives. "
            "The issues require manual intervention - would you like me to provide more details?"
        )
        state["awaiting_user_input"] = True
    
    return state


def post_fix_chat_node(
    state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> InteractiveDatacenterState:
    """Offer post-fix assistance and verification."""
    logger.info("Starting post-fix conversation")
    
    try:
        executed_fixes = state.get("executed_fixes", [])
        
        success_count = sum(1 for f in executed_fixes if f.get("status") == "success")
        total_count = len(executed_fixes)
        
        post_fix_message = f"""
✅ **FIXES APPLIED**

Successfully executed {success_count}/{total_count} fixes.

**What's next?**
• Type 'verify' to check network status
• Type 'status' to see current link states
• Ask me about any remaining issues
• Request additional diagnostics
• Type 'done' when you're satisfied

How can I help you verify the remediation?
"""
        
        state["agent_response"] = post_fix_message
        state["awaiting_user_input"] = True
        state["conversation_phase"] = "post_fix_verification"
        
        state["conversation_history"].append({
            "role": "assistant",
            "content": post_fix_message,
        })
        
    except Exception as e:
        logger.error(f"Failed to generate post-fix chat: {e}")
        state["agent_response"] = "Fixes applied. Let me know if you need anything else."
        state["awaiting_user_input"] = False
    
    return state


# Routing functions

def route_conversation(state: InteractiveDatacenterState) -> str:
    """Route based on fix availability and conversation phase."""
    auto_fixable = state.get("auto_fixable_actions", [])
    
    if not auto_fixable:
        return "no_fixes_suggest_alternatives"
    
    if state.get("awaiting_user_input"):
        return "await_user_input"
    
    return "end"


def route_after_user_response(state: InteractiveDatacenterState) -> str:
    """Route based on user's response intent."""
    if state.get("user_approved_fixes"):
        return "execute_fixes"
    
    phase = state.get("conversation_phase")
    
    if phase == "discussing_alternatives":
        return "alternatives"
    
    if state.get("awaiting_user_input"):
        return "more_questions"
    
    return "end"


def route_after_alternatives(state: InteractiveDatacenterState) -> str:
    """Route after presenting alternatives."""
    if state.get("awaiting_user_input"):
        return "await_user_input"
    return "end"


def route_post_fix(state: InteractiveDatacenterState) -> str:
    """Route after fix execution."""
    user_input = state.get("user_input", "").strip().lower()
    
    if user_input and "done" not in user_input and "exit" not in user_input:
        return "continue_chat"
    
    if state.get("awaiting_user_input"):
        return "continue_chat"
    
    return "end"


# Helper functions

def _parse_user_intent(
    user_input: str, state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> Dict[str, Any]:
    """Parse user's intent from natural language."""
    
    # Simple rule-based parsing for common intents
    user_lower = user_input.lower()
    
    if any(word in user_lower for word in ["yes", "apply", "go ahead", "proceed", "do it"]):
        return {"type": "approve_fixes"}
    
    if any(word in user_lower for word in ["no", "cancel", "stop", "don't"]):
        return {"type": "reject_fixes"}
    
    if any(word in user_lower for word in ["explain", "why", "how", "tell me more"]):
        return {"type": "request_explanation", "topic": user_input}
    
    if any(word in user_lower for word in ["alternative", "other options", "different"]):
        return {"type": "request_alternatives"}
    
    # Use LLM for complex queries
    prompt = f"""Parse this user input into an intent. User said: "{user_input}"

Context: User is responding to network remediation proposals.

Possible intents:
- approve_fixes: User wants to apply proposed fixes
- reject_fixes: User doesn't want fixes applied
- request_explanation: User wants more info about something
- request_alternatives: User wants other options
- ask_question: User has a general question

Respond with JSON: {{"type": "intent_name", "details": "any relevant context"}}
"""
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content if hasattr(response, "content") else str(response)
        
        # Extract JSON
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(0))
    except Exception as e:
        logger.error(f"Failed to parse intent with LLM: {e}")
    
    # Default to question
    return {"type": "ask_question"}


def _generate_explanation(
    topic: str, state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> str:
    """Generate detailed explanation about a topic."""
    
    auto_fixable = state.get("auto_fixable_actions", [])
    remediation_plan = state.get("remediation_plan", [])
    
    prompt = f"""User asked: "{topic}"

Provide a clear, technical explanation in the context of these network remediation actions:
{json.dumps(auto_fixable[:3], indent=2)}

Explain:
- What the fix does technically
- Why it's needed
- What the risk level means
- What could go wrong (if anything)

Be concise but thorough. Use analogies if helpful.
"""
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"Failed to generate explanation: {e}")
        return "I encountered an error generating that explanation. Could you rephrase your question?"


def _answer_network_question(
    question: str, state: InteractiveDatacenterState, llm: BaseLanguageModel
) -> str:
    """Answer general questions about the network state."""
    
    failures = state.get("failures", [])
    blueprint = state.get("blueprint")
    remediation_plan = state.get("remediation_plan", [])
    
    context = f"""Network topology: {blueprint.name if blueprint else 'unknown'}
Failures: {json.dumps(failures[:5], indent=2)}
Remediation plan: {json.dumps(remediation_plan[:3], indent=2)}
"""
    
    prompt = f"""User question: "{question}"

Network context:
{context}

Provide a helpful, accurate answer. Be conversational but technical.
If you don't have enough information, say so and suggest what else could be checked.
"""
    
    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        return response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.error(f"Failed to answer question: {e}")
        return "I'm having trouble processing that question. Could you try rephrasing it?"
