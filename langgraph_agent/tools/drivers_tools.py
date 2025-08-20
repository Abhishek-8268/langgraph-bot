# langgraph_agent/tools/drivers_tools.py
"""Driver tools for the agent"""

import logging
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
from datetime import datetime, timezone
from services import api_client
import config

logger = logging.getLogger(__name__)


@tool
def get_drivers_for_city(city: str, page: int = 1, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get drivers for a specific city with optional filters.

    Args:
        city: The city name to search for drivers. This should be a valid Indian city.
        page: Page number for pagination (default: 1).
        filters: (Optional) Dictionary of filter criteria to apply. Supported filters:
            - minAge: number (e.g., 25)
            - maxAge: number (e.g., 40)
            - minExperience: number (e.g., 5)
            - verifiedLanguages: string (e.g., "English", "Hindi")
            - vehicleTypes: string (e.g., "suv", "sedan,hatchback")
            - isPetAllowed: boolean (true/false)
            - married: boolean (true/false)
            - minConnections: number (e.g., 10)
            - profileVerified: boolean (true/false)
            - verified: boolean (true/false)
            - minDrivingExperience: number (e.g., 5)
            - allowHandicappedPersons: boolean (true/false)
            - availableForCustomersPersonalCar: boolean (true/false)
            - availableForDrivingInEventWedding: boolean (true/false)
            - availableForPartTimeFullTime: boolean (true/false)

    Returns:
        Dictionary containing drivers and pagination info.
    """
    logger.info(f"Getting drivers for {city} (page {page}) with raw filters: {filters}")

    # Process filters to ensure correct data types
    processed_filters = None
    if filters:
        processed_filters = process_filter_types(filters)
        logger.info(f"Processed filters: {processed_filters}")

    drivers_data = api_client.get_drivers(city, page, config.DRIVERS_PER_FETCH, processed_filters)

    if not drivers_data:
        logger.info(f"No drivers found in {city} with filters {processed_filters}")
        return {"drivers": [], "page": page, "has_more": False, "total_fetched": 0}

    processed_drivers = [
        process_driver_data(driver)
        for driver in drivers_data
        if driver is not None
    ]

    logger.info(f"Successfully processed {len(processed_drivers)} drivers")

    return {
        "drivers": processed_drivers,
        "page": page,
        "has_more": len(drivers_data) == config.DRIVERS_PER_FETCH,
        "total_fetched": len(processed_drivers),
    }


def process_filter_types(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process filters to ensure correct data types for API.

    Args:
        filters: Raw filter dictionary from LLM

    Returns:
        Processed filter dictionary with correct data types
    """
    processed = {}

    # Define filter type mappings based on API documentation
    integer_filters = {
        'minAge', 'maxAge', 'minExperience', 'minConnections',
        'minDrivingExperience', 'fraudReports'
    }

    boolean_filters = {
        'isPetAllowed', 'married', 'profileVerified', 'verified',
        'allowHandicappedPersons', 'availableForCustomersPersonalCar',
        'availableForDrivingInEventWedding', 'availableForPartTimeFullTime'
    }

    string_filters = {
        'verifiedLanguages', 'vehicleTypes', 'gender'
    }

    for key, value in filters.items():
        if value is None:
            continue

        try:
            if key in integer_filters:
                # Convert to integer
                processed[key] = int(value)

            elif key in boolean_filters:
                # Convert to boolean - handle various formats
                if isinstance(value, bool):
                    if value == True:
                        processed[key] = "true"
                    else:
                        processed[key] = "false"
                elif isinstance(value, str):
                    processed[key] = value.lower() in ['true', '1', 'yes', 'on']
                elif isinstance(value, (int, float)):
                    processed[key] = bool(value)
                else:
                    processed[key] = bool(value)

            elif key in string_filters:
                # Ensure string format
                processed[key] = str(value)

            else:
                # For unknown filters, pass as-is but log a warning
                logger.warning(f"Unknown filter type for '{key}': {type(value)}")
                processed[key] = value

        except (ValueError, TypeError) as e:
            logger.error(f"Error processing filter '{key}' with value '{value}': {e}")
            # Skip invalid filters rather than failing the entire request
            continue

    return processed


@tool
def apply_driver_filters(
    city: str,
    filters: Dict[str, Any],
    reset_pagination: bool = True
) -> Dict[str, Any]:
    """
    Apply specific filters to driver search and fetch filtered results.

    Args:
        city: The city to search drivers in
        filters: Dictionary of filter criteria to apply
        reset_pagination: Whether to reset to page 1 (default: True)

    Returns:
        Dictionary containing filtered drivers and updated pagination info
    """
    logger.info(f"Applying filters {filters} to drivers in {city}")

    page = 1 if reset_pagination else 1

    # Call the function directly, not as a tool
    return get_drivers_for_city.invoke({"city": city, "page": page, "filters": filters})


def process_driver_data(driver_data: Dict) -> Dict:
    """Process and format driver data from the new API response"""
    # Process vehicles
    vehicles = []
    for vehicle in driver_data.get("verified_vehicles", driver_data.get("verifiedVehicles", [])):
        vehicle_info = {
            "model": vehicle.get("model", "Unknown"),
            "type": vehicle.get("vehicle_type", vehicle.get("vehicleType", "Unknown")),
            "reg_no": vehicle.get("reg_no", ""),
            "per_km_cost": float(vehicle.get("per_km_cost", vehicle.get("perKmCost", 0))),
            "is_commercial": vehicle.get("is_commercial", False),
            "image_url": vehicle.get("primary_image_url", vehicle.get("imageUrl")),
        }
        vehicles.append(vehicle_info)

    # Combine data - handle both snake_case and camelCase
    return {
        "id": driver_data.get("id"),
        "name": driver_data.get("name", "Unknown"),
        "city": driver_data.get("city", ""),
        "phone": driver_data.get("phone_no", driver_data.get("phoneNo", "")),
        "username": driver_data.get("username", driver_data.get("userName", "")),
        "profile_image": driver_data.get("profile_image", driver_data.get("profileImage")),
        "age": driver_data.get("age"),
        "experience": driver_data.get("experience", 0),
        "bio": driver_data.get("bio", driver_data.get("driverBio", "")),
        "connections": driver_data.get("connections", 0),
        "is_pet_allowed": driver_data.get("is_pet_allowed", driver_data.get("isPetAllowed", False)),
        "is_married": driver_data.get("married", False),
        "languages": driver_data.get("verified_languages", driver_data.get("verifiedLanguages", [])),
        "trip_types": driver_data.get("trip_types", driver_data.get("tripTypes", [])),
        "routes": driver_data.get("routes", []),
        "verified_languages": driver_data.get("verified_languages", driver_data.get("verifiedLanguages", [])),
        "vehicles": vehicles,
        "lastAccess": driver_data.get("last_access", driver_data.get("lastAccess")),
        "profile_url": driver_data.get("profile_url", ""),
    }


@tool
def show_more_drivers(current_index: int, total_drivers: int) -> Dict[str, Any]:
    """
    Show next batch of drivers from already fetched list.

    Args:
        current_index: Current display index
        total_drivers: Total number of drivers available

    Returns:
        Information about next batch
    """
    next_index = current_index + config.DRIVERS_PER_DISPLAY
    has_more_in_current = next_index < total_drivers

    return {
        "next_index": next_index,
        "has_more_in_current": has_more_in_current,
        "should_fetch_new": not has_more_in_current,
    }


@tool
def remove_filters_from_search(keys_to_remove: List[str]) -> str:
    """
    Removes specified filters from the current search criteria.

    Args:
        keys_to_remove: List of filter keys to remove, or ["all"] to remove all filters

    Returns:
        Confirmation message
    """
    if "all" in keys_to_remove:
        return "Will remove all filters from the search"

    return f"Will remove the following filters: {', '.join(keys_to_remove)}"


@tool
def get_driver_details(driver_id: str, drivers: List[Dict] = []) -> Optional[Dict]:
    """
    Get detailed information for a specific driver by their ID.
    Searches the provided list of drivers first, then falls back to an API call.

    Args:
        driver_id: The unique ID of the driver
        drivers: (Optional) A list of driver dictionaries to search through.

    Returns:
        Dictionary with detailed driver information or None if not found
    """
    logger.info(f"Getting details for driver {driver_id}")

    # First, try to find the driver in the provided list
    if drivers:
        for driver in drivers:
            if driver.get("id") == driver_id:
                logger.info(f"Found driver {driver_id} in the existing list.")
                return driver

    # If not found in the list, fallback to the API call
    logger.info(f"Driver {driver_id} not in list, calling API.")
    drivers_data = api_client.get_drivers(city="", limit=1, filters={"id": driver_id})

    if not drivers_data:
        logger.warning(f"No details found for driver {driver_id}")
        return None

    return process_driver_data(drivers_data[0])


@tool
def check_driver_availability(
    driver_ids: List[str],
    trip_id: str,
    pickup_location: str,
    drop_location: str,
    trip_type: str,
    start_date: str,
    end_date: str,
    customer_details: Dict[str, str],
    user_filters: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Checks the availability of a list of drivers for the current trip.

    Args:
        trip_id: The ID of the current trip.
        driver_ids: A list of driver IDs to check for availability.
        pickup_location: The pickup city for the trip.
        drop_location: The drop-off city for the trip.
        start_date: start date of the trip in mm/dd/yy format
        end_date: end date of the trip in mm/dd/yy format (same as start_date for one-way trips)
        trip_type: The type of trip (e.g., 'one-way').
        customer_details: A dictionary containing customer's id, name, phone, and profile_image.
        user_filters: A dictionary containing user's filters for availability check.

    Returns:
        A dictionary with the result of the availability check.
    """
    if not all([trip_id, pickup_location, drop_location, trip_type, start_date, end_date]):
        return {"status": "error", "message": "Missing one or more required trip details."}

    trip_details = {
        "from": pickup_location,
        "to": drop_location,
        "trip_time": datetime.now(timezone.utc).strftime("%I:%M %p"),
        "trip_start_date": start_date,
        "trip_end_date": end_date,
        "trip_type": trip_type,
    }

    logger.info(f"Sending availability request with trip details: {trip_details}")

    response = api_client.send_availability_request(
        trip_id, driver_ids, trip_details, customer_details, user_filters
    )

    if not response:
        return {"status": "error", "message": "Failed to send the availability request due to an API error."}

    return {"status": "success", "message": "Availability requests have been sent to the drivers. You will be notified shortly."}


@tool
def create_trip(
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    customer_details: Dict[str, str],
    start_date: str,
    return_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a trip with the given details. This MUST be called before searching for drivers.

    Args:
        pickup_city: The city from where the trip starts. Should be a valid Indian city.
        drop_city: The city where the trip ends. Should be a valid Indian city.
        trip_type: The type of trip, must be either 'one-way' or 'round-trip'.
        customer_details: A dictionary containing customer's id, name, phone, and profile_image.
        start_date: The start date for the trip, in YYYY-MM-DD format.
        return_date: (Optional) The return date for a round-trip, in YYYY-MM-DD format.

    Returns:
        A dictionary with the trip creation status.
    """
    logger.info(
        f"Creating trip from {pickup_city} to {drop_city} ({trip_type}) - Start: {start_date}, Return: {return_date}"
    )

    # Helper to parse and format dates for API
    def format_date_for_api(date_str):
        """Convert YYYY-MM-DD to ISO format with current time"""
        try:
            # Parse the YYYY-MM-DD date
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            # Add current time and timezone
            current_time = datetime.now(timezone.utc)
            dt_with_time = datetime(
                dt.year, dt.month, dt.day,
                current_time.hour, current_time.minute, current_time.second,
                tzinfo=timezone.utc
            )
            # Format for API
            return dt_with_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing date {date_str}: {e}")
            # Fallback to today
            return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    # Format dates for API
    formatted_start_date = format_date_for_api(start_date)

    # Handle end date based on trip type
    if trip_type.lower() == "round-trip":
        if not return_date:
            return {"status": "error", "message": "Return date is required for a round-trip."}
        formatted_end_date = format_date_for_api(return_date)
    else:
        # For one-way trips, end date is same as start date
        formatted_end_date = formatted_start_date

    logger.info(f"Formatted dates - Start: {formatted_start_date}, End: {formatted_end_date}")

    # Call API with properly formatted dates
    trip_data = api_client.create_trip(
        customer_details,
        pickup_city,
        drop_city,
        trip_type.lower(),
        formatted_start_date,
        formatted_end_date
    )

    if not trip_data or "tripId" not in trip_data:
        return {"status": "error", "message": "Failed to create the trip due to an API error."}

    return {
        "status": "success",
        "message": "Trip created successfully.",
        "tripId": trip_data.get("tripId"),
        "pickup_city": pickup_city,
        "start_date": start_date,  # Store original date format in state
        "end_date": return_date if return_date else start_date,  # Store for availability check
    }
