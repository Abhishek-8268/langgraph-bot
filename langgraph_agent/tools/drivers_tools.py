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
        city: The city name to search for drivers.
        page: Page number for pagination (default: 1).
        filters: (Optional) Dictionary of filter criteria to apply.

    Returns:
        Dictionary containing drivers and pagination info.
    """
    logger.info(f"Getting drivers for {city} (page {page}) with filters: {filters}")

    drivers_data = api_client.get_drivers(city, page, config.DRIVERS_PER_FETCH, filters)

    if not drivers_data:
        logger.info(f"No drivers found in {city}")
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


def process_driver_data(driver_data: Dict) -> Dict:
    """Process and format driver data from the new API response"""
    # Process vehicles
    vehicles = []
    for vehicle in driver_data.get("verifiedVehicles", []):
        vehicle_info = {
            "model": vehicle.get("model", "Unknown"),
            "type": vehicle.get("vehicleType", "Unknown"),
            "reg_no": vehicle.get("reg_no", ""),
            "per_km_cost": float(vehicle.get("perKmCost", 0)),
            "is_commercial": vehicle.get("is_commercial", False),
            "image_url": vehicle.get("imageUrl"),
        }
        vehicles.append(vehicle_info)

    # Combine data
    return {
        "id": driver_data.get("id"),
        "name": driver_data.get("name", "Unknown"),
        "city": driver_data.get("city", ""),
        "phone": driver_data.get("phoneNo", ""),
        "username": driver_data.get("userName", ""),
        "profile_image": driver_data.get("profileImage"),
        "age": driver_data.get("age"),
        "experience": driver_data.get("experience", 0),
        "bio": driver_data.get("driverBio", ""),
        "connections": driver_data.get("connections", 0),
        "is_pet_allowed": driver_data.get("isPetAllowed", False),
        "is_married": driver_data.get("married", False),
        "languages": [lang for lang in driver_data.get("verifiedLanguages", []) if lang],
        "trip_types": driver_data.get("tripTypes", []),
        "routes": driver_data.get("routes", []),
        "verified_languages": [
            {"name": lang, "verified": True}
            for lang in driver_data.get("verifiedLanguages", []) if lang
        ],
        "vehicles": vehicles,
        "lastAccess": driver_data.get("lastAccess"),
    }


@tool
def filter_drivers(drivers: List[Dict], filters: Dict[str, Any]) -> List[Dict]:
    """
    Filter drivers based on various criteria.

    Args:
        drivers: List of driver dictionaries to filter
        filters: Dictionary of filter criteria

    Returns:
        Filtered list of drivers
    """
    logger.info(f"Filtering {len(drivers)} drivers with filters: {filters}")

    if not filters or not drivers:
        return drivers

    filtered_drivers = []

    for driver in drivers:
        # Check each filter
        passes_all_filters = True

        for filter_key, filter_value in filters.items():
            if not passes_filter(driver, filter_key, filter_value):
                passes_all_filters = False
                break

        if passes_all_filters:
            filtered_drivers.append(driver)

    logger.info(f"Filtering complete: {len(filtered_drivers)} drivers remaining")
    return filtered_drivers


def passes_filter(driver: Dict, key: str, value: Any) -> bool:
    """Check if a single driver passes a given filter"""
    if key == "age" and isinstance(value, dict):
        driver_age = driver.get("age")
        return driver_age is not None and compare_values(
            driver_age, value.get("operator", ">="), value.get("value")
        )

    if key == "experience" and isinstance(value, dict):
        driver_exp = driver.get("experience", 0)
        return compare_values(
            driver_exp, value.get("operator", ">="), value.get("value")
        )

    if key == "language" and isinstance(value, str):
        target_lang = value.lower()
        languages = driver.get("languages", [])
        return any(lang.lower() == target_lang for lang in languages)

    if key == "vehicle_type" and isinstance(value, str):
        target_type = value.lower()
        vehicles = driver.get("vehicles", [])
        return any(
            target_type in v.get("type", "").lower() for v in vehicles
        )

    if key in ["is_married", "is_pet_allowed"] and isinstance(value, bool):
        return driver.get(key) == value

    if key == "min_connections" and isinstance(value, (int, float)):
        return driver.get("connections", 0) >= value

    if key == "min_experience" and isinstance(value, (int, float)):
        return driver.get("experience", 0) >= value

    # Default to true if filter doesn't apply
    return True


def compare_values(
    driver_value: Optional[float], operator: str, target_value: Optional[float]
) -> bool:
    """Compare values based on operator"""
    if driver_value is None or target_value is None:
        return False
    if operator == ">":
        return driver_value > target_value
    if operator == "<":
        return driver_value < target_value
    if operator == ">=":
        return driver_value >= target_value
    if operator == "<=":
        return driver_value <= target_value
    if operator == "==":
        return driver_value == target_value
    return False


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
) -> Dict[str, Any]:
    """
    Checks the availability of a list of drivers for the current trip.

    Args:
        driver_ids: A list of driver IDs to check for availability.
        trip_id: The ID of the current trip.
        pickup_location: The pickup city for the trip.
        drop_location: The drop-off city for the trip.
        trip_type: The type of trip (e.g., 'one-way').

    Returns:
        A dictionary with the result of the availability check.
    """
    if not all([trip_id, pickup_location, drop_location, trip_type]):
        return {"status": "error", "message": "Missing one or more required trip details."}

    trip_details = {
        "from": pickup_location,
        "to": drop_location,
        "trip_time": datetime.now(timezone.utc).strftime("%I:%M %p"),
        "trip_date": datetime.now(timezone.utc).strftime("%d/%m/%y"),
        "trip_type": trip_type,
    }

    response = api_client.send_availability_request(
        trip_id, driver_ids, trip_details
    )

    if not response:
        return {"status": "error", "message": "Failed to send the availability request due to an API error."}

    return {"status": "success", "message": "Availability requests have been sent to the drivers. You will be notified shortly."}

@tool
def create_trip(
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    return_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Creates a trip with the given details. This MUST be called before searching for drivers.

    Args:
        pickup_city: The city from where the trip starts.
        drop_city: The city where the trip ends.
        trip_type: The type of trip, must be either 'one-way' or 'round-trip'.
        return_date: (Optional) The return date for a round-trip, in YYYY-MM-DD format.

    Returns:
        A dictionary with the trip creation status.
    """
    logger.info(
        f"Creating trip from {pickup_city} to {drop_city} ({trip_type})"
    )
    # Format dates to match the API's expected format (e.g., 2025-08-07T09:00:00.000Z)
    start_date = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    
    end_date = None
    if trip_type.lower() == "round-trip":
        if not return_date:
            return {"status": "error", "message": "Return date is required for a round-trip."}
        try:
            # Parse the date and set a predefined time of 12:00:00 in UTC
            end_date_dt = datetime.strptime(return_date, "%Y-%m-%d")
            end_date_dt_utc = datetime(
                end_date_dt.year, end_date_dt.month, end_date_dt.day, 12, 0, 0, tzinfo=timezone.utc
            )
            end_date = end_date_dt_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        except ValueError:
            return {"status": "error", "message": "Invalid return date format. Please use YYYY-MM-DD."}
    # For one-way trips, set a default end date (e.g., same as start date)
    else:
        end_date = start_date

    trip_data = api_client.create_trip(
        pickup_city, drop_city, trip_type.lower(), start_date, end_date
    )

    if not trip_data or "tripId" not in trip_data:
        return {"status": "error", "message": "Failed to create the trip due to an API error."}

    return {
        "status": "success",
        "message": "Trip created successfully.",
        "tripId": trip_data.get("tripId"),
        "pickup_city": pickup_city,
    }