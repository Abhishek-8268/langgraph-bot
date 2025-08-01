# services/api_client.py
"""Simple API client for driver endpoints"""

import time
import requests
from typing import List, Dict, Any, Optional
import logging

import config

logger = logging.getLogger(__name__)


def get_premium_drivers(
    city: str, page: int = 1, limit: int = config.DRIVERS_PER_FETCH
) -> List[Dict[str, Any]]:
    """Get premium drivers from API"""
    try:
        data = {
            "city": city,
            "page": page,
            "limit": limit,
            "timestamp": int(time.time()),
        }

        response = requests.post(config.GET_DRIVERS_URL, data=data, timeout=15)

        if response.status_code != 200:
            logger.error(f"API error: {response.status_code}")
            return []

        result = response.json()
        if not result.get("success", False):
            return []

        return result.get("data", [])

    except Exception as e:
        logger.error(f"Error getting drivers: {e}")
        return []


def get_driver_details(driver_id: str) -> Optional[Dict[str, Any]]:
    """Get driver details from API"""
    try:
        data = {"partnerId": driver_id, "timestamp": int(time.time())}

        response = requests.post(config.GET_PARTNER_DATA_URL, data=data, timeout=10)

        if response.status_code != 200:
            return None

        result = response.json()
        if not result.get("success", False):
            return None

        return result.get("data", {})

    except Exception as e:
        logger.error(f"Error getting driver details: {e}")
        return None
