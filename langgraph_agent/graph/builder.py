import json
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage
from langchain_google_vertexai import ChatVertexAI
from typing import List, Dict, Any
from langgraph_agent.graph.sys_prompt import bot_prompt


from langgraph_agent.tools.drivers_tools import (
    get_drivers_for_city,
    get_drivers_with_pagination,
    filter_drivers,
    get_driver_details,
    remove_filters_from_search
)


tools = [
    get_drivers_for_city,
    get_drivers_with_pagination,
    filter_drivers,
    get_driver_details,
    remove_filters_from_search
]


# Using a newer, recommended model for better performance
llm = ChatVertexAI(model="gemini-2.5-flash", temperature=0.1)
llm_with_tools = llm.bind_tools(tools)

def agent_node(state: dict) -> dict:
    """
    The core agent node that uses the LLM to decide actions and generate responses.
    """
    print("---NODE: AGENT---")
    
    system_prompt = bot_prompt

    # Ensure state has required keys
    if not isinstance(state, dict):
        state = {}
    
    # Build the conversation history
    messages = [SystemMessage(content=system_prompt)]
    
    # Add chat history
    chat_history = state.get("chat_history", [])
    if chat_history:
        messages.extend(chat_history)
    
    # Get LLM response
    try:
        ai_response = llm_with_tools.invoke(messages)
        
        # Create updated state
        updated_state = dict(state)  # Make a copy
        updated_history = chat_history + [ai_response]
        updated_state["chat_history"] = updated_history
        
        # If no tool calls, this is a direct response to the user
        if not ai_response.tool_calls:
            print(f"Agent Response: {ai_response.content}")
            updated_state["last_bot_response"] = ai_response.content
            updated_state["current_step"] = "agent_responded"
        else:
            # Agent wants to call tools
            print(f"Agent calling tools: {[tc['name'] for tc in ai_response.tool_calls]}")
            updated_state["tool_calls"] = ai_response.tool_calls
            updated_state["current_step"] = "tools_requested"
            
        return updated_state
            
    except Exception as e:
        print(f"Error in agent_node: {e}")
        error_msg = "I apologize, but I encountered an issue. Please try again."
        return {
            **state,
            "last_bot_response": error_msg,
            "current_step": "agent_error"
        }

# --- START: MODIFIED FUNCTION ---
def _create_driver_summary_for_llm(drivers: List[Dict[str, Any]]) -> str:
    """
    Creates a concise JSON summary of driver data to be passed to the LLM.
    This helper function prevents overwhelming the model with too much raw data
    and ensures all necessary fields are included for formatting.
    """
    if not isinstance(drivers, list):
        # If the tool returns a message (e.g., an error or confirmation), pass it directly.
        if isinstance(drivers, str):
            return drivers
        return json.dumps(drivers, indent=2)

    if not drivers:
        return json.dumps({
            "total_drivers_found": 0,
            "message": "No drivers found matching the criteria."
        }, indent=2)

    summary = {
        "total_drivers_found": len(drivers),
        "message": f"Successfully processed {len(drivers)} drivers.",
        "drivers_summary": []
    }

    # Include a sample of up to 10 drivers with all key information
    for driver in drivers[:10]:
        # Safely extract the primary vehicle's information
        vehicle = driver.get("vehicles", [{}])[0] if driver.get("vehicles") else {}

        driver_summary = {
            "id": driver.get("id"),
            "name": driver.get("name"),
            "phone": driver.get("phone"),
            "city": driver.get("city"),
            "username": driver.get("username"),
            "profile_image": driver.get("profile_image"),
            "age": driver.get("age"),
            "experience": driver.get("experience", 0),
            "languages": driver.get("languages", []),
            "is_pet_allowed": driver.get("is_pet_allowed"),
            "vehicle_model": vehicle.get("model", "N/A"),
            "vehicle_type": vehicle.get("type", "N/A"),
            "vehicle_image": vehicle.get("image_url"),
            "price_per_km": vehicle.get("per_km_cost"),
        }
        summary["drivers_summary"].append(driver_summary)

    return json.dumps(summary, indent=2)
# --- END: MODIFIED FUNCTION ---


# --- START: MODIFIED FUNCTION ---
def tool_executor_node(state: dict) -> dict:
    """
    Executes tools requested by the agent, processes their outputs,
    updates the state, and creates a concise summary for the next agent cycle.
    """
    print("---NODE: TOOL EXECUTOR---")
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return {**state, "current_step": "no_tools_to_execute"}

    tool_map = {tool.name: tool for tool in tools}
    tool_messages = []
    state_updates = dict(state)

    for tool_call in tool_calls:
        tool_name = tool_call.get('name')
        tool_args = tool_call.get('args', {})
        tool_id = tool_call.get('id')

        print(f"Executing tool: {tool_name} with args: {tool_args}")
        tool_to_call = tool_map.get(tool_name)

        if not tool_to_call:
            error_msg = f"Error: Tool '{tool_name}' not found."
            tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name))
            continue

        try:
            output = None
            
            # Get the full list of drivers from the current state for filtering operations
            full_driver_list = state_updates.get('drivers_with_full_details', [])

            if tool_name == 'get_drivers_for_city':
                output = tool_to_call.invoke(tool_args)
                state_updates['drivers_with_full_details'] = output
                state_updates['filtered_drivers'] = output
                state_updates['applied_filters'] = {} # Reset filters on new city search
                state_updates['pickup_location'] = tool_args.get('city')
                print(f"Fetched {len(output)} drivers. Filters reset.")

            elif tool_name == 'filter_drivers':
                if not full_driver_list:
                    output = "Error: No drivers have been fetched yet. Please search for a city first."
                else:
                    new_filters = tool_args.get('filters', {})
                    # Combine with existing filters for a comprehensive search
                    combined_filters = {**state_updates.get('applied_filters', {}), **new_filters}
                    output = tool_to_call.invoke({
                        "drivers": full_driver_list,
                        "filters": combined_filters
                    })
                    state_updates['filtered_drivers'] = output
                    state_updates['applied_filters'] = combined_filters
                    print(f"Filters applied: {combined_filters}. Found {len(output)} drivers.")

            elif tool_name == 'remove_filters_from_search':
                keys_to_remove = tool_args.get('keys_to_remove', [])
                current_filters = state_updates.get('applied_filters', {}).copy()
                
                if "all" in keys_to_remove:
                    current_filters.clear()
                    print("All filters removed.")
                else:
                    for key in keys_to_remove:
                        if key in current_filters:
                            del current_filters[key]
                            print(f"Removed filter: {key}")
                
                state_updates['applied_filters'] = current_filters
                
                # Atomically re-apply remaining filters
                if current_filters:
                    output = filter_drivers.invoke({
                        "drivers": full_driver_list,
                        "filters": current_filters
                    })
                    print(f"Re-filtered list. Found {len(output)} drivers.")
                else:
                    # If no filters left, return the full list
                    output = full_driver_list
                    print("No filters left. Returning full driver list.")
                
                state_updates['filtered_drivers'] = output

            else:
                # Normal invocation for other tools like get_driver_details
                output = tool_to_call.invoke(tool_args)

            # Create a clean summary of the output for the LLM
            if tool_name in ['get_drivers_for_city', 'filter_drivers', 'remove_filters_from_search']:
                output_str = _create_driver_summary_for_llm(output)
            else:
                output_str = json.dumps(output, indent=2) if isinstance(output, (dict, list)) else str(output)

            tool_messages.append(ToolMessage(content=output_str, tool_call_id=tool_id, name=tool_name))

        except Exception as e:
            error_msg = f"Error during execution of {tool_name}: {e}"
            print(error_msg)
            tool_messages.append(ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name))

    # Update the chat history and clear the processed tool calls for the next cycle
    state_updates['chat_history'] = state.get("chat_history", []) + tool_messages
    state_updates['tool_calls'] = []
    state_updates['current_step'] = "tools_executed"

    return state_updates
# --- END: MODIFIED FUNCTION ---


def route_after_agent(state: dict) -> str:
    """
    Router that decides the next step after the agent node.
    """
    print("---ROUTER: AFTER AGENT---")
    
    if state.get("tool_calls"):
        print("Routing to tool execution")
        return "action"
    else:
        print("Conversation complete")
        return END


# --- Graph Construction ---
def create_cab_booking_graph():
    """
    Creates and returns the compiled LangGraph workflow.
    """
    workflow = StateGraph(dict)  # Use dict instead of CabBookingState for simplicity
    
    # Add nodes
    workflow.add_node("agent", agent_node)
    workflow.add_node("action", tool_executor_node)
    
    # Set entry point
    workflow.set_entry_point("agent")
    
    # Add conditional edges
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "action": "action",
            END: END
        }
    )
    
    # After tools, go back to agent for response
    workflow.add_edge("action", "agent")
    
    return workflow.compile()


# --- Graph Export for main.py ---
app = create_cab_booking_graph()


# --- Test function ---
def test_graph():
    """Test the graph with a simple conversation"""
    print("🧪 Testing the graph...")
    
    test_state = {
        "chat_history": [],
        "drivers_with_full_details": [],
        "filtered_drivers": [],
        "applied_filters": {},
        "pickup_location": None,
        "last_bot_response": None,
        "tool_calls": []
    }
    
    # Add user message
    user_msg = HumanMessage(content="I need drivers in Jaipur")
    test_state["chat_history"] = [user_msg]
    
    print("Running graph...")
    final_state = app.invoke(test_state)
    
    print(f"Final response: {final_state.get('last_bot_response', 'No response')}")
    print(f"Drivers found: {len(final_state.get('drivers_with_full_details', []))}")
    

if __name__ == "__main__":
    test_graph()