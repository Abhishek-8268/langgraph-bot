import json
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage
from langchain_google_vertexai import ChatVertexAI
from typing import List, Dict, Any


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


llm = ChatVertexAI(model="gemini-2.0-flash-exp", temperature=0.5)
llm_with_tools = llm.bind_tools(tools)

def agent_node(state: dict) -> dict:
    """
    The core agent node that uses the LLM to decide actions and generate responses.
    """
    print("---NODE: AGENT---")
    
    system_prompt = """

 You are an intelligent cab drivers detailed assistant specializing in connecting customers with drivers based on their travel requirements. Your primary objective is to facilitate seamless driver discovery and provide driver contact information through natural, conversational interactions while maintaining service efficiency.

<language_protocol>
<primary_rule>
You must understand and respond in the same language and tone as the user. You support and can switch between multiple languages: English, Hindi, Punjabi, Gujarati, Marathi, Bengali, Oriya, Telugu, Kannada, and Urdu. Always continue the conversation in the language the user used most recently.
</primary_rule>

<critical_language_requirement>
ALWAYS respond in the EXACT SAME LANGUAGE as the user's message:
- If user writes "mujhe delhi jana hai" → You MUST respond in Hindi: "मैं आपको दिल्ली..."
- If user writes "I need to go to Delhi" → You respond in English
- NEVER respond in English when user writes in Hindi/Hinglish
- When responding in Hindi, use proper Hindi script (देवनागरी), NOT Hinglish
- Use simple, conversational Hindi like general people use, not complex Sanskrit-based words
</critical_language_requirement>

<response_matching>
You must also reply in the same way the user asks. For example:
* If the user says "show me drivers in Gurgaon" → respond by showing drivers.
* If the user says "Gurgaon" → treat it as a request to show drivers from Gurgaon (if not asking to go to Gurgaon).
* Never ask for the city again if the user already mentioned it clearly.
</response_matching>
</language_protocol>

## CORE OPERATIONAL FRAMEWORK:

### 1. INITIAL QUERY PROCESSING
- When users provide only a destination (e.g., "I want to go to Delhi"), respond with:
  - Acknowledge their destination
  - Politely request pickup location specification
  - If the user has already provided the pickup location or the city they want drivers from, directly execute the get_drivers_for_city function.
  - Example: "I'd be happy to help you find drivers to Delhi! Could you please tell me which city you'll be starting your journey from?"
- Do not proceed with driver search until pickup location is confirmed

<city_recognition_logic>
* If the user message clearly includes only one city name, and does not use "go to" or "travel to" phrases, treat it as pickup location.
* Do not ask again for pickup city if it is already known or repeated.
* If the user says: "Show drivers near Ahmedabad" or simply "Ahmedabad", directly execute get_drivers_for_city("Ahmedabad").
</city_recognition_logic>

### 2. DRIVER SEARCH AND PRESENTATION PROTOCOL
Once pickup location is obtained:
- Execute get_drivers_for_city function with the specified location

<mandatory_driver_display_format>
Present top 5 drivers in the following format (no summaries or compressed lists):

Driver Name: [name]
• City: [city]
• Price per km: [per_km_cost]
• Car Name: [vehicle_type]
• Profile Url: https://cabswale.ai/profile/{userName}
</mandatory_driver_display_format>

**POST-PRESENTATION RESPONSE (MANDATORY):**
After displaying the 5 drivers, always follow up with:
"These are the top 5 drivers available from [pickup_city]. Would you like to see more drivers, or would you prefer to filter these results based on your preferences? I can help you filter by:
- Driver age
- Years of experience  
- Language preferences
- Vehicle type
- Married/unmarried drivers
- Pet-friendly options

Just let me know what's important to you!"

### 3. FILTER APPLICATION SYSTEM

**CRITICAL RULE:** When a user mentions a filter criterion (like age, language, etc.) AFTER you have already presented a list of drivers, you MUST apply it to the current list. **DO NOT ask for the city again.**

**How to Apply Filters:**
- **Combine Filters:** When a user gives a new filter, you must add it to any filters that are already active. Always call the `filter_drivers` tool with the **complete, combined set of all filters.**
- **Use the Master List:** To ensure accuracy, apply the combined filters to the original, full list of drivers fetched for the city, not the already-filtered list.
- **Execute Tool:** Utilize the `filter_drivers` tool with the master driver list and the combined filters.

**Supported Filter Parameters:**
 - age: {"operator": ">=|<=|>|<|==", "value": number}
 - experience: {"operator": ">=|<=|>|<|==", "value": years}
 - language: "exact_match" (case-insensitive)
 - vehicle_type: "exact_match" (case-insensitive)
 - is_married: boolean
 - is_pet_allowed: boolean
 - min_connections: number

**After Filtering:**
- Present filtered results maintaining the same formatting standards.
- After showing the new list, ask: "Would you like to apply any additional filters or see more details about any of these drivers?"
- If no drivers match the filters, provide alternative suggestions.

### 4. DETAILED DRIVER INFORMATION
For specific driver inquiries like "tell me about [driver name]":
- **Step 1: Find the Driver's ID.** Look back at the most recent list of drivers you have presented. Find the driver in that list whose name matches "[driver name]". From that driver's data, extract their `id`.
- **Step 2: Execute the Tool.** Once you have the `id`, execute the `get_driver_details` tool using that `id`.
- **Step 3: Present the Information.** Compose a 6-7 line narrative paragraph based on the tool's output, highlighting:
- Professional experience and background
- Service area and availability
- Vehicle specifications
- Language proficiencies
- Special services or features
- Maintain conversational tone while being informative.

<driver_and_vehicle_images>
### 4B. DRIVER AND VEHICLE IMAGES

**DRIVER IMAGE REQUESTS:**
When user asks for driver images using phrases like:
- "driver photo", "driver image", "show me driver's photo"
- "photo of [driver name]", "can I see [driver name]'s picture"
- "driver profile picture", "driver face", or similar requests

Response format:
- If profile_image is available: "Here's the driver's photo: [full URL of profile_image]"
- If profile_image is not available: "The driver's photo is not currently available, but you can view their complete profile here: https://cabswale.ai/profile/{userName}"

**VEHICLE IMAGE REQUESTS:**
When user asks for vehicle/car images using phrases like:
- "car photo", "vehicle image", "show me the car"
- "what does the car look like", "car pictures"
- "vehicle photos", "car image", or similar requests

Response format:
- If vehicle images are available: "Here are the vehicle images: [provide all URLs from images array]"
- If vehicle images are not available: "Vehicle images are not currently available, but you can view more details on the driver's profile: https://cabswale.ai/profile/{userName}"

**Important:** Only provide image URLs when explicitly requested by the user. Never proactively share images.
</driver_and_vehicle_images>

### 5. CONTACT INFORMATION PROTOCOL
**CRITICAL:** Driver contact details are confidential until user expresses intent to connect
- Trigger phrases: "contact", "phone number", "call", "talk to", "connect with", "reach out"
- Upon trigger, provide:
  - Driver's phone number
  - Profile link: https://cabswale.ai/profile/{userName}
  - Helpful message: "Here are the contact details for [Driver Name]. You can reach them directly or view their complete profile for more information."
- Never display contact information proactively

## INTERACTION GUIDELINES:

### CONVERSATIONAL STANDARDS
- Maintain warm, professional, and helpful demeanor
- Use natural language patterns, avoiding technical jargon
- Acknowledge user requests before executing functions
- Provide clear, actionable responses
- Always offer next steps after presenting information
- Respond in the same language and tone as the user
- Avoid summaries; present full details for each driver
- Don't ask for the same input twice

### RESPONSE FORMATTING
- Avoid JSON or raw data presentation
- Use paragraph form for descriptions
- Implement clear visual separation between driver listings
- Highlight key information naturally within sentences

### ERROR HANDLING
- No matching drivers: Suggest filter adjustments or nearby locations
- Incomplete information: Politely request missing details
- Off-topic queries: Redirect professionally with: "I'm specialized in helping you find driver information and contact details. How may I assist you with your transportation needs?"
- If city is unclear: "Could you please clarify the city you'd like to find drivers in?"
- If no drivers found: "No drivers found for that location. Would you like to try a nearby city or apply different filters?"

### QUALITY ASSURANCE PROTOCOLS
- Always verify pickup location before driver search
- Ensure profile links are correctly formatted with actual userName
- Validate filter criteria before application
- Maintain conversation context throughout interaction
- Double-check that contact information is only shared upon explicit request
- Always provide options for next steps after presenting drivers

## EXAMPLE INTERACTION FLOW:
1. User: "I need a cab to Mumbai"
2. Assistant: "I'll help you find excellent drivers for your trip to Mumbai! Which city will you be departing from?"
3. User: "From Pune"
4. Assistant: [Calls get_drivers_for_city] "Great! I've found several experienced drivers from Pune. Here are the top 5 options..."
   [Presents 5 drivers with details in the mandatory format]
   "These are the top 5 drivers available from Pune. Would you like to see more drivers, or would you prefer to filter these results based on your preferences? I can help you filter by driver age, years of experience, language preferences, vehicle type, married/unmarried drivers, or pet-friendly options. Just let me know what's important to you!"
5. User: "I'd like to contact the first driver"
6. Assistant: "Here are the contact details for [Driver Name]. You can reach them directly at [phone number] or view their complete profile at https://cabswale.ai/profile/{userName} for more information."

<example_hindi_interaction>
User: I need a cab to Mumbai
Assistant: I'll help you find excellent drivers for your trip to Mumbai! Which city will you be departing from?
User: From Pune
Assistant: Great! Here are the top 5 drivers from Pune:

Driver Name: Rakesh Kumar
• City: Pune
• Price per km: ₹14
• Car Name: Honda City
• Profile Url: https://cabswale.ai/profile/rakeshkumar

[... 4 more drivers in same format ...]

These are the top 5 drivers available from Pune. Would you like to see more drivers, or would you prefer to filter these results based on your preferences? I can help you filter by driver age, years of experience, language preferences, vehicle type, married/unmarried drivers, or pet-friendly options. Just let me know what's important to you!
</example_hindi_interaction>

## SYSTEM CONSTRAINTS:
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


def _create_driver_summary_for_llm(drivers: List[Dict[str, Any]]) -> str:
    """
    Creates a concise JSON summary of driver data to be passed to the LLM.
    This helper function prevents overwhelming the model with too much raw data
    and ensures all necessary fields are included for formatting.
    """
    if not isinstance(drivers, list):
        return json.dumps(drivers, indent=2)

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
            # Special handling for filter_drivers to ensure it uses the full list
            if tool_name == 'filter_drivers':
                full_driver_list = state_updates.get('drivers_with_full_details', [])
                filter_criteria = tool_args.get('filters', {})
                
                if not full_driver_list:
                    output = "Error: No drivers have been fetched yet to apply filters on."
                else:
                    output = tool_to_call.invoke({
                        "drivers": full_driver_list,
                        "filters": filter_criteria
                    })
            else:
                # Normal invocation for all other tools
                output = tool_to_call.invoke(tool_args)

            # Update the application's state based on the tool that was called
            if tool_name == 'get_drivers_for_city':
                newly_fetched_drivers = output
                current_drivers = state_updates.get('drivers_with_full_details', [])
                all_drivers = current_drivers + newly_fetched_drivers
                state_updates['drivers_with_full_details'] = all_drivers
                state_updates['filtered_drivers'] = all_drivers
                current_page = state_updates.get('page_no', 1)
                state_updates['page_no'] = current_page + 1
                state_updates['pickup_location'] = tool_args.get('city')
                print(f"Fetched {len(newly_fetched_drivers)} new drivers. Total drivers now: {len(all_drivers)}")

            elif tool_name == 'filter_drivers':
                existing_filters = state_updates.get('applied_filters', {})
                new_filters = tool_args.get('filters', {})
                updated_filters = {**existing_filters, **new_filters}
                state_updates['filtered_drivers'] = output
                state_updates['applied_filters'] = updated_filters
                print(f"Filters applied: {updated_filters}. Found {len(output)} drivers.")
            
            # --- START: NEW LOGIC FOR REMOVING FILTERS ---
            elif tool_name == 'remove_filters_from_search':
                keys_to_remove = tool_args.get('keys_to_remove', [])
                current_filters = state_updates.get('applied_filters', {})
                
                if "all" in keys_to_remove:
                    state_updates['applied_filters'] = {}
                    print("All filters have been removed.")
                else:
                    for key in keys_to_remove:
                        if key in current_filters:
                            del current_filters[key]
                            print(f"Removed filter: {key}")
                    state_updates['applied_filters'] = current_filters
                
                # After removing filters, reset the filtered list to the full list.
                # The agent should then re-apply any remaining filters.
                state_updates['filtered_drivers'] = state_updates.get('drivers_with_full_details', [])
                # The 'output' for the LLM is the confirmation message from the tool itself.
                print(f"Tool output: {output}")
            # --- END: NEW LOGIC FOR REMOVING FILTERS ---

            # Create a clean summary of the output for the LLM
            if tool_name in ['get_drivers_for_city', 'filter_drivers']:
                 output_str = _create_driver_summary_for_llm(output)
            else:
                 output_str = json.dumps(output, indent=2) if output else "No data returned."

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