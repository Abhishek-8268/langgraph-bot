# langgraph_agent/tools/drivers_tools.py
"""Enhanced driver tools with comprehensive filtering and type safety"""

import logging
import re
from typing import List, Dict, Any, Optional, Union
from langchain_core.tools import tool
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ValidationError

from services import api_client
from schemas.driver_schema import (
    DriverFilters, 
    VehicleType, 
    Gender, 
    Language,
    DriversToolResponse,
    ShowMoreDriversResponse,
    Driver
)
import config

logger = logging.getLogger(__name__)


class GetDriversInput(BaseModel):
    """Input schema for get_drivers_for_city tool"""
    city: str = Field(..., description="The city name to search for drivers (e.g., 'Delhi', 'Mumbai')")
    page: int = Field(1, ge=1, description="Page number for pagination")
    filters: Optional[Dict[str, Any]] = Field(None, description="Dictionary of filter criteria")


class DriverDetailsInput(BaseModel):
    """Input schema for get_driver_details tool"""
    driver_id: str = Field(..., description="The unique ID of the driver")
    drivers: List[Dict[str, Any]] = Field(default_factory=list, description="List of drivers to search through")


class ShowMoreInput(BaseModel):
    """Input schema for show_more_drivers tool"""
    current_index: int = Field(..., ge=0, description="Current display index")
    total_drivers: int = Field(..., ge=0, description="Total number of drivers available")


class RemoveFiltersInput(BaseModel):
    """Input schema for remove_filters_from_search tool"""
    keys_to_remove: List[str] = Field(..., description="List of filter keys to remove, or ['all'] to remove all filters")


class CreateTripInput(BaseModel):
    """Input schema for create_trip tool"""
    pickup_city: str = Field(..., description="The city from where the trip starts")
    drop_city: str = Field(..., description="The city where the trip ends")
    trip_type: str = Field(..., description="Type of trip: 'one-way' or 'round-trip'")
    customer_details: Dict[str, str] = Field(..., description="Customer information dictionary")
    return_date: Optional[str] = Field(None, description="Return date for round-trip in YYYY-MM-DD format")


class CheckAvailabilityInput(BaseModel):
    """Input schema for check_driver_availability tool"""
    driver_ids: List[str] = Field(..., description="List of driver IDs to check availability")
    trip_id: str = Field(..., description="The ID of the current trip")
    pickup_location: str = Field(..., description="The pickup city for the trip")
    drop_location: str = Field(..., description="The drop-off city for the trip")
    trip_type: str = Field(..., description="The type of trip")
    customer_details: Dict[str, str] = Field(..., description="Customer information dictionary")


def parse_filters(filters_dict: Optional[Dict[str, Any]]) -> DriverFilters:
    """Parse and validate filters from dictionary to DriverFilters model"""
    if not filters_dict:
        return DriverFilters()
    
    try:
        # Handle enum conversions
        if "gender" in filters_dict and isinstance(filters_dict["gender"], str):
            filters_dict["gender"] = filters_dict["gender"].lower()
        
        if "vehicleTypes" in filters_dict and isinstance(filters_dict["vehicleTypes"], str):
            # Validate vehicle types
            vehicle_types = [vt.strip().lower() for vt in filters_dict["vehicleTypes"].split(",")]
            valid_types = [vt for vt in vehicle_types if vt in [e.value for e in VehicleType]]
            filters_dict["vehicleTypes"] = ",".join(valid_types)
        
        if "verifiedLanguages" in filters_dict and isinstance(filters_dict["verifiedLanguages"], str):
            # Validate languages
            languages = [lang.strip() for lang in filters_dict["verifiedLanguages"].split(",")]
            valid_languages = [lang for lang in languages if lang in [e.value for e in Language]]
            filters_dict["verifiedLanguages"] = ",".join(valid_languages)
        
        return DriverFilters(**filters_dict)
    except ValidationError as e:
        logger.warning(f"Filter validation error: {e}")
        return DriverFilters()


def get_filter_description() -> str:
    """Get a comprehensive description of available filters"""
    return """
Available filters:
- gender: 'male' or 'female'
- minAge/maxAge: Age range (18-80)
- married: true/false for marital status
- profileVerified: true/false for profile verification
- verified: true/false for general verification
- minDrivingExperience: Minimum years of driving experience
- minExperience: Minimum years of overall experience
- minConnections: Minimum number of connections
- fraudReports: Maximum number of fraud reports (0 for none)
- vehicleTypes: Comma-separated list ('sedan', 'suv', 'hatchback', 'innova', 'innovaCrysta', 'tempoTraveller12Seater')
- isPetAllowed: true/false for pet-friendly drivers
- allowHandicappedPersons: true/false for accessibility
- availableForCustomersPersonalCar: true/false for personal car driving
- availableForDrivingInEventWedding: true/false for events/weddings
- availableForPartTimeFullTime: true/false for part/full time availability
- verifiedLanguages: Comma-separated languages ('English', 'Hindi', 'Punjabi', etc.)
- connections: Direct filter with operator (e.g., '>=50', '>100')
- profileCompletionPercentage: Profile completion filter (e.g., '>=80')

Example usage:
- For female drivers with SUVs who allow pets: {"gender": "female", "vehicleTypes": "suv", "isPetAllowed": true}
- For experienced Hindi-speaking drivers: {"minExperience": 5, "verifiedLanguages": "Hindi"}
- For drivers with high connections: {"connections": ">=100"}
"""


@tool(args_schema=GetDriversInput)
def get_drivers_for_city(city: str, page: int = 1, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Get drivers for a specific city with comprehensive filtering options.
    
    This tool supports extensive filtering based on demographics, experience, vehicle types,
    languages, and availability preferences. All filters are applied server-side for efficiency.

    Args:
        city: The city name to search for drivers. Must be a valid Indian city name.
        page: Page number for pagination (default: 1, minimum: 1).
        filters: Optional dictionary of filter criteria. See get_filter_description() for all options.

    Returns:
        Dictionary containing drivers list, pagination info, and metadata.
        
    Filter Examples:
        - {"gender": "female", "isPetAllowed": true} - Female pet-friendly drivers
        - {"minAge": 25, "maxAge": 40, "vehicleTypes": "suv,sedan"} - Age and vehicle filters
        - {"verifiedLanguages": "English,Hindi", "minConnections": 50} - Language and connection filters
        - {"married": true, "minExperience": 5} - Marital status and experience
    """
    logger.info(f"Getting drivers for {city} (page {page}) with filters: {filters}")

    # Parse and validate filters
    validated_filters = parse_filters(filters)
    filter_params = validated_filters.to_api_params()
    
    logger.info(f"Validated filters: {filter_params}")

    # Call API with filters
    drivers_data = api_client.get_drivers(city, page, config.DRIVERS_PER_FETCH, filter_params)

    if not drivers_data:
        logger.info(f"No drivers found in {city} with applied filters")
        return {
            "drivers": [], 
            "page": page, 
            "has_more": False, 
            "total_fetched": 0,
            "applied_filters": filter_params
        }

    # Process drivers
    processed_drivers = []
    for driver in drivers_data:
        if driver is not None:
            try:
                processed_driver = process_driver_data(driver)
                processed_drivers.append(processed_driver)
            except Exception as e:
                logger.warning(f"Error processing driver data: {e}")
                continue

    logger.info(f"Successfully processed {len(processed_drivers)} drivers with filters")

    return {
        "drivers": processed_drivers,
        "page": page,
        "has_more": len(drivers_data) == config.DRIVERS_PER_FETCH,
        "total_fetched": len(processed_drivers),
        "applied_filters": filter_params
    }


def process_driver_data(driver_data: Dict) -> Dict:
    """Process and format driver data from the API response with type safety"""
    try:
        # Process vehicles with proper validation
        vehicles = []
        verified_vehicles = driver_data.get("verifiedVehicles", [])
        
        for vehicle in verified_vehicles:
            vehicle_info = {
                "model": vehicle.get("model", "Unknown"),
                "type": vehicle.get("vehicleType", "unknown"),
                "reg_no": vehicle.get("reg_no", ""),
                "per_km_cost": float(vehicle.get("perKmCost", 0)) if vehicle.get("perKmCost") else 0.0,
                "is_commercial": bool(vehicle.get("is_commercial", False)),
                "image_url": vehicle.get("imageUrl"),
            }
            vehicles.append(vehicle_info)

        # Process languages with validation
        verified_languages = driver_data.get("verifiedLanguages", [])
        languages = [lang for lang in verified_languages if lang and isinstance(lang, str)]

        # Safely extract and convert data types
        driver_info = {
            "id": str(driver_data.get("id", "")),
            "name": driver_data.get("name") or "Unknown",
            "city": driver_data.get("city", ""),
            "phone": str(driver_data.get("phoneNo", "")),
            "username": driver_data.get("userName", ""),
            "profile_image": driver_data.get("profileImage"),
            
            # Demographics with type safety
            "age": int(driver_data["age"]) if driver_data.get("age") and str(driver_data["age"]).isdigit() else None,
            "gender": driver_data.get("gender"),
            "is_married": bool(driver_data.get("married")) if driver_data.get("married") is not None else None,
            
            # Experience and verification
            "experience": int(driver_data.get("experience", 0)),
            "driving_experience": int(driver_data.get("drivingExperience", 0)) if driver_data.get("drivingExperience") else None,
            "connections": int(driver_data.get("connections", 0)),
            "profile_verified": bool(driver_data.get("profileVerified")) if driver_data.get("profileVerified") is not None else None,
            "verified": bool(driver_data.get("verified")) if driver_data.get("verified") is not None else None,
            
            # Preferences and capabilities
            "is_pet_allowed": bool(driver_data.get("isPetAllowed")) if driver_data.get("isPetAllowed") is not None else None,
            "allow_handicapped_persons": bool(driver_data.get("allowHandicappedPersons")) if driver_data.get("allowHandicappedPersons") is not None else None,
            "available_for_customers_personal_car": bool(driver_data.get("availableForCustomersPersonalCar")) if driver_data.get("availableForCustomersPersonalCar") is not None else None,
            "available_for_driving_in_event_wedding": bool(driver_data.get("availableForDrivingInEventWedding")) if driver_data.get("availableForDrivingInEventWedding") is not None else None,
            "available_for_part_time_full_time": bool(driver_data.get("availableForPartTimeFullTime")) if driver_data.get("availableForPartTimeFullTime") is not None else None,
            
            # Professional info
            "bio": driver_data.get("driverBio", ""),
            "fraud_reports": int(driver_data.get("fraudReports", 0)),
            
            # Languages and routes
            "languages": languages,
            "verified_languages": languages,  # For backward compatibility
            "trip_types": driver_data.get("tripTypes", []),
            "routes": driver_data.get("routes", []),
            
            # Vehicle and timing info
            "vehicles": vehicles,
            "last_access": driver_data.get("lastAccess"),
        }

        return driver_info

    except Exception as e:
        logger.error(f"Error processing driver data: {e}")
        # Return minimal safe data
        return {
            "id": str(driver_data.get("id", "unknown")),
            "name": driver_data.get("name", "Unknown"),
            "city": driver_data.get("city", ""),
            "phone": str(driver_data.get("phoneNo", "")),
            "vehicles": [],
            "languages": [],
        }


@tool(args_schema=ShowMoreInput)
def show_more_drivers(current_index: int, total_drivers: int) -> Dict[str, Any]:
    """
    Show next batch of drivers from already fetched list.
    
    Manages pagination of drivers that have already been fetched, determining
    whether to show more from current batch or fetch new drivers.

    Args:
        current_index: Current display index in the drivers list
        total_drivers: Total number of drivers currently available

    Returns:
        Information about next batch and whether new fetch is needed
    """
    next_index = current_index + config.DRIVERS_PER_DISPLAY
    has_more_in_current = next_index < total_drivers

    return {
        "next_index": next_index,
        "has_more_in_current": has_more_in_current,
        "should_fetch_new": not has_more_in_current,
    }


@tool(args_schema=RemoveFiltersInput)
def remove_filters_from_search(keys_to_remove: List[str]) -> str:
    """
    Remove specified filters from the current search criteria.
    
    Allows users to remove specific filters or all filters to broaden their search.

    Args:
        keys_to_remove: List of filter keys to remove, or ["all"] to remove all filters.
                        Valid keys include: gender, minAge, maxAge, vehicleTypes, isPetAllowed, etc.

    Returns:
        Confirmation message about which filters were removed
    """
    if "all" in keys_to_remove:
        return "All filters have been removed from the search"

    return f"The following filters have been removed: {', '.join(keys_to_remove)}"


@tool(args_schema=DriverDetailsInput)
def get_driver_details(driver_id: str, drivers: List[Dict] = []) -> Optional[Dict]:
    """
    Get detailed information for a specific driver by their ID.
    
    Searches the provided list of drivers first for efficiency, then falls back 
    to an API call if the driver is not found in the current list.

    Args:
        driver_id: The unique identifier of the driver
        drivers: Optional list of driver dictionaries to search through first

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


@tool(args_schema=CheckAvailabilityInput)
def check_driver_availability(
    driver_ids: List[str],
    trip_id: str,
    pickup_location: str,
    drop_location: str,
    trip_type: str,
    customer_details: Dict[str, str],
) -> Dict[str, Any]:
    """
    Check the availability of specified drivers for the current trip.
    
    Sends availability requests to selected drivers and notifies them about the trip details.

    Args:
        driver_ids: List of driver IDs to check for availability
        trip_id: The ID of the current trip
        pickup_location: The pickup city for the trip
        drop_location: The drop-off city for the trip
        trip_type: The type of trip (e.g., 'one-way', 'round-trip')
        customer_details: Dictionary containing customer's id, name, phone, and profile_image

    Returns:
        Dictionary with the result of the availability check
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
        trip_id, driver_ids, trip_details, customer_details
    )

    if not response:
        return {"status": "error", "message": "Failed to send the availability request due to an API error."}

    return {"status": "success", "message": "Availability requests have been sent to the drivers. You will be notified shortly."}


@tool(args_schema=CreateTripInput)
def create_trip(
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    customer_details: Dict[str, str],
    return_date: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a trip with the given details. This MUST be called before searching for drivers.
    
    Creates a new trip booking in the system with customer details and trip information.
    For round-trips, a return date is required.

    Args:
        pickup_city: The city from where the trip starts (must be a valid Indian city)
        drop_city: The city where the trip ends (must be a valid Indian city)
        trip_type: Type of trip - must be either 'one-way' or 'round-trip'
        customer_details: Dictionary containing customer's id, name, phone, and profile_image
        return_date: Required for round-trip, in YYYY-MM-DD format

    Returns:
        Dictionary with trip creation status and trip ID if successful
    """
    logger.info(f"Creating trip from {pickup_city} to {drop_city} ({trip_type})")
    
    # Get the current time in UTC
    start_date_dt = datetime.now(timezone.utc)
    start_date = start_date_dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    end_date = None
    if trip_type.lower() == "round-trip":
        if not return_date:
            return {"status": "error", "message": "Return date is required for a round-trip."}
        try:
            # Parse the date and combine with a fixed time (e.g., noon) in UTC
            end_date_dt = datetime.strptime(return_date, "%Y-%m-%d")
            end_date_dt_utc = datetime(
                end_date_dt.year, end_date_dt.month, end_date_dt.day, 12, 0, 0, tzinfo=timezone.utc
            )
            end_date = end_date_dt_utc.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        except ValueError:
            return {"status": "error", "message": "Invalid return date format. Please use YYYY-MM-DD."}
    else:
        # For one-way trips, set a default end date (same as start date)
        end_date = start_date

    trip_data = api_client.create_trip(
        customer_details, pickup_city, drop_city, trip_type.lower(), start_date, end_date
    )

    if not trip_data or "tripId" not in trip_data:
        return {"status": "error", "message": "Failed to create the trip due to an API error."}

    return {
        "status": "success",
        "message": "Trip created successfully.",
        "tripId": trip_data.get("tripId"),
        "pickup_city": pickup_city,
    }


# Helper functions for filter interpretation
def interpret_user_filters(user_query: str) -> Dict[str, Any]:
    """
    Interpret natural language filter requests and convert to API parameters.
    
    This function helps the LLM understand how to convert user requests into proper filter parameters.
    
    Args:
        user_query: Natural language query from user
        
    Returns:
        Dictionary of filter parameters
        
    Examples:
        - "female drivers" -> {"gender": "female"}
        - "drivers under 30" -> {"maxAge": 30}
        - "SUV drivers" -> {"vehicleTypes": "suv"}
        - "pet friendly married drivers" -> {"isPetAllowed": true, "married": true}
        - "Hindi speaking drivers with experience" -> {"verifiedLanguages": "Hindi", "minExperience": 3}
    """
    filters = {}
    query_lower = user_query.lower()
    
    # Gender filters
    if "female" in query_lower:
        filters["gender"] = "female"
    elif "male" in query_lower and "female" not in query_lower:
        filters["gender"] = "male"
    
    # Age filters
    if "under" in query_lower or "below" in query_lower:
        age_match = re.search(r'under|below\s+(\d+)', query_lower)
        if age_match:
            filters["maxAge"] = int(age_match.group(1))
    
    if "over" in query_lower or "above" in query_lower:
        age_match = re.search(r'over|above\s+(\d+)', query_lower)
        if age_match:
            filters["minAge"] = int(age_match.group(1))
    
    # Vehicle type filters
    vehicle_keywords = {
        "suv": "suv",
        "sedan": "sedan", 
        "hatchback": "hatchback",
        "innova": "innova",
        "crysta": "innovaCrysta",
        "tempo": "tempoTraveller12Seater"
    }
    
    found_vehicles = []
    for keyword, vehicle_type in vehicle_keywords.items():
        if keyword in query_lower:
            found_vehicles.append(vehicle_type)
    
    if found_vehicles:
        filters["vehicleTypes"] = ",".join(found_vehicles)
    
    # Boolean preferences
    if "pet" in query_lower and ("allow" in query_lower or "friendly" in query_lower):
        filters["isPetAllowed"] = True
    
    if "married" in query_lower:
        filters["married"] = True
    elif "unmarried" in query_lower or "single" in query_lower:
        filters["married"] = False
    
    if "verified" in query_lower:
        filters["verified"] = True
    
    # Language filters
    language_keywords = {
        "english": "English",
        "hindi": "Hindi", 
        "punjabi": "Punjabi",
        "tamil": "Tamil",
        "telugu": "Telugu",
        "marathi": "Marathi",
        "gujarati": "Gujarati",
        "bengali": "Bengali",
        "kannada": "Kannada",
        "malayalam": "Malayalam"
    }
    
    found_languages = []
    for keyword, language in language_keywords.items():
        if keyword in query_lower:
            found_languages.append(language)
    
    if found_languages:
        filters["verifiedLanguages"] = ",".join(found_languages)
    
    # Experience filters
    if "experienced" in query_lower:
        filters["minExperience"] = 5
    elif "experience" in query_lower:
        exp_match = re.search(r'(\d+)\s*(?:year|yr).*experience', query_lower)
        if exp_match:
            filters["minExperience"] = int(exp_match.group(1))
    
    return filters