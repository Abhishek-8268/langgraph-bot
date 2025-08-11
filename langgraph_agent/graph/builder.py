# langgraph_agent/graph/builder.py
"""Enhanced LangGraph agent builder with comprehensive filtering and type safety"""

import json
import logging
from typing import Dict, Any, List
from datetime import datetime

from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage
from langchain_google_vertexai import ChatVertexAI
from pydantic import ValidationError

from langgraph_agent.graph.sys_prompt import bot_prompt
from langgraph_agent.tools.drivers_tools import (
    get_drivers_for_city,
    get_driver_details,
    remove_filters_from_search,
    show_more_drivers,
    create_trip,
    check_driver_availability,
)
from schemas.driver_schema import DriverFilters, CabBookingState
import config

logger = logging.getLogger(__name__)

# Tools list
tools = [
    get_drivers_for_city,
    get_driver_details,
    remove_filters_from_search,
    show_more_drivers,
    create_trip,
    check_driver_availability,
]

# Initialize LLM with enhanced configuration
llm = ChatVertexAI(
    model="gemini-2.0-flash", 
    temperature=0.7,  # Slightly lower for more consistent tool usage
    max_tokens=2048
)
llm_with_tools = llm.bind_tools(tools)


def agent_node(state: dict) -> dict:
    """Enhanced agent node with better error handling and filtering awareness"""
    logger.info("---AGENT NODE---")

    # Get the current date to provide context to the LLM
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    prompt_with_date = bot_prompt.format(current_date=current_date_str)

    # Build messages
    messages = [SystemMessage(content=prompt_with_date)]

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
    """Enhanced tool executor with comprehensive filtering and state management"""
    logger.info("---TOOL EXECUTOR NODE---")

    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        logger.warning("Tool executor called but no tool_calls in state.")
        return state

    tool_map = {tool.name: tool for tool in tools}
    tool_messages = []
    state_updates = dict(state)

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id")

        logger.info(f"Executing tool: {tool_name} with args: {tool_args}")

        tool_to_call = tool_map.get(tool_name)
        if not tool_to_call:
            error_msg = f"Error: Tool '{tool_name}' not found."
            logger.error(error_msg)
            tool_messages.append(
                ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name)
            )
            continue

        try:
            # Enhanced context injection for tools
            if tool_name == "get_driver_details":
                tool_args["drivers"] = state_updates.get("all_fetched_drivers", [])

            elif tool_name == "create_trip":
                tool_args["customer_details"] = {
                    "id": state_updates.get("customer_id"),
                    "name": state_updates.get("customer_name"),
                    "phone": state_updates.get("customer_phone"),
                    "profile_image": state_updates.get("customer_profile"),
                }

            elif tool_name == "check_driver_availability":
                tool_args["trip_id"] = state_updates.get("trip_id")
                tool_args["pickup_location"] = state_updates.get("pickup_location")
                tool_args["drop_location"] = state_updates.get("drop_location")
                tool_args["trip_type"] = state_updates.get("trip_type")
                tool_args["customer_details"] = {
                    "id": state_updates.get("customer_id"),
                    "name": state_updates.get("customer_name"),
                    "phone": state_updates.get("customer_phone"),
                    "profile_image": state_updates.get("customer_profile"),
                }

            elif tool_name == "get_drivers_for_city":
                # Enhanced filter management
                current_filters = state_updates.get("applied_filters", {})
                new_filters = tool_args.get("filters", {})
                
                # Combine filters intelligently
                if new_filters:
                    # If new filters are provided, they should override/extend current filters
                    combined_filters = {**current_filters, **new_filters}
                else:
                    # Use existing filters
                    combined_filters = current_filters
                
                tool_args["filters"] = combined_filters
                state_updates["applied_filters"] = combined_filters
                state_updates["pickup_location"] = tool_args.get("city")
                
                logger.info(f"Applied combined filters: {combined_filters}")

            # Execute the tool
            output = tool_to_call.invoke(tool_args)

            # Enhanced state updates based on tool output
            if tool_name == "create_trip":
                if output.get("status") == "success":
                    state_updates["trip_id"] = output.get("tripId")
                    state_updates["pickup_location"] = tool_args.get("pickup_city")
                    state_updates["drop_location"] = tool_args.get("drop_city")
                    state_updates["trip_type"] = tool_args.get("trip_type")
                    output["message"] = f"Trip created successfully from {tool_args.get('pickup_city')} to {tool_args.get('drop_city')}. Now I will find drivers for you."
                
            elif tool_name == "get_drivers_for_city":
                new_drivers = output.get("drivers", [])
                applied_filters = output.get("applied_filters", {})

                # Enhanced pagination and filtering logic
                if tool_args.get("page", 1) == 1:
                    # New search - reset everything
                    state_updates["all_fetched_drivers"] = new_drivers
                    state_updates["current_display_index"] = 0
                    state_updates["fetch_count"] = 1
                    state_updates["applied_filters"] = applied_filters
                else:
                    # Pagination - append drivers
                    all_drivers = state_updates.get("all_fetched_drivers", [])
                    all_drivers.extend(new_drivers)
                    state_updates["all_fetched_drivers"] = all_drivers
                    state_updates["fetch_count"] = state_updates.get("fetch_count", 0) + 1

                # Update filtered drivers list
                state_updates["filtered_drivers"] = state_updates["all_fetched_drivers"]
                state_updates["current_page"] = output.get("page", 1)

                # Log filtering results
                filter_summary = ", ".join([f"{k}: {v}" for k, v in applied_filters.items()]) if applied_filters else "none"
                logger.info(f"Fetched {len(new_drivers)} drivers with filters: {filter_summary}")
                logger.info(f"Total drivers now: {len(state_updates['all_fetched_drivers'])}")

            elif tool_name == "show_more_drivers":
                info = output
                state_updates["current_display_index"] = info.get("next_index", 0)
                
                if info.get("should_fetch_new"):
                    current_page = state_updates.get("current_page", 1)
                    if state_updates.get("fetch_count", 0) < config.MAX_FETCH_DEPTH:
                        output = {
                            "message": "need_more_drivers",
                            "next_page": current_page + 1,
                        }

            elif tool_name == "remove_filters_from_search":
                keys_to_remove = tool_args.get("keys_to_remove", [])
                current_filters = state_updates.get("applied_filters", {}).copy()

                if "all" in keys_to_remove:
                    state_updates["applied_filters"] = {}
                    logger.info("All filters removed")
                else:
                    for key in keys_to_remove:
                        if key in current_filters:
                            del current_filters[key]
                            logger.info(f"Removed filter: {key}")
                    state_updates["applied_filters"] = current_filters

                # Reset driver data to force new search
                state_updates["all_fetched_drivers"] = []
                state_updates["filtered_drivers"] = []
                state_updates["current_display_index"] = 0
                state_updates["fetch_count"] = 0

                remaining_filters = ", ".join(current_filters.keys()) if current_filters else "none"
                output = {
                    "message": f"Filters removed successfully. Remaining filters: {remaining_filters}. Please search again to see updated results."
                }

            # Format the output for the LLM
            output_str = format_tool_output(tool_name, output, state_updates)
            tool_messages.append(
                ToolMessage(content=output_str, tool_call_id=tool_id, name=tool_name)
            )

        except ValidationError as e:
            logger.error(f"Validation error in tool {tool_name}: {e}")
            tool_messages.append(
                ToolMessage(
                    content=f"Error: Invalid parameters for '{tool_name}'. Please check your input format.",
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            tool_messages.append(
                ToolMessage(
                    content=f"Error: An unexpected error occurred while running '{tool_name}'. Please try again.",
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )

    # Update the chat history and clear tool calls
    state_updates["chat_history"] = state.get("chat_history", []) + tool_messages
    state_updates["tool_calls"] = []

    return state_updates


def format_tool_output(tool_name: str, output: Any, state: dict) -> str:
    """Enhanced tool output formatting with filter awareness"""
    
    if tool_name == "get_drivers_for_city":
        all_drivers = state.get("all_fetched_drivers", [])
        applied_filters = state.get("applied_filters", {})
        drivers_to_show = all_drivers[:config.DRIVERS_PER_DISPLAY]

        if not drivers_to_show:
            filter_summary = ", ".join([f"{k}: {v}" for k, v in applied_filters.items()]) if applied_filters else "none"
            return json.dumps({
                "total_drivers_found": 0, 
                "message": "No drivers found.",
                "applied_filters": filter_summary
            })

        # Create filter summary for display
        filter_descriptions = []
        if applied_filters:
            for key, value in applied_filters.items():
                if key == "gender":
                    filter_descriptions.append(f"{value} drivers")
                elif key == "vehicleTypes":
                    vehicles = value.split(",") if isinstance(value, str) else [value]
                    filter_descriptions.append(f"{'/'.join(vehicles)} vehicles")
                elif key == "verifiedLanguages":
                    languages = value.split(",") if isinstance(value, str) else [value]
                    filter_descriptions.append(f"{'/'.join(languages)} speaking")
                elif key == "isPetAllowed" and value:
                    filter_descriptions.append("pet-friendly")
                elif key == "married":
                    filter_descriptions.append("married" if value else "unmarried")
                elif key == "minAge":
                    filter_descriptions.append(f"age {value}+")
                elif key == "maxAge":
                    filter_descriptions.append(f"age under {value}")
                elif key == "minExperience":
                    filter_descriptions.append(f"{value}+ years experience")
                elif key == "minConnections":
                    filter_descriptions.append(f"{value}+ connections")

        summary = {
            "total_drivers_fetched": len(all_drivers),
            "showing_drivers": len(drivers_to_show),
            "has_more": len(all_drivers) > config.DRIVERS_PER_DISPLAY,
            "applied_filters": ", ".join(filter_descriptions) if filter_descriptions else "none",
            "drivers": format_drivers_list(drivers_to_show),
        }

        return json.dumps(summary, indent=2)

    elif tool_name == "show_more_drivers":
        if output.get("message") == "need_more_drivers":
            return json.dumps({
                "status": "need_fetch_more", 
                "next_page": output.get("next_page"),
                "current_filters": state.get("applied_filters", {})
            })

        # Get next batch to show
        current_index = state.get("current_display_index", 0)
        drivers_list = state.get("filtered_drivers", [])
        applied_filters = state.get("applied_filters", {})

        drivers_to_show = drivers_list[
            current_index : current_index + config.DRIVERS_PER_DISPLAY
        ]

        # Create filter summary
        filter_descriptions = create_filter_summary(applied_filters)

        summary = {
            "showing_drivers": len(drivers_to_show),
            "has_more": current_index + config.DRIVERS_PER_DISPLAY < len(drivers_list),
            "applied_filters": filter_descriptions,
            "drivers": format_drivers_list(drivers_to_show),
        }

        return json.dumps(summary, indent=2)

    elif tool_name == "get_driver_details":
        if not output:
            return json.dumps({"error": "Driver not found"})
        return json.dumps(format_drivers_list([output])[0], indent=2)

    elif tool_name == "remove_filters_from_search":
        remaining_filters = state.get("applied_filters", {})
        filter_summary = create_filter_summary(remaining_filters)
        return json.dumps({
            "message": output,
            "remaining_filters": filter_summary
        })

    elif isinstance(output, (dict, list)):
        return json.dumps(output, indent=2)
    else:
        return str(output)


def create_filter_summary(filters: Dict[str, Any]) -> str:
    """Create a human-readable summary of applied filters"""
    if not filters:
        return "none"
    
    descriptions = []
    for key, value in filters.items():
        if key == "gender":
            descriptions.append(f"{value} drivers")
        elif key == "vehicleTypes":
            vehicles = value.split(",") if isinstance(value, str) else [str(value)]
            descriptions.append(f"{'/'.join(vehicles)} vehicles")
        elif key == "verifiedLanguages":
            languages = value.split(",") if isinstance(value, str) else [str(value)]
            descriptions.append(f"{'/'.join(languages)} speaking")
        elif key == "isPetAllowed":
            descriptions.append("pet-friendly" if value else "no pets")
        elif key == "married":
            descriptions.append("married" if value else "unmarried")
        elif key == "minAge":
            descriptions.append(f"age {value}+")
        elif key == "maxAge":
            descriptions.append(f"age under {value}")
        elif key == "minExperience":
            descriptions.append(f"{value}+ years experience")
        elif key == "minConnections":
            descriptions.append(f"{value}+ connections")
        elif key == "verified":
            descriptions.append("verified" if value else "unverified")
        elif key == "profileVerified":
            descriptions.append("profile verified" if value else "profile not verified")
        elif key == "fraudReports":
            descriptions.append(f"max {value} fraud reports")
        elif key == "connections":
            descriptions.append(f"connections {value}")
        else:
            descriptions.append(f"{key}: {value}")
    
    return ", ".join(descriptions)


def format_drivers_list(drivers: List[Dict]) -> List[Dict]:
    """Enhanced driver list formatting with comprehensive data"""
    formatted = []

    for driver in drivers:
        # Get first vehicle info with enhanced details
        vehicle = {}
        if driver.get("vehicles") and len(driver["vehicles"]) > 0:
            first_vehicle = driver["vehicles"][0]
            vehicle = {
                "model": first_vehicle.get("model", "N/A"),
                "type": first_vehicle.get("type", "N/A"),
                "price_per_km": first_vehicle.get("per_km_cost", "N/A"),
                "reg_no": first_vehicle.get("reg_no", "N/A"),
                "is_commercial": first_vehicle.get("is_commercial", False),
                "image_url": first_vehicle.get("image_url"),
            }

        # Enhanced driver formatting with all relevant data
        formatted_driver = {
            "id": driver.get("id"),
            "name": driver.get("name"),
            "phone": driver.get("phone"),
            "username": driver.get("username"),
            "profile_image": driver.get("profile_image"),
            
            # Demographics
            "age": driver.get("age"),
            "gender": driver.get("gender"),
            "is_married": driver.get("is_married"),
            
            # Experience and verification
            "experience": driver.get("experience"),
            "driving_experience": driver.get("driving_experience"),
            "connections": driver.get("connections"),
            "verified": driver.get("verified"),
            "profile_verified": driver.get("profile_verified"),
            
            # Preferences
            "is_pet_allowed": driver.get("is_pet_allowed"),
            "allow_handicapped_persons": driver.get("allow_handicapped_persons"),
            "available_for_customers_personal_car": driver.get("available_for_customers_personal_car"),
            "available_for_driving_in_event_wedding": driver.get("available_for_driving_in_event_wedding"),
            
            # Professional info
            "languages": driver.get("languages", []),
            "verified_languages": driver.get("verified_languages", []),
            "bio": driver.get("bio"),
            "fraud_reports": driver.get("fraud_reports"),
            
            # Location and timing
            "city": driver.get("city"),
            "last_access": driver.get("lastAccess"),
            
            # Vehicle info
            "vehicle": vehicle,
            "vehicles": driver.get("vehicles", []),
        }

        formatted.append(formatted_driver)

    return formatted


def validate_state(state: dict) -> dict:
    """Validate and clean state data"""
    try:
        # Ensure applied_filters is always a dictionary
        if "applied_filters" not in state:
            state["applied_filters"] = {}
        elif not isinstance(state["applied_filters"], dict):
            logger.warning("applied_filters is not a dict, resetting")
            state["applied_filters"] = {}

        # Ensure lists are properly initialized
        for key in ["all_fetched_drivers", "filtered_drivers", "chat_history", "tool_calls"]:
            if key not in state:
                state[key] = []
            elif not isinstance(state[key], list):
                logger.warning(f"{key} is not a list, resetting")
                state[key] = []

        # Ensure numeric values are valid
        for key in ["current_display_index", "current_page", "fetch_count"]:
            if key not in state:
                state[key] = 0
            elif not isinstance(state[key], int) or state[key] < 0:
                logger.warning(f"{key} is invalid, resetting")
                state[key] = 0

        return state
    except Exception as e:
        logger.error(f"Error validating state: {e}")
        return state


def route_after_agent(state: dict) -> str:
    """Enhanced router with state validation"""
    state = validate_state(state)
    
    if state.get("tool_calls"):
        return "action"
    else:
        return END


# Build the enhanced graph
def create_graph():
    """Create the enhanced LangGraph workflow with filtering capabilities"""
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


# Create the enhanced app
app = create_graph()