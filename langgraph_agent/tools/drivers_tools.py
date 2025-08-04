# langgraph_agent/tools/drivers_tools.py
"""Driver tools for the agent"""

import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.tools import tool

from services import api_client
import config

logger = logging.getLogger(__name__)


@tool
def get_drivers_for_city(city: str, page: int = 1) -> Dict[str, Any]:
    """
    Get drivers for a specific city with full details.

    Args:
        city: The city name to search for drivers
        page: Page number for pagination (default: 1)

    Returns:
        Dictionary containing drivers and pagination info
    """
    logger.info(f"Getting drivers for {city} (page {page})")

    # Get premium drivers (20 at a time)
    premium_drivers = api_client.get_premium_drivers(
        city, page, config.DRIVERS_PER_FETCH
    )

    if not premium_drivers:
        logger.info(f"No drivers found in {city}")
        return {"drivers": [], "page": page, "has_more": False, "total_fetched": 0}

    logger.info(
        f"Found {len(premium_drivers)} premium drivers, fetching details in parallel..."
    )

    # Fetch details in parallel for better performance
    drivers_with_details = []

    with ThreadPoolExecutor(max_workers=20) as executor:
        # Submit all tasks
        future_to_driver = {
            executor.submit(fetch_driver_details, driver): driver
            for driver in premium_drivers
        }

        # Collect results
        for future in as_completed(future_to_driver, timeout=15):
            try:
                result = future.result()
                if result:
                    drivers_with_details.append(result)
            except Exception as e:
                driver = future_to_driver[future]
                logger.error(
                    f"Failed to fetch details for driver {driver.get('id')}: {e}"
                )

    logger.info(
        f"Successfully fetched {len(drivers_with_details)} drivers with details"
    )

    return {
        "drivers": drivers_with_details,
        "page": page,
        "has_more": len(premium_drivers) == config.DRIVERS_PER_FETCH,
        "total_fetched": len(drivers_with_details),
    }


def fetch_driver_details(premium_driver: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Fetch and process driver details"""
    driver_id = premium_driver.get("id")
    if not driver_id:
        return None

    details = api_client.get_driver_details(driver_id)
    if not details:
        return None

    return process_driver_data(premium_driver, details, driver_id)


def process_driver_data(premium_driver: Dict, details: Dict, driver_id: str) -> Dict:
    """Process and combine driver data"""
    # Get profile image
    profile_image = None
    photos = premium_driver.get("photos", [])
    if photos and isinstance(photos, list) and len(photos) > 0:
        photo = photos[0]
        if isinstance(photo, dict) and "full" in photo:
            profile_image = photo["full"].get("url")

    # Process vehicles
    vehicles = []
    for vehicle in premium_driver.get("verifiedVehicles", []):
        # Get vehicle image
        image_url = None
        if vehicle.get("images"):
            try:
                first_image = vehicle["images"][0]
                if isinstance(first_image, dict) and "full" in first_image:
                    image_url = first_image["full"].get("url")
            except:
                pass

        vehicle_info = {
            "model": vehicle.get("model", "Unknown"),
            "type": vehicle.get("vehicleType")
            or vehicle.get("vehicle_type", "Unknown"),
            "reg_no": vehicle.get("reg_no", ""),
            "per_km_cost": float(vehicle.get("perKmCost", 0))
            if vehicle.get("perKmCost")
            else 0.0,
            "is_commercial": vehicle.get("is_commercial", False),
            "image_url": image_url,
        }
        vehicles.append(vehicle_info)

    # Combine data
    return {
        "id": driver_id,
        "name": premium_driver.get("name", "Unknown"),
        "city": premium_driver.get("city", ""),
        "phone": premium_driver.get("phoneNo", ""),
        "username": premium_driver.get("userName", ""),
        "profile_image": profile_image,
        "age": details.get("age"),
        "experience": details.get("experience", 0),
        "bio": details.get("driverBio", ""),
        "connections": details.get("connections", 0),
        "is_pet_allowed": details.get("isPetAllowed", False),
        "is_married": details.get("married", False),
        "languages": details.get("languages", []),
        "trip_types": details.get("tripTypes", []),
        "routes": [
            {"from": r.get("from", ""), "to": r.get("to", "")}
            for r in details.get("routes", [])
        ],
        "verified_languages": [
            {"name": l.get("name", ""), "verified": l.get("verified", False)}
            for l in details.get("verifiedLanguages", [])
        ],
        "vehicles": vehicles,
    }


# langgraph_agent/tools/drivers_tools.py


@tool
def filter_drivers(drivers: List[Dict], filters: Dict[str, Any]) -> List[Dict]:
    """
    Filter drivers based on various criteria in a single pass.

    Args:
        drivers: List of driver dictionaries to filter
        filters: Dictionary of filter criteria

    Returns:
        Filtered list of drivers
    """
    logger.info(f"Filtering {len(drivers)} drivers with filters: {filters}")

    if not filters or not drivers:
        return drivers

    # Pre-compile filter checks for efficiency
    filter_checks = []
    for key, value in filters.items():
        if key == "age" and isinstance(value, dict):
            filter_checks.append(
                lambda d: compare_values(
                    d.get("age"), value.get("operator", ">="), value.get("value")
                )
            )
        elif key == "experience" and isinstance(value, dict):
            filter_checks.append(
                lambda d: compare_values(
                    d.get("experience", 0),
                    value.get("operator", ">="),
                    value.get("value"),
                )
            )
        elif key == "language" and isinstance(value, str):
            target_lang = value.lower()
            filter_checks.append(
                lambda d: any(
                    lang.lower() == target_lang for lang in d.get("languages", [])
                )
                or any(
                    vl.get("name", "").lower() == target_lang
                    for vl in d.get("verified_languages", [])
                    if isinstance(vl, dict)
                )
            )
        elif key == "vehicle_type" and isinstance(value, str):
            target_type = value.lower()
            filter_checks.append(
                lambda d: any(
                    target_type in v.get("type", "").lower()
                    or v.get("type", "").lower() in target_type
                    for v in d.get("vehicles", [])
                )
            )
        elif key == "is_married" and isinstance(value, bool):
            filter_checks.append(lambda d: d.get("is_married") == value)
        elif key == "is_pet_allowed" and isinstance(value, bool):
            filter_checks.append(lambda d: d.get("is_pet_allowed") == value)
        elif key == "min_connections" and isinstance(value, (int, float)):
            filter_checks.append(lambda d: d.get("connections", 0) >= value)
        elif key == "min_experience" and isinstance(value, (int, float)):
            filter_checks.append(lambda d: d.get("experience", 0) >= value)
        elif key == "max_cost_per_km" and isinstance(value, (int, float)):
            filter_checks.append(
                lambda d: any(
                    v.get("per_km_cost", float("inf")) <= value
                    for v in d.get("vehicles", [])
                )
            )

    # Filter drivers in a single list comprehension
    filtered_drivers = [
        driver for driver in drivers if all(check(driver) for check in filter_checks)
    ]

    logger.info(f"Filtering complete: {len(filtered_drivers)} drivers remaining")
    return filtered_drivers


def compare_values(driver_value: float, operator: str, target_value: float) -> bool:
    """Compare values based on operator"""
    if operator == ">":
        return driver_value > target_value
    elif operator == "<":
        return driver_value < target_value
    elif operator == ">=":
        return driver_value >= target_value
    elif operator == "<=":
        return driver_value <= target_value
    elif operator == "==":
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
        "should_fetch_new": not has_more_in_current and next_index >= total_drivers,
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
def get_driver_details(driver_id: str) -> Optional[Dict]:
    """
    Get detailed information for a specific driver.

    Args:
        driver_id: The unique ID of the driver

    Returns:
        Dictionary with detailed driver information or None if not found
    """
    logger.info(f"Getting details for driver {driver_id}")

    details = api_client.get_driver_details(driver_id)

    if not details:
        logger.warning(f"No details found for driver {driver_id}")
        return None

    # Format detailed information
    driver_details = {
        "id": driver_id,
        "name": details.get("name", "Unknown"),
        "age": details.get("age"),
        "experience": details.get("experience", 0),
        "bio": details.get("driverBio", ""),
        "city": details.get("city", ""),
        "phone": details.get("phoneNo", ""),
        "username": details.get("userName", ""),
        "connections": details.get("connections", 0),
        "is_pet_allowed": details.get("isPetAllowed", False),
        "is_married": details.get("married", False),
        "languages": details.get("languages", []),
        "verified_languages": details.get("verifiedLanguages", []),
        "trip_types": details.get("tripTypes", []),
        "routes": details.get("routes", []),
        "training_content": details.get("trainingContent", []),
        "vehicle_ownership": details.get("vehicleOwnershipDetails", []),
        "verified_vehicles": details.get("verifiedVehicles", []),
        "profile_pic": details.get("profilePic", ""),
        "membership_active": details.get("membershipActive", False),
        "aadhar_verified": details.get("aadharCardVerified", False),
        "license_verified": details.get("drivingLicenseVerified", False),
    }

    logger.info(f"Got detailed info for {driver_details['name']}")
    return driver_details
