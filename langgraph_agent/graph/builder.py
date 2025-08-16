# langgraph_agent/graph/builder.py
"""Simplified LangGraph agent builder using modular components"""

from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage


# Define the state type for proper typing
class GraphState(TypedDict, total=False):
    """State definition for the graph"""
    chat_history: List[BaseMessage]
    all_fetched_drivers: List[Dict[str, Any]]
    filtered_drivers: List[Dict[str, Any]]
    current_display_index: int
    current_page: int
    fetch_count: int
    applied_filters: Dict[str, Any]
    trip_id: Optional[str]
    pickup_location: Optional[str]
    drop_location: Optional[str]
    trip_type: Optional[str]
    start_date: Optional[str]
    end_date: Optional[str]
    customer_id: Optional[str]
    customer_name: Optional[str]
    customer_phone: Optional[str]
    customer_profile: Optional[str]
    last_bot_response: Optional[str]
    tool_calls: List[Dict[str, Any]]


# Import and wrap node functions
from langgraph_agent.graph import nodes


def agent_node_wrapper(state: GraphState) -> Dict[str, Any]:
    """Agent node wrapper with proper typing"""
    # Convert TypedDict to regular dict for the node function
    return nodes.agent_node(dict(state))


def tool_executor_node_wrapper(state: GraphState) -> Dict[str, Any]:
    """Tool executor node wrapper with proper typing"""
    # Convert TypedDict to regular dict for the node function
    return nodes.tool_executor_node(dict(state))


def route_after_agent(state: GraphState) -> str:
    """Router to decide next step after agent"""
    if state.get("tool_calls"):
        return "action"
    else:
        return END


def create_graph():
    """Create the LangGraph workflow"""
    # Use GraphState for proper typing
    workflow = StateGraph(GraphState)

    # Add nodes with wrapped functions
    workflow.add_node("agent", agent_node_wrapper)
    workflow.add_node("action", tool_executor_node_wrapper)

    # Set entry point
    workflow.set_entry_point("agent")

    # Add conditional edges
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {"action": "action", END: END}
    )

    # After tools, go back to agent
    workflow.add_edge("action", "agent")

    return workflow.compile()


# Create the app
app = create_graph()
