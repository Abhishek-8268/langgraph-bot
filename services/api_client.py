# services/api_client.py
"""Simple API client for driver endpoints"""

import requests
from typing import List, Dict, Any, Optional
import logging

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