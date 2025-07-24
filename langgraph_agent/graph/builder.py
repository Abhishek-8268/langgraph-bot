import json
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage
from langchain_google_vertexai import ChatVertexAI


from langgraph_agent.tools.drivers_tools import (
    get_drivers_for_city,
    get_drivers_with_pagination,
    filter_drivers,
    get_driver_details
)


tools = [
    get_drivers_for_city,
    get_drivers_with_pagination,
    filter_drivers,
    get_driver_details
]

# --- LLM Setup ---
llm = ChatVertexAI(model="gemini-2.0-flash-exp", temperature=0)
llm_with_tools = llm.bind_tools(tools)

def agent_node(state: dict) -> dict:
    """
    The core agent node that uses the LLM to decide actions and generate responses.
    """
    print("---NODE: AGENT---")
    
    system_prompt = """You are a helpful cab booking assistant. Your goal is to help users find and book drivers.

WORKFLOW:
1. When a user provides a pickup location/city, use `get_drivers_for_city` to fetch drivers for that city.
2. After getting drivers, present the top 5 in a friendly, readable format with key details like is name, age, vehicle, languages and "Profile_Link": https://cabswale.ai/profile/{userName} (here you have to use the driver userName that you get from `userName` after fetching the data from api).
3. If users want to filter drivers, use the `filter_drivers` tool with the current driver list.
4. For detailed information about a specific driver, use `get_driver_details` with the driver's ID.
5.After getting the detailed information about a specific driver presnt it in a paragarph of  6-7 lines 
6. when use say book/call then show  contact/phone number and profile url when user ask for it or if user say book the drivers otherwise hide it , when user say to book/call a specific driver show the contact details of that driver and the "Profile_Link": https://cabswale.ai/profile/{userName} (here you have to use the driver userName that you get from `userName` after fetching the data from api)
7. Always be conversational and helpful. Present information in a user-friendly way.
8. If the user try to deviate or wants to talk about somethings else other than cab booking then try to tell user you can only provide cab assistance

AVAILABLE FILTERS:
- age: {"operator": ">=", "value": 25} (operators: >, <, ==, >=, <=)
- experience: {"operator": ">=", "value": 5} (in years)
- language: "Hindi" (exact match, case-insensitive)
- vehicle_type: "Sedan" (exact match, case-insensitive)
- is_married: true/false
- is_pet_allowed: true/false
- min_connections: 100 (minimum number)

IMPORTANT:
- Always acknowledge the user's request before calling tools
- Present results in a user-friendly way, not as raw data
- If no drivers match filters, suggest adjusting criteria
- Be conversational and helpful throughout
- Focus on the most important driver information: name, age, experience, vehicle, languages
- When users ask for more info about a specific driver by name, use get_driver_details with the driver's ID from the existing driver list"""

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


def tool_executor_node(state: dict) -> dict:
    """
    Executes the tools requested by the agent and processes their outputs.
    """
    print("---NODE: TOOL EXECUTOR---")
    
    if not state.get("tool_calls"):
        return {**state, "current_step": "no_tools_to_execute"}
    
    tool_map = {tool.name: tool for tool in tools}
    tool_messages = []
    state_updates = dict(state)
    
    for tool_call in state["tool_calls"]:
        tool_name = tool_call['name']
        tool_args = tool_call['args']
        tool_id = tool_call['id']
        
        print(f"Executing tool: {tool_name} with args: {tool_args}")
        
        try:
            tool_to_call = tool_map.get(tool_name)
            if not tool_to_call:
                error_msg = f"Tool '{tool_name}' not found"
                tool_messages.append(
                    ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name)
                )
                continue
            
            # Execute the tool
            output = tool_to_call.invoke(tool_args)
            
            # Process tool outputs and update state
            if tool_name == 'get_drivers_batch_simple':
                state_updates['drivers_with_full_details'] = output
                state_updates['filtered_drivers'] = output
                state_updates['pickup_location'] = tool_args.get('city')
                print(f"Fetched {len(output)} drivers with full details")
                
            elif tool_name == 'get_premium_drivers_by_city':
                state_updates['premium_drivers'] = output
                print(f"Fetched {len(output)} premium drivers")
                
            elif tool_name == 'filter_drivers_simple':
                state_updates['filtered_drivers'] = output
                state_updates['applied_filters'] = tool_args.get('filters', {})
                print(f"Filtered to {len(output)} drivers")
                
            elif tool_name == 'get_driver_full_detail':
                print(f"Got full details for driver")
            
            # Create a summary for the LLM (avoid sending too much data)
            if isinstance(output, list) and len(output) > 0:
                if tool_name in ['get_drivers_batch_simple', 'filter_drivers_simple']:
                    # Create a concise summary for the LLM
                    summary = {
                        "total_drivers": len(output),
                        "message": f"Found {len(output)} drivers successfully",
                        "sample_drivers": []
                    }
                    
                    # Include sample of up to 10 drivers with key info only
                    for driver in output[:10]:
                        driver_summary = {
                            "id": driver.get("id"),
                            "name": driver.get("name"),
                            "age": driver.get("age"),
                            "experience": driver.get("experience"),
                            "languages": driver.get("languages", []),
                            "vehicle": driver.get("vehicles", [{}])[0].get("model", "Unknown") if driver.get("vehicles") else "No vehicle",
                            "vehicle_type": driver.get("vehicles", [{}])[0].get("vehicle_type", "Unknown") if driver.get("vehicles") else "Unknown",
                            "is_married": driver.get("is_married"),
                            "is_pet_allowed": driver.get("is_pet_allowed"),
                            "connections": driver.get("connections", 0)
                        }
                        summary["sample_drivers"].append(driver_summary)
                    
                    output_str = json.dumps(summary, indent=2)
                else:
                    output_str = json.dumps(output[:5], indent=2)
            else:
                output_str = json.dumps(output, indent=2) if output else "No data returned"
            
            tool_messages.append(
                ToolMessage(content=output_str, tool_call_id=tool_id, name=tool_name)
            )
            
        except Exception as e:
            error_msg = f"Error executing {tool_name}: {str(e)}"
            print(error_msg)
            tool_messages.append(
                ToolMessage(content=error_msg, tool_call_id=tool_id, name=tool_name)
            )
    
    # Update chat history and clear tool calls
    state_updates['chat_history'] = state.get("chat_history", []) + tool_messages
    state_updates['tool_calls'] = []
    state_updates['current_step'] = "tools_executed"
    
    return state_updates


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