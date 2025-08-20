# langgraph_agent/graph/nodes.py
"""Graph nodes for the cab booking agent"""

import json
import logging
from typing import Dict, Any, List
from datetime import datetime

from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from langchain_google_vertexai import ChatVertexAI

from langgraph_agent.graph.sys_prompt import bot_prompt
from langgraph_agent.tools.drivers_tools import (
    get_drivers_for_city,
    get_driver_details,
    remove_filters_from_search,
    show_more_drivers,
    create_trip,
    check_driver_availability,
)
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

# Initialize LLM
llm = ChatVertexAI(model="gemini-2.0-flash", temperature=0.9)
llm_with_tools = llm.bind_tools(tools)


def agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Agent node that processes messages and decides actions"""
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

        # Check if the response is an AIMessage and has tool_calls
        if isinstance(ai_response, AIMessage):
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
                logger.info(f"Agent calling tools: {[tc['name'] for tc in ai_response.tool_calls]}")
                return {
                    **state,
                    "chat_history": updated_history,
                    "tool_calls": ai_response.tool_calls,
                }
        else:
            # Fallback for unexpected message type
            logger.warning(f"Unexpected message type: {type(ai_response)}")
            return {
                **state,
                "chat_history": updated_history,
                "last_bot_response": str(ai_response.content) if hasattr(ai_response, 'content') else str(ai_response),
                "tool_calls": [],
            }

    except Exception as e:
        logger.error(f"Error in agent_node: {e}")
        return {
            **state,
            "last_bot_response": "I apologize, but I encountered an issue. Please try again.",
            "tool_calls": [],
        }


def tool_executor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Execute tools requested by the agent"""
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
            # Prepare tool arguments based on tool name
            prepared_args = prepare_tool_arguments(tool_name, tool_args, state_updates)

            # Execute the tool - use .func to call the underlying function
            output = tool_to_call.invoke(prepared_args)

            # Update state based on tool output
            update_state_from_tool_output(tool_name, output, prepared_args, state_updates)

            # Format output for LLM
            output_str = format_tool_output(tool_name, output, state_updates)
            tool_messages.append(
                ToolMessage(content=output_str, tool_call_id=tool_id, name=tool_name)
            )

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            tool_messages.append(
                ToolMessage(
                    content=f"Error: An unexpected error occurred while running the tool '{tool_name}'.",
                    tool_call_id=tool_id,
                    name=tool_name,
                )
            )

    # Update the chat history and clear the tool calls
    state_updates["chat_history"] = state.get("chat_history", []) + tool_messages
    state_updates["tool_calls"] = []

    return state_updates


def prepare_tool_arguments(tool_name: str, tool_args: Dict[str, Any], state: dict) -> Dict[str, Any]:
    """Prepare tool arguments with context from state"""
    args = tool_args.copy()

    if tool_name == "get_driver_details":
        args["drivers"] = state.get("all_fetched_drivers", [])

    elif tool_name == "create_trip":
        # Add customer details from state
        args["customer_details"] = {
            "id": state.get("customer_id"),
            "name": state.get("customer_name"),
            "phone": state.get("customer_phone"),
            "profile_image": state.get("customer_profile", ""),
        }
        logger.info(f"Creating trip with dates - Start: {args.get('start_date')}, Return: {args.get('return_date')}")

    elif tool_name == "check_driver_availability":
        all_drivers = state.get("all_fetched_drivers", [])
        args["driver_ids"] = [driver["id"] for driver in all_drivers]
        args["trip_id"] = state.get("trip_id")
        args["pickup_location"] = state.get("pickup_location")
        args["drop_location"] = state.get("drop_location")
        args["trip_type"] = state.get("trip_type")
        args["customer_details"] = {
            "id": state.get("customer_id"),
            "name": state.get("customer_name"),
            "phone": state.get("customer_phone"),
            "profile_image": state.get("customer_profile", ""),
        }
        args["user_filters"] = state.get("applied_filters", {})

        # Convert dates from YYYY-MM-DD to mm/dd/yy for availability API
        start_date = state.get("start_date")
        end_date = state.get("end_date")

        if start_date:
            try:
                dt = datetime.strptime(start_date, "%Y-%m-%d")
                args["start_date"] = dt.strftime("%m/%d/%y")
            except:
                args["start_date"] = datetime.now().strftime("%m/%d/%y")
        else:
            args["start_date"] = datetime.now().strftime("%m/%d/%y")

        if end_date:
            try:
                dt = datetime.strptime(end_date, "%Y-%m-%d")
                args["end_date"] = dt.strftime("%m/%d/%y")
            except:
                args["end_date"] = args["start_date"]
        else:
            args["end_date"] = args["start_date"]

        logger.info(f"Checking availability with dates - Start: {args['start_date']}, End: {args['end_date']}")

    elif tool_name == "get_drivers_for_city":
        # Handle filters
        current_filters = state.get("applied_filters", {})
        new_filters = args.get("filters", {})

        if new_filters:
            processed_filters = process_filter_values(new_filters)
            merged_filters = current_filters.copy()
            merged_filters.update(processed_filters)
            args["filters"] = merged_filters
        elif current_filters:
            args["filters"] = current_filters

        # Set city from state if not provided
        if "city" not in args and state.get("pickup_location"):
            args["city"] = state["pickup_location"]

    return args


def update_state_from_tool_output(
    tool_name: str,
    output: Any,
    tool_args: Dict[str, Any],
    state: dict
) -> None:
    """Update state based on tool output"""

    if tool_name == "create_trip":
        if "error" not in output:
            state["trip_id"] = output.get("tripId")
            state["pickup_location"] = output.get("pickup_city")
            state["drop_location"] = tool_args.get("drop_city")
            state["trip_type"] = tool_args.get("trip_type")
            state["start_date"] = output.get("start_date")
            state["end_date"] = output.get("end_date")

            logger.info(f"Trip created. Stored dates - Start: {state['start_date']}, End: {state['end_date']}")

            output["message"] = f"Trip created successfully from {tool_args.get('pickup_city')} to {tool_args.get('drop_city')}. Now I will find drivers for you."

    elif tool_name == "get_drivers_for_city":
        new_drivers = output.get("drivers", [])
        page = output.get("page", 1)

        # Update filters in state if they were applied
        if tool_args.get("filters"):
            state["applied_filters"] = tool_args["filters"]

        # Update pickup location
        if "city" in tool_args:
            state["pickup_location"] = tool_args["city"]

        if page == 1:
            # New search or filter application
            state["all_fetched_drivers"] = new_drivers
            state["current_display_index"] = 0
            state["fetch_count"] = 1
            state["current_page"] = 1
        else:
            # Pagination
            all_drivers = state.get("all_fetched_drivers", [])
            all_drivers.extend(new_drivers)
            state["all_fetched_drivers"] = all_drivers
            state["fetch_count"] = state.get("fetch_count", 0) + 1
            state["current_page"] = page

        state["filtered_drivers"] = state["all_fetched_drivers"]

        logger.info(
            f"Applied filters: {state.get('applied_filters', {})} - "
            f"Fetched {len(new_drivers)} drivers, total now: {len(state['all_fetched_drivers'])}"
        )

    elif tool_name == "show_more_drivers":
        state["current_display_index"] = output.get("next_index", 0)
        if output.get("should_fetch_new"):
            current_page = state.get("current_page", 1)
            if state.get("fetch_count", 0) < config.MAX_FETCH_DEPTH:
                output["message"] = "need_more_drivers"
                output["next_page"] = current_page + 1

    elif tool_name == "remove_filters_from_search":
        keys_to_remove = tool_args.get("keys_to_remove", [])
        current_filters = state.get("applied_filters", {}).copy()

        if "all" in keys_to_remove:
            state["applied_filters"] = {}
        else:
            for key in keys_to_remove:
                current_filters.pop(key, None)
            state["applied_filters"] = current_filters

        # Reset driver list after removing filters
        state["all_fetched_drivers"] = []
        state["filtered_drivers"] = []
        state["current_display_index"] = 0
        state["fetch_count"] = 0
        state["current_page"] = 1


def process_filter_values(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Process filter values to ensure correct format for API"""
    processed = {}

    boolean_filters = {
        'married', 'isPetAllowed', 'verified', 'profileVerified',
        'allowHandicappedPersons', 'availableForCustomersPersonalCar',
        'availableForDrivingInEventWedding', 'availableForPartTimeFullTime'
    }

    integer_filters = {
        'minAge', 'maxAge', 'minExperience', 'minConnections', 'minDrivingExperience'
    }

    string_filters = {'verifiedLanguages', 'vehicleTypes', 'gender'}

    for key, value in filters.items():
        if value is None:
            continue

        try:
            if key in boolean_filters:
                if isinstance(value, str):
                    processed[key] = value.lower() in ['true', '1', 'yes', 'on']
                else:
                    processed[key] = bool(value)
            elif key in integer_filters:
                processed[key] = int(value)
            elif key in string_filters:
                processed[key] = str(value)
            else:
                processed[key] = value
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid value for filter '{key}': {value} - {e}")
            continue

    return processed


def format_tool_output(tool_name: str, output: Any, state: dict) -> str:
    """Format tool output for LLM consumption"""
    if tool_name == "get_drivers_for_city":
        all_drivers = state.get("all_fetched_drivers", [])
        drivers_to_show = all_drivers[:config.DRIVERS_PER_DISPLAY]

        if not drivers_to_show:
            return json.dumps({"total_drivers_found": 0, "message": "No drivers found."})

        summary = {
            "total_drivers_fetched": len(all_drivers),
            "showing_drivers": len(drivers_to_show),
            "has_more": len(all_drivers) > config.DRIVERS_PER_DISPLAY,
            "drivers": format_drivers_list(drivers_to_show),
        }
        return json.dumps(summary, indent=2)

    elif tool_name == "show_more_drivers":
        if output.get("message") == "need_more_drivers":
            return json.dumps({"status": "need_fetch_more", "next_page": output.get("next_page")})

        current_index = state.get("current_display_index", 0)
        drivers_list = state.get("filtered_drivers", [])
        drivers_to_show = drivers_list[current_index:current_index + config.DRIVERS_PER_DISPLAY]

        summary = {
            "showing_drivers": len(drivers_to_show),
            "has_more": current_index + config.DRIVERS_PER_DISPLAY < len(drivers_list),
            "drivers": format_drivers_list(drivers_to_show),
        }
        return json.dumps(summary, indent=2)

    elif tool_name == "get_driver_details":
        if not output:
            return json.dumps({"error": "Driver not found"})
        return json.dumps(format_drivers_list([output])[0], indent=2)

    elif isinstance(output, (dict, list)):
        return json.dumps(output, indent=2)
    else:
        return str(output)


def format_drivers_list(drivers: List[Dict]) -> List[Dict]:
    """Format driver list for display"""
    formatted = []

    for driver in drivers:
        vehicle = {}
        if driver.get("vehicles") and len(driver["vehicles"]) > 0:
            first_vehicle = driver["vehicles"][0]
            vehicle = {
                "model": first_vehicle.get("model", "N/A"),
                "type": first_vehicle.get("type", "N/A"),
                "price_per_km": first_vehicle.get("per_km_cost", "N/A"),
                "image_url": first_vehicle.get("image_url"),
            }

        formatted.append({
            "id": driver.get("id"),
            "name": driver.get("name"),
            "phone": driver.get("phone"),
            "username": driver.get("username"),
            "profile_imagFalsee": driver.get("profile_image"),
            "age": driver.get("age"),
            "experience": driver.get("experience"),
            "languages": driver.get("languages", []),
            "is_pet_allowed": driver.get("is_pet_allowed"),
            "is_married": driver.get("is_married"),
            "city": driver.get("city"),
            "vehicle": vehicle,
            "lastAccess": driver.get("lastAccess"),
            "vehicles": driver.get("vehicles", []),
        })

    return formatted
