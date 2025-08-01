# langgraph_agent/graph/builder.py
"""LangGraph agent builder"""

import json
import logging
from typing import Dict, Any, List

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage
from langchain_google_vertexai import ChatVertexAI

from langgraph_agent.graph.sys_prompt import bot_prompt
from langgraph_agent.tools.drivers_tools import (
    get_drivers_for_city,
    filter_drivers,
    get_driver_details,
    remove_filters_from_search,
)

logger = logging.getLogger(__name__)

# Tools list
tools = [
    get_drivers_for_city,
    filter_drivers,
    get_driver_details,
    remove_filters_from_search,
]

# Initialize LLM
llm = ChatVertexAI(model="gemini-2.0-flash-exp", temperature=0.1)
llm_with_tools = llm.bind_tools(tools)


def agent_node(state: dict) -> dict:
    """Agent node that processes messages and decides actions"""
    logger.info("---AGENT NODE---")

    # Build messages
    messages = [SystemMessage(content=bot_prompt)]

    # Add chat history
    chat_history = state.get("chat_history", [])
    if chat_history:
        messages.extend(chat_history)

    # Get LLM response
    try:
        ai_response = llm_with_tools.invoke(messages)

        # Update chat history
        updated_history = chat_history + [ai_response]

        # Check for tool calls
        if not ai_response.tool_calls:
            # Direct response
            logger.info("Agent provided direct response")
            return {
                **state,
                "chat_history": updated_history,
                "last_bot_response": ai_response.content,
                "tool_calls": [],
            }
        else:
            # Agent wants to call tools
            logger.info(
                f"Agent calling tools: {[tc['name'] for tc in ai_response.tool_calls]}"
            )
            return {
                **state,
                "chat_history": updated_history,
                "tool_calls": ai_response.tool_calls,
            }

    except Exception as e:
        logger.error(f"Error in agent_node: {e}")
        return {
            **state,
            "last_bot_response": "I apologize, but I encountered an issue. Please try again.",
            "tool_calls": [],
        }


def tool_executor_node(state: dict) -> dict:
    """Execute tools requested by the agent"""
    logger.info("---TOOL EXECUTOR NODE---")

    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return state

    # Map tool names to functions
    tool_map = {tool.name: tool for tool in tools}
    tool_messages = []

    # Current state copy for updates
    state_updates = dict(state)

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id")

        logger.info(f"Executing tool: {tool_name}")

        tool_to_call = tool_map.get(tool_name)
        if not tool_to_call:
            tool_messages.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' not found.",
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )
            continue

        try:
            # Execute tool
            output = tool_to_call.invoke(tool_args)

            # Update state based on tool
            if tool_name == "get_drivers_for_city":
                state_updates["drivers_with_full_details"] = output
                state_updates["filtered_drivers"] = output
                state_updates["applied_filters"] = {}
                state_updates["pickup_location"] = tool_args.get("city")
                logger.info(f"Fetched {len(output)} drivers")

            elif tool_name == "filter_drivers":
                # Get the full driver list from state
                drivers_to_filter = state_updates.get("drivers_with_full_details", [])

                # Apply filters
                new_filters = tool_args.get("filters", {})
                combined_filters = {
                    **state_updates.get("applied_filters", {}),
                    **new_filters,
                }

                # Call filter with the full driver list
                from langgraph_agent.tools.drivers_tools import (
                    filter_drivers as filter_func,
                )

                filtered_result = filter_func.invoke(
                    {"drivers": drivers_to_filter, "filters": combined_filters}
                )

                state_updates["filtered_drivers"] = filtered_result
                state_updates["applied_filters"] = combined_filters
                output = filtered_result  # Use the filtered result
                logger.info(
                    f"Applied filters: {combined_filters}, found {
                        len(filtered_result)
                    } drivers"
                )

            elif tool_name == "remove_filters_from_search":
                keys_to_remove = tool_args.get("keys_to_remove", [])
                current_filters = state_updates.get("applied_filters", {}).copy()

                if "all" in keys_to_remove:
                    state_updates["applied_filters"] = {}
                    state_updates["filtered_drivers"] = state_updates.get(
                        "drivers_with_full_details", []
                    )
                else:
                    for key in keys_to_remove:
                        current_filters.pop(key, None)
                    state_updates["applied_filters"] = current_filters

                    # Re-apply remaining filters
                    if current_filters:
                        full_list = state_updates.get("drivers_with_full_details", [])
                        filtered = filter_drivers.invoke(
                            {"drivers": full_list, "filters": current_filters}
                        )
                        state_updates["filtered_drivers"] = filtered
                    else:
                        state_updates["filtered_drivers"] = state_updates.get(
                            "drivers_with_full_details", []
                        )

            # Format output for LLM
            output_str = format_tool_output(tool_name, output)

            tool_messages.append(
                ToolMessage(content=output_str, tool_call_id=tool_id, name=tool_name)
            )

        except Exception as e:
            logger.error(f"Error executing {tool_name}: {e}")
            tool_messages.append(
                ToolMessage(
                    content=f"Error: {str(e)}", tool_call_id=tool_id, name=tool_name
                )
            )

    # Update chat history with tool results
    state_updates["chat_history"] = state.get("chat_history", []) + tool_messages
    state_updates["tool_calls"] = []

    return state_updates


def format_tool_output(tool_name: str, output: Any) -> str:
    """Format tool output for LLM"""
    if tool_name in ["get_drivers_for_city", "filter_drivers"]:
        # Create driver summary
        if isinstance(output, str):
            return output

        if not output:
            return json.dumps(
                {"total_drivers_found": 0, "message": "No drivers found."}
            )

        summary = {"total_drivers_found": len(output), "drivers": []}

        # Include key info for up to 10 drivers
        for driver in output[:10]:
            # Get first vehicle info
            vehicle = {}
            if driver.get("vehicles") and len(driver["vehicles"]) > 0:
                first_vehicle = driver["vehicles"][0]
                vehicle = {
                    "model": first_vehicle.get("model", "N/A"),
                    "type": first_vehicle.get("type", "N/A"),
                    "price_per_km": first_vehicle.get("per_km_cost", "N/A"),
                }

            summary["drivers"].append(
                {
                    "id": driver.get("id"),
                    "name": driver.get("name"),
                    "phone": driver.get("phone"),
                    "username": driver.get("username"),
                    "profile_image": driver.get("profile_image"),
                    "age": driver.get("age"),
                    "experience": driver.get("experience"),
                    "languages": driver.get("languages", []),
                    "is_pet_allowed": driver.get("is_pet_allowed"),
                    "is_married": driver.get("is_married"),
                    "city": driver.get("city"),
                    "vehicle": vehicle,
                }
            )

        return json.dumps(summary, indent=2)

    elif isinstance(output, (dict, list)):
        return json.dumps(output, indent=2)
    else:
        return str(output)


def route_after_agent(state: dict) -> str:
    """Router to decide next step after agent"""
    if state.get("tool_calls"):
        return "action"
    else:
        return END


# Build the graph
def create_graph():
    """Create the LangGraph workflow"""
    workflow = StateGraph(dict)

    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("action", tool_executor_node)

    # Set entry point
    workflow.set_entry_point("agent")

    # Add conditional edges
    workflow.add_conditional_edges(
        "agent", route_after_agent, {"action": "action", END: END}
    )

    # After tools, go back to agent
    workflow.add_edge("action", "agent")

    return workflow.compile()


# Create the app
app = create_graph()
