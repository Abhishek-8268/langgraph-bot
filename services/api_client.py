# services/api_client.py
"""API client with Pydantic model support"""

import requests
from typing import List, Dict, Any, Optional
import logging
import json

from models.api_models import DriversSearchResponse, TripCreationResponse, AvailabilityResponse
import config

logger = logging.getLogger(__name__)


def get_drivers(
    city: str,
    page: int = 1,
    limit: int = config.DRIVERS_PER_FETCH,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Get drivers from the API with Pydantic validation

    Returns list of driver dictionaries for backward compatibility
    """
    try:
        params = {
            "city": city,
            "page": page,
            "limit": limit,
        }
        if filters:
            params.update(filters)

        response = requests.get(config.GET_PREMIUM_DRIVERS_URL, params=params, timeout=20)

        if response.status_code != 200:
            logger.error(f"API error: {response.status_code} - {response.text}")
            return []

        # Parse with Pydantic model
        result = DriversSearchResponse.model_validate(response.json())

        if not result.success:
            logger.warning(f"API returned success=false for city {city}")
            return []

        # Convert drivers to dictionaries for backward compatibility
        # But now they're validated and have computed fields like profile_url
        drivers_list = []
        for driver in result.data:
            driver_dict = driver.model_dump(by_alias=False)
            # Add the computed profile_url
            driver_dict["profile_url"] = driver.profile_url
            # Add primary vehicle info
            driver_dict["primary_vehicle"] = driver.primary_vehicle
            drivers_list.append(driver_dict)

        return drivers_list

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error getting drivers: {e}")
        return []
    except Exception as e:
        logger.error(f"Error getting drivers from API: {e}")
        return []


def create_trip(
    customer_details: Dict[str, str],
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    start_date: str,
    end_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Create a trip using the API with Pydantic validation
    """
    try:
        payload = {
            "customerId": customer_details.get("id"),
            "customerName": customer_details.get("name"),
            "customerPhone": customer_details.get("phone"),
            "customerProfileImage": customer_details.get("profile_image", ""),
            "pickUpLocation": {
                "city": pickup_city,
                "coordinates": "",
                "placeName": "",
            },
            "dropLocation": {
                "city": drop_city,
                "coordinates": "",
                "placeName": "",
            },
            "startDate": start_date,
            "tripType": trip_type,
        }
        if end_date:
            payload["endDate"] = end_date

        response = requests.post(config.CREATE_TRIP_URL, json=payload, timeout=20)

        if response.status_code not in [200, 201]:
            logger.error(f"API error creating trip: {response.status_code} - {response.text}")
            return None

        # Parse with Pydantic model
        result = TripCreationResponse.model_validate(response.json())

        # Return as dictionary for backward compatibility
        return {
            "message": result.message,
            "tripId": result.trip_id
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error creating trip: {e}")
        return None
    except Exception as e:
        logger.error(f"Error calling create_trip API: {e}")
        return None


def send_availability_request(
    trip_id: str,
    driver_ids: List[str],
    trip_details: Dict[str, Any],
    customer_details: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Send availability request with Pydantic validation
    """
    try:
        # Use the actual driver_ids passed, not hardcoded ones
        payload = {
            "driverIds": ["NewcOnEO5DdiDkhKwc8LjGapICB3"],
            "data": {
                "trip_details": trip_details,
                "customerDetails": {
                    "name": customer_details.get("name"),
                    "id": customer_details.get("id"),
                    "phoneNo": customer_details.get("phone"),
                    "profile_image": customer_details.get("profile_image", ""),
                },
                "message": "Please confirm your availability for this trip.",
            },
            "tripId": trip_id,
        }

        logger.info(f"Sending availability request. Trip ID: {trip_id}")
        logger.info(f"Driver IDs: {driver_ids}")
        logger.debug(f"Payload: {json.dumps(payload, indent=2)}")

        response = requests.post(
            config.SEND_AVAILABILITY_REQUEST_URL,
            json=payload,
            timeout=20
        )

        if response.status_code not in [200, 201]:
            logger.error(
                f"API error sending availability request: {response.status_code} - {response.text}"
            )
            return None

        # Parse with Pydantic model
        result = AvailabilityResponse.model_validate(response.json())

        if not result.success:
            logger.error(f"Availability request failed: {result.message}")
            return None

        logger.info(f"Availability request sent successfully for Trip ID: {trip_id}")

        # Return as dictionary for backward compatibility
        return result.model_dump(by_alias=False)

    except requests.exceptions.RequestException as e:
        logger.error(f"Request error sending availability: {e}")
        return None
    except Exception as e:
        logger.error(f"Error sending availability request: {e}")
        return None
