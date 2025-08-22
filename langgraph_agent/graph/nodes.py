# langgraph_agent/graph/nodes.py
"""Graph nodes with state tracking for trip details"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta

from langchain_core.messages import SystemMessage, ToolMessage, AIMessage, HumanMessage
from langchain_google_vertexai import ChatVertexAI

from langgraph_agent.graph.sys_prompt import bot_prompt
from langgraph_agent.tools.drivers_tools import (
    create_trip_and_check_availability,
)
import config

# Configure detailed logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Tools list - simplified
tools = [
    create_trip_and_check_availability,
]

# Initialize LLM
llm = ChatVertexAI(model="gemini-2.0-flash", temperature=0.7)
llm_with_tools = llm.bind_tools(tools)


def extract_trip_details_from_message(message: str, current_date: str) -> Dict[str, Any]:
    """
    Extract trip details from user message
    Returns dict with pickup_city, drop_city, trip_type, start_date
    """
    extracted = {}
    message_lower = message.lower()

    # Common Indian cities
    cities = [
        "delhi", "mumbai", "bangalore", "bengaluru", "chennai", "kolkata",
        "hyderabad", "pune", "ahmedabad", "jaipur", "surat", "lucknow",
        "kanpur", "nagpur", "indore", "bhopal", "patna", "vadodara",
        "ghaziabad", "ludhiana", "agra", "nashik", "faridabad", "meerut",
        "rajkot", "varanasi", "srinagar", "aurangabad", "dhanbad", "amritsar",
        "gurgaon", "gurugram", "noida", "chandigarh", "mysore", "mysuru"
    ]

    # Find cities mentioned
    found_cities = []
    for city in cities:
        if city in message_lower:
            found_cities.append(city.title())

    # Determine pickup and drop from context
    if "from" in message_lower and "to" in message_lower:
        # Pattern: "from X to Y"
        parts = message_lower.split("from")[1].split("to")
        if len(parts) >= 2:
            for city in cities:
                if city in parts[0]:
                    extracted["pickup_city"] = city.title()
                if city in parts[1]:
                    extracted["drop_city"] = city.title()
    elif " to " in message_lower or " se " in message_lower:
        # Pattern: "X to Y" or "X se Y"
        if len(found_cities) >= 2:
            extracted["pickup_city"] = found_cities[0]
            extracted["drop_city"] = found_cities[1]

    # Extract trip type
    if "one-way" in message_lower or "one way" in message_lower or "oneway" in message_lower:
        extracted["trip_type"] = "one-way"
    elif "round-trip" in message_lower or "round trip" in message_lower or "roundtrip" in message_lower or "return" in message_lower:
        extracted["trip_type"] = "round-trip"

    # Extract date
    current = datetime.strptime(current_date, "%Y-%m-%d")

    if "tomorrow" in message_lower or "kal" in message_lower:
        extracted["start_date"] = (current + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "today" in message_lower or "aaj" in message_lower:
        extracted["start_date"] = current_date
    elif "day after tomorrow" in message_lower or "parso" in message_lower:
        extracted["start_date"] = (current + timedelta(days=2)).strftime("%Y-%m-%d")
    # Add more date parsing as needed

    logger.info(f"Extracted trip details: {extracted}")
    return extracted


def agent_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Agent node that processes messages and decides actions"""
    logger.info("\n" + "="*50)
    logger.info("AGENT NODE EXECUTION")
    logger.info("="*50)

    # Log current state
    logger.info("Current State:")
    logger.info(f"  - Customer ID: {state.get('customer_id')}")
    logger.info(f"  - Customer Name: {state.get('customer_name')}")
    logger.info(f"  - Trip ID: {state.get('trip_id')}")
    logger.info(f"  - Pickup: {state.get('pickup_location')}")
    logger.info(f"  - Drop: {state.get('drop_location')}")
    logger.info(f"  - Trip Type: {state.get('trip_type')}")
    logger.info(f"  - Start Date: {state.get('start_date')}")
    logger.info(f"  - Booking Status: {state.get('booking_status')}")

    # Get current date for context
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    prompt_with_date = bot_prompt.format(current_date=current_date_str)

    # Get chat history
    chat_history = state.get("chat_history", [])

    # Check if this is a new conversation and extract trip details from first message
    if len(chat_history) == 1 and isinstance(chat_history[0], HumanMessage):
        user_message = chat_history[0].content
        extracted = extract_trip_details_from_message(user_message, current_date_str)

        # Update state with extracted details if not already set
        if extracted.get("pickup_city") and not state.get("pickup_location"):
            state["pickup_location"] = extracted["pickup_city"]
            logger.info(f"  Setting pickup_location: {extracted['pickup_city']}")

        if extracted.get("drop_city") and not state.get("drop_location"):
            state["drop_location"] = extracted["drop_city"]
            logger.info(f"  Setting drop_location: {extracted['drop_city']}")

        if extracted.get("trip_type") and not state.get("trip_type"):
            state["trip_type"] = extracted["trip_type"]
            logger.info(f"  Setting trip_type: {extracted['trip_type']}")

        if extracted.get("start_date") and not state.get("start_date"):
            state["start_date"] = extracted["start_date"]
            logger.info(f"  Setting start_date: {extracted['start_date']}")

    # Build messages for LLM
    messages = [SystemMessage(content=prompt_with_date)]

    if chat_history:
        messages.extend(chat_history)
        logger.info(f"  - Chat History Length: {len(chat_history)}")
        # Log last user message
        for msg in reversed(chat_history):
            if msg.__class__.__name__ == "HumanMessage":
                logger.info(f"  - Last User Message: {msg.content[:100]}...")
                break

    # Get LLM response
    try:
        logger.info("\nInvoking LLM...")
        ai_response = llm_with_tools.invoke(messages)

        # Update chat history
        updated_history = chat_history + [ai_response]

        # Check if the response is an AIMessage and has tool_calls
        if isinstance(ai_response, AIMessage):
            if not ai_response.tool_calls:
                # Direct response - agent is gathering info or responding
                logger.info("✅ Agent provided direct response")
                logger.info(f"Response: {ai_response.content[:200]}...")

                # Return state with extracted trip details preserved
                return {
                    **state,
                    "chat_history": updated_history,
                    "last_bot_response": ai_response.content,
                    "tool_calls": [],
                }
            else:
                # Agent wants to call tools
                logger.info(f"🔧 Agent requesting tool calls:")
                for tc in ai_response.tool_calls:
                    logger.info(f"  - Tool: {tc['name']}")
                    logger.info(f"    Args: {tc.get('args', {})}")
                return {
                    **state,
                    "chat_history": updated_history,
                    "tool_calls": ai_response.tool_calls,
                }
        else:
            # Fallback for unexpected message type
            logger.warning(f"⚠️ Unexpected message type: {type(ai_response)}")
            return {
                **state,
                "chat_history": updated_history,
                "last_bot_response": str(ai_response.content) if hasattr(ai_response, 'content') else str(ai_response),
                "tool_calls": [],
            }

    except Exception as e:
        logger.error(f"❌ Error in agent_node: {e}", exc_info=True)
        return {
            **state,
            "last_bot_response": "I apologize, but I encountered an issue. Please try again.",
            "tool_calls": [],
        }


def tool_executor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Execute tools requested by the agent"""
    logger.info("\n" + "="*50)
    logger.info("TOOL EXECUTOR NODE")
    logger.info("="*50)

    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        logger.warning("⚠️ Tool executor called but no tool_calls in state.")
        return state

    tool_map = {tool.name: tool for tool in tools}
    tool_messages = []
    state_updates = dict(state)

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id")

        logger.info(f"\n🔧 Executing tool: {tool_name}")
        logger.info(f"Tool Arguments:")
        for key, value in tool_args.items():
            if key != "customer_details":  # Don't log sensitive customer details
                logger.info(f"  - {key}: {value}")

        tool_to_call = tool_map.get(tool_name)
        if not tool_to_call:
            error_msg = f"Error: Tool '{tool_name}' not found."
            logger.error(f"❌ {error_msg}")
            tool_messages.append(
                ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name)
            )
            continue

        try:
            # Prepare tool arguments
            prepared_args = prepare_tool_arguments(tool_name, tool_args, state_updates)

            logger.info("\n📞 CALLING TOOL FUNCTION...")
            # Execute the tool
            output = tool_to_call.invoke(prepared_args)
            logger.info(f"\n✅ Tool execution completed")
            logger.info(f"Tool Output: {output}")

            # Update state based on tool output
            update_state_from_tool_output(tool_name, output, prepared_args, state_updates)

            # Format output for LLM
            if tool_name == "create_trip_and_check_availability":
                if output.get("status") == "success":
                    output_str = json.dumps({
                        "status": "success",
                        "message": output.get("message"),
                        "trip_id": output.get("trip_id"),
                        "drivers_notified": output.get("drivers_notified", 0),
                        "details": "Drivers are being notified based on preferences"
                    })
                    logger.info(f"✅ SUCCESS: Trip {output.get('trip_id')} created, {output.get('drivers_notified')} drivers notified")
                else:
                    output_str = json.dumps(output)
                    logger.warning(f"⚠️ Tool returned status: {output.get('status')}")
            else:
                output_str = json.dumps(output) if isinstance(output, dict) else str(output)

            tool_messages.append(
                ToolMessage(content=output_str, tool_call_id=tool_id, name=tool_name)
            )

        except Exception as e:
            logger.error(f"❌ Error executing tool {tool_name}: {e}", exc_info=True)
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

    logger.info("\n" + "="*50)
    logger.info("TOOL EXECUTOR COMPLETED")
    logger.info(f"Final State Updates:")
    logger.info(f"  - Trip ID: {state_updates.get('trip_id')}")
    logger.info(f"  - Booking Status: {state_updates.get('booking_status')}")
    logger.info(f"  - Drivers Notified: {state_updates.get('drivers_notified')}")
    logger.info("="*50)

    return state_updates


def prepare_tool_arguments(tool_name: str, tool_args: Dict[str, Any], state: dict) -> Dict[str, Any]:
    """Prepare tool arguments with context from state"""
    logger.info("\nPreparing tool arguments...")
    args = tool_args.copy()

    if tool_name == "create_trip_and_check_availability":
        # Add customer details from state - THESE SHOULD ALREADY BE IN STATE
        customer_details = {
            "id": state.get("customer_id"),
            "name": state.get("customer_name"),
            "phone": state.get("customer_phone"),
            "profile_image": state.get("customer_profile", ""),
        }
        args["customer_details"] = customer_details

        logger.info(f"  Customer: {customer_details['name']} (ID: {customer_details['id']})")
        logger.info(f"  Route: {args.get('pickup_city')} to {args.get('drop_city')}")
        logger.info(f"  Trip Type: {args.get('trip_type')}")
        logger.info(f"  Start Date: {args.get('start_date')}")
        logger.info(f"  Return Date: {args.get('return_date')}")

        # Process filters if provided
        if "filters" in args and args["filters"]:
            args["filters"] = process_filter_values(args["filters"])
            logger.info(f"  Filters: {args['filters']}")

    return args


def update_state_from_tool_output(
    tool_name: str,
    output: Any,
    tool_args: Dict[str, Any],
    state: dict
) -> None:
    """Update state based on tool output"""
    logger.info("\nUpdating state from tool output...")

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

            logger.info(f"  ✅ State Updated:")
            logger.info(f"     - Trip ID: {state['trip_id']}")
            logger.info(f"     - Route: {state['pickup_location']} to {state['drop_location']}")
            logger.info(f"     - Trip Type: {state['trip_type']}")
            logger.info(f"     - Start Date: {state['start_date']}")
            logger.info(f"     - End Date: {state['end_date']}")
            logger.info(f"     - Drivers Notified: {state['drivers_notified']}")
            logger.info(f"     - Booking Status: {state['booking_status']}")
        else:
            logger.warning(f"  ⚠️ Tool execution was not successful: {output.get('status')}")


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
