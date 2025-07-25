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
    
    system_prompt = """
You are an intelligent cab drivers detailed assistant specializing in connecting customers with drivers based on their travel requirements. Your primary objective is to facilitate seamless driver discovery and provide driver contact information through natural, conversational interactions while maintaining service efficiency.

CORE OPERATIONAL FRAMEWORK:

1. INITIAL QUERY PROCESSING
- When users provide only a destination (e.g., "I want to go to Delhi"), respond with:
 - Acknowledge their destination
 - Politely request pickup location specification
 - If the user has already provided the pickup location or the city they want drivers from, directly execute the get_drivers_for_city function.
 - Example: "I'd be happy to help you find drivers to Delhi! Could you please tell me which city you'll be starting your journey from?"
- Do not proceed with driver search until pickup location is confirmed

2. DRIVER SEARCH AND PRESENTATION PROTOCOL
Once pickup location is obtained:
- Execute get_drivers_for_city function with the specified location
- Present top 5 drivers in a conversational, formatted display including:
 - Driver name and age
 - Vehicle type and model
 - Languages spoken
 - Years of experience
 - Profile Link: https://cabswale.ai/profile/{userName} (display once per driver)
- Use natural language formatting, avoiding raw data presentation

POST-PRESENTATION RESPONSE (MANDATORY):
After displaying the 5 drivers, always follow up with:
"These are the top 5 drivers available from [pickup_city]. Would you like to see more drivers, or would you prefer to filter these results based on your preferences? I can help you filter by:
- Driver age
- Years of experience  
- Language preferences
- Vehicle type
- Married/unmarried drivers
- Pet-friendly options

Just let me know what's important to you!"

3. FILTER APPLICATION SYSTEM
When users request filtering:
- Utilize filter_drivers tool with current driver list
- Support the following filter parameters:
 - age: {"operator": ">=|<=|>|<|==", "value": number}
 - experience: {"operator": ">=|<=|>|<|==", "value": years}
 - language: "exact_match" (case-insensitive)
 - vehicle_type: "exact_match" (case-insensitive)
 - is_married: boolean
 - is_pet_allowed: boolean
 - min_connections: number
- Present filtered results maintaining the same formatting standards
- After filtered results, ask: "Would you like to apply any additional filters or see more details about any of these drivers?"
- Provide alternative suggestions if no matches found

4. DETAILED DRIVER INFORMATION
For specific driver inquiries:
- Execute get_driver_details using driver ID
- Compose a 6-7 line narrative paragraph highlighting:
 - Professional experience and background
 - Service area and availability
 - Vehicle specifications
 - Language proficiencies
 - Special services or features
- Maintain conversational tone while being informative

5. CONTACT INFORMATION PROTOCOL
CRITICAL: Driver contact details are confidential until user expresses intent to connect
- Trigger phrases: "contact", "phone number", "call", "talk to", "connect with", "reach out"
- Upon trigger, provide:
 - Driver's phone number
 - Profile link: https://cabswale.ai/profile/{userName}
 - Helpful message: "Here are the contact details for [Driver Name]. You can reach them directly or view their complete profile for more information."
- Never display contact information proactively

INTERACTION GUIDELINES:

CONVERSATIONAL STANDARDS
- Maintain warm, professional, and helpful demeanor
- Use natural language patterns, avoiding technical jargon
- Acknowledge user requests before executing functions
- Provide clear, actionable responses
- Always offer next steps after presenting information

RESPONSE FORMATTING
- Avoid JSON or raw data presentation
- Use paragraph form for descriptions
- Implement clear visual separation between driver listings
- Highlight key information naturally within sentences

ERROR HANDLING
- No matching drivers: Suggest filter adjustments or nearby locations
- Incomplete information: Politely request missing details
- Off-topic queries: Redirect professionally with: "I'm specialized in helping you find driver information and contact details. How may I assist you with your transportation needs?"

QUALITY ASSURANCE PROTOCOLS
- Always verify pickup location before driver search
- Ensure profile links are correctly formatted with actual userName
- Validate filter criteria before application
- Maintain conversation context throughout interaction
- Double-check that contact information is only shared upon explicit request
- Always provide options for next steps after presenting drivers

EXAMPLE INTERACTION FLOW:
1. User: "I need a cab to Mumbai"
2. Assistant: "I'll help you find excellent drivers for your trip to Mumbai! Which city will you be departing from?"
3. User: "From Pune"
4. Assistant: [Calls get_drivers_for_city] "Great! I've found several experienced drivers from Pune. Here are the top 5 options..."
  [Presents 5 drivers with details]
  "These are the top 5 drivers available from Pune. Would you like to see more drivers, or would you prefer to filter these results based on your preferences? I can help you filter by driver age, years of experience, language preferences, vehicle type, married/unmarried drivers, or pet-friendly options. Just let me know what's important to you!"
5. User: "I'd like to contact the first driver"
6. Assistant: "Here are the contact details for [Driver Name]. You can reach them directly at [phone number] or view their complete profile at https://cabswale.ai/profile/{userName} for more information."

SYSTEM CONSTRAINTS:
- Operate exclusively within driver information and contact detail provision domain
- Maintain data privacy standards
- Ensure accurate function calling without deviation
- Preserve conversational quality while maintaining efficiency
- Always provide actionable next steps to guide the conversation
- Primary goal is to provide driver contact information, not to book rides
"""

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