# langgraph_agent/tools/drivers_tools.py
"""Driver tools for the agent"""

import logging
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.tools import tool

from services import api_client

logger = logging.getLogger(__name__)


@tool
def get_drivers_for_city(city: str, page: int = 1, limit: int = 10) -> List[Dict]:
    """
    Get drivers for a specific city with full details.

    Args:
        city: The city name to search for drivers
        page: Page number for pagination (default: 1)
        limit: Number of drivers per page (default: 10)

    Returns:
        List of driver dictionaries with complete information
    """
    logger.info(f"Getting drivers for {city} (page {page})")

    # Get premium drivers
    premium_drivers = api_client.get_premium_drivers(city, page, limit)

    if not premium_drivers:
        logger.info(f"No drivers found in {city}")
        return []

    logger.info(f"Found {len(premium_drivers)} premium drivers, fetching details...")

    # Fetch details in parallel
    drivers_with_details = []

    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        future_to_driver = {
            executor.submit(fetch_driver_details, driver): driver
            for driver in premium_drivers
        }

        # Collect results
        for future in as_completed(future_to_driver, timeout=25):
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
    return drivers_with_details


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
    if photos and photos[0].get("full", {}).get("url"):
        profile_image = photos[0]["full"]["url"]

    # Process vehicles
    vehicles = []
    for vehicle in premium_driver.get("verifiedVehicles", []):
        # Get vehicle image
        image_url = None
        if vehicle.get("images"):
            try:
                first_image = vehicle["images"][0]
                image_url = first_image.get("full", {}).get("url")
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

    # Work with a copy to preserve original data
    filtered_drivers = []

    for driver in drivers:
        # Check each filter
        passes_all_filters = True

        for filter_key, filter_value in filters.items():
            if filter_key == "age" and isinstance(filter_value, dict):
                operator = filter_value.get("operator", ">=")
                value = filter_value.get("value")
                if value is not None:
                    driver_age = driver.get("age")
                    if driver_age is None or not compare_values(
                        driver_age, operator, value
                    ):
                        passes_all_filters = False
                        break

            elif filter_key == "experience" and isinstance(filter_value, dict):
                operator = filter_value.get("operator", ">=")
                value = filter_value.get("value")
                if value is not None:
                    driver_exp = driver.get("experience", 0)
                    if not compare_values(driver_exp, operator, value):
                        passes_all_filters = False
                        break

            elif filter_key == "language" and isinstance(filter_value, str):
                target_lang = filter_value.lower()
                languages = driver.get("languages", [])
                if not any(lang.lower() == target_lang for lang in languages):
                    passes_all_filters = False
                    break

            elif filter_key == "vehicle_type" and isinstance(filter_value, str):
                target_type = filter_value.lower()
                vehicles = driver.get("vehicles", [])
                if not any(v.get("type", "").lower() == target_type for v in vehicles):
                    passes_all_filters = False
                    break

            elif filter_key == "is_married" and isinstance(filter_value, bool):
                if driver.get("is_married") != filter_value:
                    passes_all_filters = False
                    break

            elif filter_key == "is_pet_allowed" and isinstance(filter_value, bool):
                if driver.get("is_pet_allowed") != filter_value:
                    passes_all_filters = False
                    break

            elif filter_key == "min_connections" and isinstance(
                filter_value, (int, float)
            ):
                if driver.get("connections", 0) < filter_value:
                    passes_all_filters = False
                    break

            elif filter_key == "min_experience" and isinstance(
                filter_value, (int, float)
            ):
                if driver.get("experience", 0) < filter_value:
                    passes_all_filters = False
                    break

            elif filter_key == "max_cost_per_km" and isinstance(
                filter_value, (int, float)
            ):
                vehicles = driver.get("vehicles", [])
                has_affordable = any(
                    v.get("per_km_cost", float("inf")) <= filter_value for v in vehicles
                )
                if not has_affordable:
                    passes_all_filters = False
                    break

        # If driver passes all filters, add to results with full data
        if passes_all_filters:
            filtered_drivers.append(driver)

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
