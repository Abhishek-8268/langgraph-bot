# services/api_client.py
"""Simple API client for driver endpoints"""

import requests
from typing import List, Dict, Any, Optional
import logging
from datetime import datetime, timezone

import config

logger = logging.getLogger(__name__)


def get_drivers(
    city: str,
    page: int = 1,
    limit: int = config.DRIVERS_PER_FETCH,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Get drivers from the new single API endpoint"""
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

        result = response.json()
        if not result.get("success", False):
            logger.warning(f"API returned success=false for city {city}")
            return []

        return result.get("data", [])

    except Exception as e:
        logger.error(f"Error getting drivers from new API: {e}")
        return []


def create_trip(
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    start_date: str,
    end_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Create a trip using the new API endpoint with the updated payload."""
    try:
        payload = {
            "customerId": "69",
            "customerName": "tester",
            "customerPhone": "69696696969696",
            "customerProfileImage": "",
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

        return response.json()

    except Exception as e:
        logger.error(f"Error calling create_trip API: {e}")
        return None