# langgraph_agent/graph/nodes.py
"""Refactored graph nodes for streamlined cab booking flow"""

import json
import logging
from typing import Dict, Any, List
from datetime import datetime

from langchain_core.messages import SystemMessage, ToolMessage, AIMessage
from langchain_google_vertexai import ChatVertexAI

from langgraph_agent.graph.sys_prompt import bot_prompt
from langgraph_agent.tools.drivers_tools import (
    create_trip_and_check_availability,
)
import config

logger = logging.getLogger(__name__)

# Tools list - simplified
tools = [
    create_trip_and_check_availability,
]

# Initialize LLM
llm = ChatVertexAI(model="gemini-2.0-flash", temperature=0.7)
llm_with_tools = llm.bind_tools(tools)


def agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Agent node that processes messages and decides actions"""
    logger.info("---AGENT NODE---")

    # Get current date for context
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
                # Direct response - agent is gathering info or responding
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
            # Prepare tool arguments
            prepared_args = prepare_tool_arguments(tool_name, tool_args, state_updates)

            # Execute the tool
            output = tool_to_call.invoke(prepared_args)

            # Update state based on tool output
            update_state_from_tool_output(tool_name, output, prepared_args, state_updates)

            # Format output for LLM
            if tool_name == "create_trip_and_check_availability":
                if output.get("status") == "success":
                    output_str = json.dumps({
                        "status": "success",
                        "message": "Trip created and availability request sent successfully",
                        "trip_id": output.get("trip_id"),
                        "drivers_notified": output.get("drivers_notified", 0),
                        "details": "Drivers are being notified based on preferences"
                    })
                else:
                    output_str = json.dumps(output)
            else:
                output_str = json.dumps(output) if isinstance(output, dict) else str(output)

            tool_messages.append(
                ToolMessage(content=output_str, tool_call_id=tool_id, name=tool_name)
            )

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            tool_messages.append(
                ToolMessage(
                    content=f"Error: Failed to process your request. Please try again.",
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

    if tool_name == "create_trip_and_check_availability":
        # Add customer details from state - THESE SHOULD ALREADY BE IN STATE
        args["customer_details"] = {
            "id": state.get("customer_id"),
            "name": state.get("customer_name"),
            "phone": state.get("customer_phone"),
            "profile_image": state.get("customer_profile", ""),
        }

        # Process filters if provided
        if "filters" in args and args["filters"]:
            args["filters"] = process_filter_values(args["filters"])

        logger.info(f"Creating trip with customer: {args['customer_details']['name']}")
        logger.info(f"Trip dates - Start: {args.get('start_date')}, Return: {args.get('return_date')}")

    return args


def update_state_from_tool_output(
    tool_name: str,
    output: Any,
    tool_args: Dict[str, Any],
    state: dict
) -> None:
    """Update state based on tool output"""

    if tool_name == "create_trip_and_check_availability":
        if output.get("status") == "success":
            # Store trip details in state
            state["trip_id"] = output.get("trip_id")
            state["pickup_location"] = tool_args.get("pickup_city")
            state["drop_location"] = tool_args.get("drop_city")
            state["trip_type"] = tool_args.get("trip_type")
            state["start_date"] = tool_args.get("start_date")
            state["end_date"] = tool_args.get("return_date") or tool_args.get("start_date")
            state["applied_filters"] = tool_args.get("filters", {})
            state["booking_status"] = "completed"
            state["drivers_notified"] = output.get("drivers_notified", 0)

            logger.info(f"Trip created successfully. ID: {state['trip_id']}")
            logger.info(f"Notified {state['drivers_notified']} drivers")


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
