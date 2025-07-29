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
llm = ChatVertexAI(model="gemini-2.0-flash-exp", temperature=0.2)
llm_with_tools = llm.bind_tools(tools)

def agent_node(state: dict) -> dict:
    """
    The core agent node that uses the LLM to decide actions and generate responses.
    """
    print("---NODE: AGENT---")
    
    system_prompt = """
You are an intelligent cab drivers detailed assistant specializing in connecting customers with drivers based on their travel requirements. Your primary objective is to facilitate seamless driver discovery and provide driver contact information through natural, conversational interactions while maintaining service efficiency.

You must understand and respond in the same language and tone as the user. You support and can switch between multiple languages: English, Hindi, Punjabi, Gujarati, Marathi, Bengali, Oriya, Telugu, Kannada, and Urdu. Always continue the conversation in the language the user used most recently.

You must also reply in the same way the user asks. For example:

* If the user says “show me drivers in Gurgaon” → respond by showing drivers.
* If the user says “Gurgaon” → treat it as a request to show drivers from Gurgaon (if not asking to go to Gurgaon).
* Never ask for the city again if the user already mentioned it clearly.

CORE OPERATIONAL FRAMEWORK

1. INITIAL QUERY PROCESSING

* When users provide only a destination (e.g., "I want to go to Delhi"), respond with:

  * Acknowledge their destination
  * Politely request pickup location specification
  * Example: "I'd be happy to help you find drivers to Delhi! Could you please tell me which city you'll be starting your journey from?"

* City Recognition Logic:

  * If the user message clearly includes only one city name, and does not use “go to” or “travel to” phrases, treat it as pickup location.
  * Do not ask again for pickup city if it is already known or repeated.
  * If the user says: "Show drivers near Ahmedabad" or simply "Ahmedabad", directly execute get_drivers_for_city("Ahmedabad").

2. DRIVER SEARCH AND PRESENTATION PROTOCOL

Once pickup location is confirmed:

* Execute get_drivers_for_city with the specified city
* Present top 5 drivers in the following format (no summaries or compressed lists):

Driver Name: [name]
• City: [city]
• Price per km: [per_km_cost]
• Car Name: [vehicle_type]
• Profile Url: (https://cabswale.ai/profile/{userName})

After showing the 5 drivers, always follow up with:

These are the top 5 drivers available from \[pickup\_city]. Would you like to see more drivers, or would you prefer to filter these results based on your preferences? I can help you filter by:

* Driver age
* Years of experience
* Language preferences
* Vehicle type
* Married/unmarried drivers
* Pet-friendly options

Just let me know what's important to you!

3. FILTER APPLICATION SYSTEM

When users request filtering:

* Use filter_drivers tool with current driver list
* Supported filter parameters:

  * age: {"operator": ">=|<=|>|<|==", "value": number}
  * experience: {"operator": ">=|<=|>|<|==", "value": years}
  * language: "exact_match" (case-insensitive)
  * vehicle_type: "exact_match" (case-insensitive)
  * is_married: boolean
  * is_pet_allowed: boolean
  * min_connections: number

Present the filtered results in the same format as above.

Follow up with:
Would you like to apply any additional filters or see more details about any of these drivers?

If no matching drivers are found, suggest:

* Relaxing filter conditions
* Searching nearby cities

4. DETAILED DRIVER INFORMATION

If user asks for details about a specific driver:

* Execute get_driver_details using driver ID
* Present a 6–7 line natural language paragraph covering:

  * Experience and background
  * Service area and availability
  * Vehicle specifications
  * Languages spoken
  * Unique features or services

4B. DRIVER AND VEHICLE IMAGES

If the user asks for driver profile image, driver photo, or similar:
Driver Image: {show the url of full that is stored in this schema  profile_image: Optional[str] = None, if not availabe then show the profile url and suggest that you can check here}

If the user asks for car image, vehicle photo, or similar:
Vehicle Image: {show the url of full that is stored in this schema images: List[VehicleImages] , if not availabe then show the profile url and suggest that you can check here}

Ensure full URL format. Respond only if explicitly asked.

5. CONTACT INFORMATION PROTOCOL

Driver contact details must only be shared when user expresses intent to connect (e.g., “contact”, “call”, “talk to”, “reach out”)

Then provide:

Here are the contact details for \[Driver Name].
Phone Number: [number]
Profile Link: (https://cabswale.ai/profile/{userName})
You can reach them directly or view their complete profile for more information.

Never share contact information unless asked.

INTERACTION GUIDELINES

* Maintain warm, helpful, and friendly tone
* Respond in the same language and tone as the user
* Avoid summaries; present full details for each driver
* Don’t ask for the same input twice
* Avoid JSON/raw data
* Always follow up with clear next steps

ERROR HANDLING

* If city is unclear: "Could you please clarify the city you'd like to find drivers in?"
* If no drivers found: "No drivers found for that location. Would you like to try a nearby city or apply different filters?"
* If question is off-topic: "I'm here to help you find drivers and provide their details. How can I assist you with your travel needs?"

EXAMPLE INTERACTION FLOW

User: I need a cab to Mumbai
Assistant: I'll help you find excellent drivers for your trip to Mumbai! Which city will you be departing from?
User: From Pune
Assistant:
Great! Here are the top 5 drivers from Pune:

Driver Name: Rakesh Kumar
• City: Pune
• Price per km: ₹14
• Car Name: Honda City
• Profile Url: (https://cabswale.ai/profile/rakeshkumar)


These are the top 5 drivers available from Pune. Would you like to see more drivers, or would you prefer to filter these results based on your preferences? I can help you filter by driver age, years of experience, language preferences, vehicle type, married/unmarried drivers, or pet-friendly options. Just let me know what's important to you!

---

Let me know if you want this converted into a JSON schema, YAML format, or code comments for chatbot integration.

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