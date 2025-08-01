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
    show_more_drivers,
)
import config

logger = logging.getLogger(__name__)

# Tools list
tools = [
    get_drivers_for_city,
    filter_drivers,
    get_driver_details,
    remove_filters_from_search,
    show_more_drivers,
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
                new_drivers = output.get("drivers", [])

                # Add to all fetched drivers
                all_drivers = state_updates.get("all_fetched_drivers", [])
                all_drivers.extend(new_drivers)

                state_updates["all_fetched_drivers"] = all_drivers
                state_updates["drivers_with_full_details"] = all_drivers
                state_updates["filtered_drivers"] = all_drivers
                state_updates["applied_filters"] = {}
                state_updates["pickup_location"] = tool_args.get("city")
                state_updates["current_display_index"] = 0
                state_updates["current_page"] = output.get("page", 1)
                state_updates["fetch_count"] = state_updates.get("fetch_count", 0) + 1

                logger.info(
                    f"Fetched {len(new_drivers)} drivers, total: {len(all_drivers)}"
                )

            elif tool_name == "filter_drivers":
                # Get all drivers to filter
                drivers_to_filter = state_updates.get("all_fetched_drivers", [])

                # Apply filters
                new_filters = tool_args.get("filters", {})

                # IMPORTANT: For new filter requests, replace old filters
                # This prevents the issue where it can't find drivers when applying new filters
                if new_filters:
                    combined_filters = new_filters
                else:
                    combined_filters = {
                        **state_updates.get("applied_filters", {}),
                        **new_filters,
                    }

                # Log for debugging
                logger.info(
                    f"Filtering {len(drivers_to_filter)} drivers with filters: {
                        combined_filters
                    }"
                )

                # Call filter with all drivers
                from langgraph_agent.tools.drivers_tools import (
                    filter_drivers as filter_func,
                )

                filtered_result = filter_func.invoke(
                    {"drivers": drivers_to_filter, "filters": combined_filters}
                )

                # Check if we've reached max fetch limit
                fetch_count = state_updates.get("fetch_count", 0)
                total_drivers = len(drivers_to_filter)

                # If we don't have enough matching drivers and haven't reached limit
                if (
                    len(filtered_result) < config.DRIVERS_PER_DISPLAY
                    and fetch_count < config.MAX_FETCH_DEPTH
                ):
                    current_page = state_updates.get("current_page", 1)

                    # Store current filtered results
                    state_updates["filtered_drivers"] = filtered_result
                    state_updates["applied_filters"] = combined_filters
                    state_updates["need_more_fetch"] = True
                    state_updates["need_more_for_filter"] = True

                    output = {
                        "current_matches": len(filtered_result),
                        "need_more_fetch": True,
                        "next_page": current_page + 1,
                        "total_checked": total_drivers,
                    }
                else:
                    state_updates["filtered_drivers"] = filtered_result
                    state_updates["applied_filters"] = combined_filters
                    state_updates["current_display_index"] = 0
                    output = filtered_result

                logger.info(
                    f"Applied filters: {combined_filters}, found {
                        len(filtered_result)
                    } drivers"
                )

            elif tool_name == "show_more_drivers":
                info = output
                state_updates["current_display_index"] = info.get("next_index", 0)

                # Check if we need to fetch more
                if info.get("should_fetch_new", False):
                    current_page = state_updates.get("current_page", 1)
                    fetch_count = state_updates.get("fetch_count", 0)

                    if fetch_count < config.MAX_FETCH_DEPTH:
                        # Need to fetch more drivers
                        output = {
                            "message": "need_more_drivers",
                            "next_page": current_page + 1,
                        }

            elif tool_name == "remove_filters_from_search":
                keys_to_remove = tool_args.get("keys_to_remove", [])
                current_filters = state_updates.get("applied_filters", {}).copy()

                if "all" in keys_to_remove:
                    state_updates["applied_filters"] = {}
                    state_updates["filtered_drivers"] = state_updates.get(
                        "all_fetched_drivers", []
                    )
                else:
                    for key in keys_to_remove:
                        current_filters.pop(key, None)
                    state_updates["applied_filters"] = current_filters

                    # Re-apply remaining filters
                    if current_filters:
                        all_drivers = state_updates.get("all_fetched_drivers", [])
                        filtered = filter_drivers.invoke(
                            {"drivers": all_drivers, "filters": current_filters}
                        )
                        state_updates["filtered_drivers"] = filtered
                    else:
                        state_updates["filtered_drivers"] = state_updates.get(
                            "all_fetched_drivers", []
                        )

                state_updates["current_display_index"] = 0

            # Format output for LLM
            output_str = format_tool_output(tool_name, output, state_updates)

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


def format_tool_output(tool_name: str, output: Any, state: dict) -> str:
    """Format tool output for LLM"""
    if tool_name == "get_drivers_for_city":
        # Get drivers to display (first 5)
        all_drivers = state.get("all_fetched_drivers", [])
        drivers_to_show = all_drivers[: config.DRIVERS_PER_DISPLAY]

        if not drivers_to_show:
            return json.dumps(
                {"total_drivers_found": 0, "message": "No drivers found."}
            )

        summary = {
            "total_drivers_fetched": len(all_drivers),
            "showing_drivers": len(drivers_to_show),
            "has_more": len(all_drivers) > config.DRIVERS_PER_DISPLAY,
            "drivers": format_drivers_list(drivers_to_show),
        }

        return json.dumps(summary, indent=2)

    elif tool_name == "filter_drivers":
        # Show first 5 of filtered results
        filtered = output if isinstance(output, list) else []

        # Check if we need more fetch
        if isinstance(output, dict) and output.get("need_more_fetch"):
            return json.dumps(
                {
                    "current_matching_drivers": output.get("current_matches", 0),
                    "message": "Found some matching drivers but fetching more to show you the best options.",
                    "need_more_fetch": True,
                    "next_page": output.get("next_page"),
                }
            )

        drivers_to_show = filtered[: config.DRIVERS_PER_DISPLAY]

        if not drivers_to_show:
            all_drivers_count = len(state.get("all_fetched_drivers", []))
            return json.dumps(
                {
                    "total_drivers_checked": all_drivers_count,
                    "total_matching_drivers": 0,
                    "message": f"I've searched through {all_drivers_count} drivers but couldn't find any matching your criteria.",
                    "suggestion": "Would you like to adjust your filters or try a different city?",
                }
            )

        summary = {
            "total_matching_drivers": len(filtered),
            "showing_drivers": len(drivers_to_show),
            "has_more": len(filtered) > config.DRIVERS_PER_DISPLAY,
            "drivers": format_drivers_list(drivers_to_show),
        }

        return json.dumps(summary, indent=2)

    elif tool_name == "show_more_drivers":
        if output.get("message") == "need_more_drivers":
            return json.dumps(
                {"status": "need_fetch_more", "next_page": output.get("next_page")}
            )

        # Get next batch to show
        current_index = state.get("current_display_index", 0)
        drivers_list = state.get("filtered_drivers", [])

        drivers_to_show = drivers_list[
            current_index : current_index + config.DRIVERS_PER_DISPLAY
        ]

        summary = {
            "showing_drivers": len(drivers_to_show),
            "has_more": current_index + config.DRIVERS_PER_DISPLAY < len(drivers_list),
            "drivers": format_drivers_list(drivers_to_show),
        }

        return json.dumps(summary, indent=2)

    elif isinstance(output, (dict, list)):
        return json.dumps(output, indent=2)
    else:
        return str(output)


def format_drivers_list(drivers: List[Dict]) -> List[Dict]:
    """Format driver list for display"""
    formatted = []

    for driver in drivers:
        # Get first vehicle info
        vehicle = {}
        if driver.get("vehicles") and len(driver["vehicles"]) > 0:
            first_vehicle = driver["vehicles"][0]
            vehicle = {
                "model": first_vehicle.get("model", "N/A"),
                "type": first_vehicle.get("type", "N/A"),
                "price_per_km": first_vehicle.get("per_km_cost", "N/A"),
            }

        formatted.append(
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

    return formatted


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
