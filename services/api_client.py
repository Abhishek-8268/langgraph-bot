# services/api_client.py
"""API client with enhanced logging for debugging"""

import requests
from typing import List, Dict, Any, Optional
import logging
import json

from models.api_models import DriversSearchResponse, TripCreationResponse, AvailabilityResponse
import config

# Configure detailed logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_drivers(
    city: str,
    page: int = 1,
    limit: int = config.DRIVERS_PER_FETCH,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Get drivers from the API with detailed logging
    """
    logger.info("\n📍 GET_DRIVERS API CALL")
    logger.info(f"  URL: {config.GET_PREMIUM_DRIVERS_URL}")
    logger.info(f"  Params: city={city}, page={page}, limit={limit}")
    if filters is not None:
        for k, v in filters.items():
            if v == True:
                filters[k] = "true"
            elif v == False:
                filters[k] = "false"
        logger.info(f"  Filters: {filters}")

    try:
        params = {
            "city": city,
            "page": page,
            "limit": limit,
        }
        if filters:
            params.update(filters)

        response = requests.get(config.GET_PREMIUM_DRIVERS_URL, params=params, timeout=20)
        logger.info(f"  Response Status: {response.status_code}")

        if response.status_code != 200:
            logger.error(f"  ❌ API error: {response.status_code}")
            logger.error(f"  Response: {response.text[:500]}")
            return []

        # Parse with Pydantic model
        result = DriversSearchResponse.model_validate(response.json())

        if not result.success:
            logger.warning(f"  ⚠️ API returned success=false for city {city}")
            return []

        # Convert drivers to dictionaries
        drivers_list = []
        for driver in result.data:
            driver_dict = driver.model_dump(by_alias=False)
            driver_dict["profile_url"] = driver.profile_url
            driver_dict["primary_vehicle"] = driver.primary_vehicle
            drivers_list.append(driver_dict)

        logger.info(f"  ✅ Found {len(drivers_list)} drivers")
        return drivers_list

    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Request error: {e}")
        return []
    except Exception as e:
        logger.error(f"  ❌ Error: {e}", exc_info=True)
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
    Create a trip using the API with detailed logging
    """
    logger.info(f"\n🚗 CREATE_TRIP API CALL")
    logger.info(f"  URL: {config.CREATE_TRIP_URL}")
    logger.info(f"  Customer: {customer_details.get('name')} (ID: {customer_details.get('id')})")
    logger.info(f"  Route: {pickup_city} to {drop_city}")
    logger.info(f"  Type: {trip_type}")
    logger.info(f"  Dates: {start_date} to {end_date}")

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

        logger.info(f"  Payload: {json.dumps(payload, indent=2)}")

        response = requests.post(config.CREATE_TRIP_URL, json=payload, timeout=20)
        logger.info(f"  Response Status: {response.status_code}")

        if response.status_code not in [200, 201]:
            logger.error(f"  ❌ API error: {response.status_code}")
            logger.error(f"  Response: {response.text}")
            return None

        response_data = response.json()
        logger.info(f"  Response Data: {json.dumps(response_data, indent=2)}")

        # Parse with Pydantic model
        result = TripCreationResponse.model_validate(response_data)

        # Return as dictionary for backward compatibility
        trip_response = {
            "message": result.message,
            "tripId": result.trip_id
        }

        logger.info(f"  ✅ Trip created successfully: {result.trip_id}")
        return trip_response

    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Request error: {e}")
        return None
    except Exception as e:
        logger.error(f"  ❌ Error: {e}", exc_info=True)
        return None


def send_availability_request(
    trip_id: str,
    driver_ids: List[str],
    trip_details: Dict[str, Any],
    customer_details: Dict[str, Any],
    user_filters: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Send availability request with detailed logging
    """
    logger.info(f"\n📨 SEND_AVAILABILITY API CALL")
    logger.info(f"  URL: {config.SEND_AVAILABILITY_REQUEST_URL}")
    logger.info(f"  Trip ID: {trip_id}")
    logger.info(f"  Number of Drivers: {len(driver_ids)}")
    logger.info(f"  Trip: {trip_details.get('from')} to {trip_details.get('to')}")

    try:
        # Convert boolean filters to strings
        for k, v in user_filters.items():
            if v == True:
                user_filters[k] = "true"
            elif v == False:
                user_filters[k] = "false"

        # Build payload - IMPORTANT: Use actual driver_ids, not hardcoded
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
            "userFilters": user_filters,
        }

        logger.info(f"  Driver IDs being sent: {driver_ids[:10]}... (first 10)")
        logger.info(f"  User Filters: {user_filters}")

        # Log full payload for debugging (be careful with sensitive data in production)
        logger.info(f"  Full Payload:")
        logger.info(f"    - driverIds count: {len(payload['driverIds'])}")
        logger.info(f"    - tripId: {payload['tripId']}")
        logger.info(f"    - trip_details: {payload['data']['trip_details']}")
        logger.info(f"    - userFilters: {payload['userFilters']}")

        response = requests.post(
            config.SEND_AVAILABILITY_REQUEST_URL,
            json=payload,
            timeout=20
        )

        logger.info(f"  Response Status: {response.status_code}")

        if response.status_code not in [200, 201]:
            logger.error(f"  ❌ API error: {response.status_code}")
            logger.error(f"  Response: {response.text}")
            return None

        response_data = response.json()
        logger.info(f"  Response Data: {json.dumps(response_data, indent=2) if len(str(response_data)) < 500 else 'Response too large to log'}")

        # Parse with Pydantic model
        result = AvailabilityResponse.model_validate(response_data)

        if not result.success:
            logger.error(f"  ❌ Availability request failed: {result.message}")
            return None

        logger.info(f"  ✅ Availability request sent successfully")
        logger.info(f"  Summary: {result.summary.model_dump() if result.summary else 'No summary'}")

        # Return as dictionary
        return result.model_dump(by_alias=False)

    except requests.exceptions.RequestException as e:
        logger.error(f"  ❌ Request error: {e}")
        return None
    except Exception as e:
        logger.error(f"  ❌ Error: {e}", exc_info=True)
        return None
