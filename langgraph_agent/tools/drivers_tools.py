# langgraph_agent/tools/drivers_tools.py
"""Refactored driver tools for streamlined flow with proper API separation"""

import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool
from datetime import datetime, timezone
from services import api_client
import config

# Configure detailed logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@tool
def create_trip_and_check_availability(
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    customer_details: Dict[str, str],
    start_date: str,
    return_date: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Creates a trip and immediately checks driver availability based on preferences.
    This combines trip creation and availability checking into a single operation.

    Args:
        pickup_city: The city from where the trip starts. Should be a valid Indian city.
        drop_city: The city where the trip ends. Should be a valid Indian city.
        trip_type: The type of trip, must be either 'one-way' or 'round-trip'.
        customer_details: A dictionary containing customer's id, name, phone, and profile_image.
        start_date: The start date for the trip, in YYYY-MM-DD format.
        return_date: (Optional) The return date for a round-trip, in YYYY-MM-DD format.
        filters: (Optional) Driver preferences/filters like vehicle type, languages, etc.

    Returns:
        A dictionary with the operation status and details.
    """
    logger.info("="*50)
    logger.info("STARTING TRIP CREATION AND AVAILABILITY CHECK")
    logger.info(f"Route: {pickup_city} to {drop_city}")
    logger.info(f"Trip Type: {trip_type}")
    logger.info(f"Customer: {customer_details.get('name')} (ID: {customer_details.get('id')})")
    logger.info(f"Dates - Start: {start_date}, Return: {return_date}")
    logger.info(f"Filters: {filters}")
    logger.info("="*50)

    # STEP 1: CREATE THE TRIP
    logger.info("\n📝 STEP 1: Creating Trip...")

    def format_date_for_api(date_str):
        """Convert YYYY-MM-DD to ISO format with current time"""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            current_time = datetime.now(timezone.utc)
            dt_with_time = datetime(
                dt.year, dt.month, dt.day,
                current_time.hour, current_time.minute, current_time.second,
                tzinfo=timezone.utc
            )
            formatted = dt_with_time.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
            logger.info(f"  Formatted date: {date_str} -> {formatted}")
            return formatted
        except (ValueError, TypeError) as e:
            logger.error(f"  ❌ Error parsing date {date_str}: {e}")
            return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    # Format dates for API
    formatted_start_date = format_date_for_api(start_date)

    if trip_type.lower() == "round-trip":
        if not return_date:
            logger.error("  ❌ Return date missing for round-trip")
            return {
                "status": "error",
                "message": "Return date is required for a round-trip."
            }
        formatted_end_date = format_date_for_api(return_date)
    else:
        formatted_end_date = formatted_start_date

    logger.info(f"  Calling CREATE_TRIP API...")
    logger.info(f"  URL: {config.CREATE_TRIP_URL}")
    logger.info(f"  Payload: pickup={pickup_city}, drop={drop_city}, type={trip_type}")

    # Call trip creation API
    trip_data = api_client.create_trip(
        customer_details,
        pickup_city,
        drop_city,
        trip_type.lower(),
        formatted_start_date,
        formatted_end_date
    )

    if not trip_data:
        logger.error("  ❌ TRIP CREATION FAILED: No response from API")
        return {
            "status": "error",
            "message": "Failed to create the trip. Please try again in a moment."
        }

    if "tripId" not in trip_data:
        logger.error(f"  ❌ TRIP CREATION FAILED: No tripId in response: {trip_data}")
        return {
            "status": "error",
            "message": "Failed to create the trip. Please try again in a moment."
        }

    trip_id = trip_data.get("tripId")
    logger.info(f"  ✅ TRIP CREATED SUCCESSFULLY!")
    logger.info(f"  Trip ID: {trip_id}")

    # STEP 2: GET DRIVERS BASED ON FILTERS/PREFERENCES
    logger.info(f"\n🚗 STEP 2: Fetching Drivers from {pickup_city}...")

    processed_filters = process_filter_types(filters) if filters else None
    logger.info(f"  Processed filters: {processed_filters}")

    # Fetch multiple pages to get enough drivers (up to 100)
    all_drivers = []

    drivers_data = api_client.get_drivers(
            pickup_city,
            1,
            config.DRIVERS_PER_FETCH,
            processed_filters
        )
    all_drivers.extend(drivers_data)

    if not all_drivers:
        logger.warning(f"  ⚠️ NO DRIVERS FOUND for {pickup_city} with filters {processed_filters}")
        return {
            "status": "partial_success",
            "message": "Trip created but no drivers available currently. We'll notify you when drivers become available.",
            "trip_id": trip_id
        }

    logger.info(f"  ✅ Total drivers found: {len(all_drivers)}")

    # STEP 3: SEND AVAILABILITY REQUEST TO ALL FOUND DRIVERS
    logger.info(f"\n📤 STEP 3: Sending Availability Requests...")

    driver_ids = [driver["id"] for driver in all_drivers]
    logger.info(f"  Driver IDs to notify: {driver_ids[:5]}... (showing first 5 of {len(driver_ids)})")

    # Prepare trip details for availability check
    trip_details = {
        "from": pickup_city,
        "to": drop_city,
        "trip_time": datetime.now(timezone.utc).strftime("%I:%M %p"),
        "trip_start_date": datetime.strptime(start_date, "%Y-%m-%d").strftime("%m/%d/%y"),
        "trip_end_date": datetime.strptime(return_date if return_date else start_date, "%Y-%m-%d").strftime("%m/%d/%y"),
        "trip_type": trip_type,
    }

    logger.info(f"  Trip details for availability: {trip_details}")

    # Convert filters for availability API
    user_filters = {}
    if processed_filters:
        for key, value in processed_filters.items():
            if isinstance(value, bool):
                user_filters[key] = "true" if value else "false"
            else:
                user_filters[key] = value
        logger.info(f"  User filters for availability: {user_filters}")

    # Send availability request
    logger.info(f"  Calling SEND_AVAILABILITY API...")
    logger.info(f"  URL: {config.SEND_AVAILABILITY_REQUEST_URL}")
    logger.info(f"  Sending to {len(driver_ids)} drivers")

    availability_response = api_client.send_availability_request(
        trip_id,
        driver_ids,
        trip_details,
        customer_details,
        user_filters
    )

    if not availability_response:
        logger.error("  ❌ AVAILABILITY REQUEST FAILED: No response from API")
        return {
            "status": "partial_success",
            "message": f"Trip created (ID: {trip_id}) but couldn't notify drivers. Please try again.",
            "trip_id": trip_id
        }

    # Success - both trip creation and availability check completed
    logger.info("  ✅ AVAILABILITY REQUESTS SENT SUCCESSFULLY!")
    logger.info("="*50)
    logger.info("COMPLETED: TRIP CREATED AND DRIVERS NOTIFIED")
    logger.info(f"Trip ID: {trip_id}")
    logger.info(f"Drivers Notified: {len(driver_ids)}")
    logger.info("="*50)

    return {
        "status": "success",
        "message": "I have notified drivers matching your preferences. You'll receive their quotations shortly.",
        "trip_id": trip_id,
        "drivers_notified": len(driver_ids),
        "filters_applied": bool(filters)
    }


def process_filter_types(filters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process filters to ensure correct data types for API.

    Args:
        filters: Raw filter dictionary from LLM

    Returns:
        Processed filter dictionary with correct data types
    """
    logger.info("  Processing filter types...")
    processed = {}

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
                processed[key] = int(value)
                logger.info(f"    {key}: {value} -> {processed[key]} (int)")

            elif key in boolean_filters:
                if isinstance(value, bool):
                    processed[key] = value
                elif isinstance(value, str):
                    processed[key] = value.lower() in ['true', '1', 'yes', 'on']
                else:
                    processed[key] = bool(value)
                logger.info(f"    {key}: {value} -> {processed[key]} (bool)")

            elif key in string_filters:
                processed[key] = str(value)
                logger.info(f"    {key}: {value} -> {processed[key]} (str)")

            else:
                logger.warning(f"    Unknown filter type for '{key}': {type(value)}")
                processed[key] = value

        except (ValueError, TypeError) as e:
            logger.error(f"    Error processing filter '{key}' with value '{value}': {e}")
            continue

    return processed
