import time
from typing import List

from langgraph_agent.tools.drivers_tools import (
    filter_drivers, 
    get_driver_full_detail, 
    get_premium_drivers_by_city,
    get_drivers_with_details_batch
)
from schemas.driver_schema import CabBookingState, Driver, PremiumDriver


def fetch_drivers_node(state: CabBookingState) -> dict:
    """
    Fetches a list of premium drivers and then gets their full details in parallel.
    
    This node is called after a pickup city is known and we need to load drivers.
    It intelligently handles pagination and uses batch processing for efficiency.
    """
    print("---NODE: FETCHING DRIVERS---")
    
    # Get current state values
    pickup_city = state.pickup_location
    current_page = state.page_no
    limit_per_page = 10
    
    # Check if we've already exhausted the API
    if state.no_more_drivers_from_api:
        print("API has no more drivers - skipping fetch")
        return {"last_bot_response": "No more drivers available from the service."}
    
    try:
        # Use the batch tool for efficiency
        newly_fetched_drivers = get_drivers_with_details_batch.invoke({
            "city": pickup_city,
            "page": current_page,
            "limit": limit_per_page
        })
        
        # If no drivers returned, mark API as exhausted
        if not newly_fetched_drivers:
            print("No more drivers found from API.")
            return {
                "no_more_drivers_from_api": True,
                "last_bot_response": "I've searched through all available drivers."
            }
        
        print(f"Successfully fetched details for {len(newly_fetched_drivers)} drivers.")
        
        # Update the state with the new data
        updated_full_details = state.drivers_with_full_details + newly_fetched_drivers
        
        return {
            "drivers_with_full_details": updated_full_details,
            "page_no": current_page + 1,  # Increment page for next fetch
            "last_bot_response": f"Found {len(newly_fetched_drivers)} additional drivers. Let me apply your filters..."
        }
        
    except Exception as e:
        print(f"Error in fetch_drivers_node: {e}")
        return {
            "last_bot_response": "I encountered an issue while fetching drivers. Please try again."
        }


def apply_filters_and_present_node(state: CabBookingState) -> dict:
    """
    Applies filters to the full list of drivers and prepares the response.
    Handles the logic for pagination if no drivers match the filters.
    """
    print("---NODE: APPLYING FILTERS & PRESENTING---")
    
    all_drivers = state.drivers_with_full_details
    active_filters = state.applied_filters
    
    # Validate we have drivers to work with
    if not all_drivers:
        return {
            "last_bot_response": "I need to fetch some drivers first. Let me do that for you...",
            "trigger_fetch": True
        }
    
    try:
        # Apply the filters using the tool
        filtered_drivers_list = filter_drivers.invoke({
            "drivers": all_drivers,
            "filters": active_filters
        })
        
        print(f"Found {len(filtered_drivers_list)} drivers after applying filters.")
        
        # Decision logic based on results
        
        # Path A: We found drivers!
        if filtered_drivers_list:
            bot_response = format_driver_list_for_display(filtered_drivers_list)
            return {
                "filtered_drivers": filtered_drivers_list,
                "drivers_to_display": filtered_drivers_list[:5],  # Show top 5
                "last_bot_response": bot_response,
                "current_step": "drivers_presented"
            }
        
        # Path B: No drivers found, but we can fetch more pages
        elif not state.no_more_drivers_from_api and state.page_no <= state.max_filter_search_depth:
            bot_response = "I couldn't find drivers matching your criteria in the current list. Let me search for more drivers..."
            return {
                "last_bot_response": bot_response,
                "trigger_fetch": True,
                "filter_search_depth": state.filter_search_depth + 1
            }
        
        # Path C: No drivers found and we've exhausted our search
        else:
            bot_response = (
                "I couldn't find any drivers matching your specific criteria after searching extensively. "
                "Here are some highly-rated drivers you might consider, or you can adjust your filters."
            )
            
            # Show top 5 unfiltered drivers as fallback
            unfiltered_top_5 = all_drivers[:5]
            reset_message = format_driver_list_for_display(unfiltered_top_5)
            final_response = f"{bot_response}\n\n{reset_message}"
            
            return {
                "applied_filters": {},  # Reset filters
                "filtered_drivers": all_drivers,  # Reset to all drivers
                "drivers_to_display": unfiltered_top_5,
                "last_bot_response": final_response,
                "current_step": "filters_reset"
            }
    
    except Exception as e:
        print(f"Error in apply_filters_and_present_node: {e}")
        return {
            "last_bot_response": "I encountered an issue while filtering drivers. Please try again."
        }


def format_driver_list_for_display(drivers: List[Driver]) -> str:
    """
    Helper function to create a clean, readable string from a list of drivers.
    
    Args:
        drivers: List of Driver objects to format
    
    Returns:
        Formatted string for display to user
    """
    if not drivers:
        return "No drivers to display."
    
    # Limit display to 5 drivers for readability
    drivers_to_show = drivers[:5]
    
    lines = ["Here are the top drivers I found for you:"]
    
    for i, driver in enumerate(drivers_to_show):
        try:
            # Get vehicle info safely
            vehicle = None
            if driver.existingInfo.verifiedVehicles:
                vehicle = driver.existingInfo.verifiedVehicles[0]
            
            vehicle_info = f"{vehicle.model}" if vehicle else "a verified vehicle"
            
            # Get driver name safely
            driver_name = driver.existingInfo.name or "Driver"
            
            # Get age safely
            age_text = f"{driver.age} years" if driver.age else "experienced"
            
            # Get languages safely
            languages = ", ".join(driver.languages) if driver.languages else "multiple languages"
            
            # Create driver description
            line = (
                f"{i+1}. **{driver_name}** ({age_text}), "
                f"drives a **{vehicle_info}** and speaks {languages}."
            )
            
            # Add experience if available
            if driver.experience:
                line += f" {driver.experience} years of experience."
            
            lines.append(line)
            
        except Exception as e:
            print(f"Error formatting driver {i}: {e}")
            lines.append(f"{i+1}. Driver information temporarily unavailable.")
    
    # Add helpful footer
    if len(drivers) > 5:
        lines.append("\nWould you like to see more drivers, apply different filters, or get details on a specific driver?")
    else:
        lines.append("\nWould you like more details on any of these drivers or would you like to apply filters?")
    
    return "\n".join(lines)


def route_after_filtering(state: CabBookingState, last_node_output: dict) -> str:
    """
    Conditional edge that decides the next step after filtering.
    
    Args:
        state: Current CabBookingState
        last_node_output: Dictionary output from the last executed node
    
    Returns:
        String indicating the next node/edge to execute
    """
    print("---ROUTER: DECIDING NEXT STEP---")
    
    # Check for the fetch trigger signal
    if last_node_output.get("trigger_fetch"):
        print("Decision: Triggering another driver fetch.")
        return "fetch_drivers"
    
    # Check if we've reached max search depth
    elif state.filter_search_depth >= state.max_filter_search_depth:
        print("Decision: Max search depth reached, ending search.")
        return "__end__"
    
    # Default: end the current flow
    else:
        print("Decision: Normal end of driver search flow.")
        return "__end__"


def reset_driver_search_node(state: CabBookingState) -> dict:
    """
    Resets the driver search state for a fresh start.
    Useful when user wants to change city or start over.
    """
    print("---NODE: RESETTING DRIVER SEARCH---")
    
    return {
        "drivers_with_full_details": [],
        "premium_drivers": [],
        "filtered_drivers": [],
        "applied_filters": {},
        "drivers_to_display": [],
        "page_no": 1,
        "no_more_drivers_from_api": False,
        "filter_search_depth": 0,
        "current_step": "search_reset",
        "last_bot_response": "I've reset the driver search. Please let me know your pickup location to find available drivers."
    }


def update_filters_node(state: CabBookingState, new_filters: dict) -> dict:
    """
    Updates the applied filters and triggers re-filtering.
    
    Args:
        state: Current state
        new_filters: Dictionary of new filters to apply
    
    Returns:
        Updated state dictionary
    """
    print(f"---NODE: UPDATING FILTERS WITH {new_filters}---")
    
    # Merge new filters with existing ones
    updated_filters = {**state.applied_filters, **new_filters}
    
    return {
        "applied_filters": updated_filters,
        "current_step": "filters_updated",
        "last_bot_response": f"I've updated your filters. Let me find drivers that match your preferences..."
    }