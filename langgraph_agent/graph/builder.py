import json
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, ToolMessage, HumanMessage
from langchain_google_vertexai import ChatVertexAI
from typing import List, Dict, Any

from langgraph_agent.graph.sys_prompt import bot_prompt
from langgraph_agent.tools.drivers_tools import (
    get_drivers_for_city,
    filter_drivers,
    get_driver_details,
    remove_filters_from_search,
    show_more_drivers
)

tools = [
    get_drivers_for_city,
    filter_drivers,
    get_driver_details,
    remove_filters_from_search,
    show_more_drivers
]

llm = ChatVertexAI(model="gemini-2.0-flash", temperature=0.1)
llm_with_tools = llm.bind_tools(tools)

def agent_node(state: dict) -> dict:
    """The core agent node that uses the LLM to decide on the next action."""
    messages = [SystemMessage(content=bot_prompt)] + state.get("chat_history", [])
    
    try:
        ai_response = llm_with_tools.invoke(messages)
        updated_history = state.get("chat_history", []) + [ai_response]
        
        if not ai_response.tool_calls:
            return {**state, "chat_history": updated_history, "last_bot_response": ai_response.content}
        else:
            return {**state, "chat_history": updated_history, "tool_calls": ai_response.tool_calls}
            
    except Exception:
        return {**state, "last_bot_response": "I apologize, but I encountered an issue. Please try again."}

def _create_driver_summary_for_llm(state: dict) -> str:
    """
    Creates a concise, flattened JSON summary of the current display state for the LLM,
    including the search depth to guide re-fetching decisions.
    """
    drivers_to_paginate = state.get('filtered_drivers', state.get('drivers_with_full_details', []))
    offset = state.get('display_offset', 0)
    drivers_to_display = drivers_to_paginate[offset:offset+5]
    
    summary = {
        "message": f"Displayed drivers {offset+1} to {offset+len(drivers_to_display)}.",
        "total_drivers_in_current_list": len(drivers_to_paginate),
        "drivers_in_current_view": len(drivers_to_display),
        "more_drivers_in_list": len(drivers_to_paginate) > offset + 5,
        "no_more_drivers_from_api": state.get("no_more_drivers_from_api", False),
        "filter_search_depth": state.get("filter_search_depth", 0),
        "unfiltered_search_depth": state.get("unfiltered_search_depth", 0),
        "drivers_summary": []
    }

    for driver in drivers_to_display:
        vehicle = driver.get("vehicles", [{}])[0] if driver.get("vehicles") else {}
        summary["drivers_summary"].append({
            "id": driver.get("id"),
            "name": driver.get("name"),
            "city": driver.get("city"),
            "userName": driver.get("username"),
            "car_model": vehicle.get("model", "Not available"),
            "price_per_km": vehicle.get("per_km_cost")
        })

    return json.dumps(summary, indent=2)

def tool_executor_node(state: dict) -> dict:
    """Executes tools and manages state, including the filter and unfiltered search depth."""
    tool_calls = state.get("tool_calls", [])
    if not tool_calls:
        return state

    tool_map = {tool.name: tool for tool in tools}
    tool_messages = []
    state_updates = dict(state)

    for tool_call in tool_calls:
        tool_name = tool_call.get('name')
        tool_args = tool_call.get('args', {})
        tool_id = tool_call.get('id')
        
        tool_to_call = tool_map.get(tool_name)
        if not tool_to_call:
            tool_messages.append(ToolMessage(content=f"Error: Tool '{tool_name}' not found.", tool_call_id=tool_id))
            continue

        try:
            if tool_name == 'get_drivers_for_city':
                tool_args['limit'] = 25
                newly_fetched = tool_to_call.invoke(tool_args)
                
                if state_updates.get('applied_filters'):
                    state_updates['filter_search_depth'] = state_updates.get('filter_search_depth', 0) + 1
                else:
                    state_updates['unfiltered_search_depth'] = state_updates.get('unfiltered_search_depth', 0) + 1

                if not newly_fetched:
                    state_updates['no_more_drivers_from_api'] = True
                else:
                    current_drivers = state_updates.get('drivers_with_full_details', [])
                    state_updates['drivers_with_full_details'] = current_drivers + newly_fetched
                    state_updates['page_no'] = state_updates.get('page_no', 1) + 1
                
                current_filters = state_updates.get('applied_filters', {})
                all_drivers = state_updates.get('drivers_with_full_details', [])
                state_updates['filtered_drivers'] = filter_drivers.invoke({"drivers": all_drivers, "filters": current_filters}) if current_filters else all_drivers
                state_updates['display_offset'] = 0

            elif tool_name == 'filter_drivers':
                all_drivers = state_updates.get('drivers_with_full_details', [])
                new_filters = tool_args.get('filters', {})
                combined_filters = {**state_updates.get('applied_filters', {}), **new_filters}
                
                filtered_output = tool_to_call.invoke({"drivers": all_drivers, "filters": combined_filters})
                
                state_updates['filtered_drivers'] = filtered_output
                state_updates['applied_filters'] = combined_filters
                state_updates['display_offset'] = 0
                state_updates['filter_search_depth'] = 1

            elif tool_name == 'show_more_drivers':
                state_updates['display_offset'] = state_updates.get('display_offset', 0) + 5

            elif tool_name == 'remove_filters_from_search':
                keys_to_remove = tool_args.get('keys_to_remove', [])
                current_filters = state_updates.get('applied_filters', {}).copy()
                if "all" in keys_to_remove:
                    current_filters.clear()
                else:
                    for key in keys_to_remove:
                        if key in current_filters: del current_filters[key]
                
                state_updates['applied_filters'] = current_filters
                all_drivers = state_updates.get('drivers_with_full_details', [])
                state_updates['filtered_drivers'] = filter_drivers.invoke({"drivers": all_drivers, "filters": current_filters}) if current_filters else all_drivers
                state_updates['display_offset'] = 0
                state_updates['filter_search_depth'] = 0

            else: # Handles get_driver_details
                output = tool_to_call.invoke(tool_args)
                tool_messages.append(ToolMessage(content=json.dumps(output) if output else "No details found.", tool_call_id=tool_id))
                continue

            summary_for_llm = _create_driver_summary_for_llm(state_updates)
            tool_messages.append(ToolMessage(content=summary_for_llm, tool_call_id=tool_id))

        except Exception as e:
            tool_messages.append(ToolMessage(content="An error occurred while processing your request.", tool_call_id=tool_id))

    state_updates['chat_history'] = state.get("chat_history", []) + tool_messages
    state_updates['tool_calls'] = []
    return state_updates

def route_after_agent(state: dict) -> str:
    """Decides the next step after the agent node."""
    if state.get("tool_calls"):
        return "action"
    return END

def create_cab_booking_graph():
    """Builds and compiles the LangGraph workflow."""
    workflow = StateGraph(dict)
    workflow.add_node("agent", agent_node)
    workflow.add_node("action", tool_executor_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", route_after_agent, {"action": "action", END: END})
    workflow.add_edge("action", "agent")
    return workflow.compile()

app = create_cab_booking_graph()
