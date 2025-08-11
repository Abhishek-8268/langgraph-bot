# services/api_client.py
"""Enhanced API client with comprehensive filtering and type safety"""

import requests
from typing import List, Dict, Any, Optional, Union
import logging
from datetime import datetime, timezone
import json
from pydantic import BaseModel, ValidationError

from schemas.driver_schema import (
    DriverFilters, 
    CreateTripRequest, 
    CreateTripResponse,
    AvailabilityRequest,
    DriversResponse
)
import config

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Custom exception for API errors"""
    def __init__(self, status_code: int, message: str, response_data: Optional[Dict] = None):
        self.status_code = status_code
        self.message = message
        self.response_data = response_data
        super().__init__(f"API Error {status_code}: {message}")


class APIClient:
    """Enhanced API client with type safety and comprehensive error handling"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.timeout = 30
        # Add retry logic headers
        self.session.headers.update({
            'User-Agent': 'CabBot/1.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
    
    def _make_request(
        self, 
        method: str, 
        url: str, 
        params: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """Make HTTP request with comprehensive error handling"""
        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                timeout=timeout
            )
            
            # Log request details
            logger.debug(f"{method} {url} - Status: {response.status_code}")
            if params:
                logger.debug(f"Params: {params}")
            if json_data:
                logger.debug(f"JSON data: {json.dumps(json_data, indent=2)}")
            
            # Handle different status codes
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 400:
                error_data = response.json() if response.content else {}
                raise APIError(400, "Bad Request - Invalid parameters", error_data)
            elif response.status_code == 401:
                raise APIError(401, "Unauthorized - Check API credentials")
            elif response.status_code == 403:
                raise APIError(403, "Forbidden - Access denied")
            elif response.status_code == 404:
                raise APIError(404, "Not Found - Endpoint or resource not found")
            elif response.status_code == 429:
                raise APIError(429, "Too Many Requests - Rate limit exceeded")
            elif response.status_code >= 500:
                raise APIError(response.status_code, f"Server Error - {response.reason}")
            else:
                raise APIError(response.status_code, f"Unexpected status code: {response.status_code}")
                
        except requests.exceptions.ConnectTimeout:
            logger.error(f"Connection timeout for {url}")
            raise APIError(0, "Connection timeout - Server took too long to respond")
        except requests.exceptions.ReadTimeout:
            logger.error(f"Read timeout for {url}")
            raise APIError(0, "Read timeout - Server response took too long")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error for {url}: {e}")
            raise APIError(0, "Connection error - Unable to reach server")
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {url}: {e}")
            raise APIError(0, f"Request error: {str(e)}")
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response from {url}")
            raise APIError(0, "Invalid JSON response from server")


# Create singleton instance
api_client = APIClient()


def get_drivers(
    city: str,
    page: int = 1,
    limit: int = config.DRIVERS_PER_FETCH,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Get drivers with comprehensive filtering support
    
    Args:
        city: Target city for driver search
        page: Page number for pagination
        limit: Number of drivers per page
        filters: Dictionary of filter parameters
        
    Returns:
        List of driver dictionaries
    """
    try:
        # Build parameters
        params = {
            "city": city.strip(),
            "page": max(1, page),
            "limit": min(max(1, limit), 100),  # Ensure reasonable limits
        }
        
        # Add filters if provided
        if filters:
            # Validate and clean filters
            validated_filters = validate_filters(filters)
            params.update(validated_filters)
        
        logger.info(f"Fetching drivers for {city} (page {page}, limit {limit})")
        if filters:
            logger.info(f"Applied filters: {filters}")
        
        # Make API request
        result = api_client._make_request("GET", config.GET_PREMIUM_DRIVERS_URL, params=params)
        
        # Validate response structure
        if not isinstance(result, dict):
            logger.error("API response is not a dictionary")
            return []
        
        if not result.get("success", False):
            logger.warning(f"API returned success=false for city {city}")
            error_msg = result.get("message", "Unknown error")
            logger.warning(f"API error message: {error_msg}")
            return []
        
        drivers_data = result.get("data", [])
        if not isinstance(drivers_data, list):
            logger.error("API data field is not a list")
            return []
        
        logger.info(f"Successfully fetched {len(drivers_data)} drivers for {city}")
        return drivers_data
        
    except APIError as e:
        logger.error(f"API error getting drivers: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting drivers: {e}")
        return []


def validate_filters(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and clean filter parameters"""
    if not filters:
        return {}
    
    try:
        # Create DriverFilters instance for validation
        driver_filters = DriverFilters(**filters)
        return driver_filters.to_api_params()
    except ValidationError as e:
        logger.warning(f"Filter validation failed: {e}")
        # Return cleaned filters, removing invalid ones
        cleaned_filters = {}
        for key, value in filters.items():
            try:
                # Basic type validation
                if key in ["minAge", "maxAge", "minExperience", "minDrivingExperience", "minConnections", "fraudReports"]:
                    if isinstance(value, (int, str)) and str(value).isdigit():
                        cleaned_filters[key] = int(value)
                elif key in ["gender", "vehicleTypes", "verifiedLanguages", "connections", "profileCompletionPercentage"]:
                    if isinstance(value, str) and value.strip():
                        cleaned_filters[key] = value.strip()
                elif key in ["married", "profileVerified", "verified", "isPetAllowed", "allowHandicappedPersons",
                           "availableForCustomersPersonalCar", "availableForDrivingInEventWedding", 
                           "availableForPartTimeFullTime"]:
                    if isinstance(value, (bool, str)):
                        if isinstance(value, str):
                            cleaned_filters[key] = value.lower() in ['true', '1', 'yes']
                        else:
                            cleaned_filters[key] = bool(value)
                else:
                    cleaned_filters[key] = value
            except Exception:
                logger.warning(f"Skipping invalid filter: {key}={value}")
                continue
        
        return cleaned_filters
    except Exception as e:
        logger.error(f"Error validating filters: {e}")
        return {}


def create_trip(
    customer_details: Dict[str, str],
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    start_date: str,
    end_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Create a trip with enhanced validation and error handling
    
    Args:
        customer_details: Customer information
        pickup_city: Pickup location city
        drop_city: Drop-off location city  
        trip_type: Type of trip ('one-way' or 'round-trip')
        start_date: Trip start date in ISO format
        end_date: Trip end date in ISO format (required for round-trip)
        
    Returns:
        Trip creation response or None on failure
    """
    try:
        # Validate required parameters
        if not all([pickup_city, drop_city, trip_type, start_date]):
            logger.error("Missing required parameters for trip creation")
            return None
        
        if not customer_details or not customer_details.get("id"):
            logger.error("Customer details are required for trip creation")
            return None
        
        # Validate trip type
        if trip_type.lower() not in ["one-way", "round-trip"]:
            logger.error(f"Invalid trip type: {trip_type}")
            return None
        
        # Build trip payload
        payload = {
            "customerId": customer_details.get("id"),
            "customerName": customer_details.get("name", ""),
            "customerPhone": customer_details.get("phone", ""),
            "customerProfileImage": customer_details.get("profile_image", ""),
            "pickUpLocation": {
                "city": pickup_city.strip(),
                "coordinates": "",
                "placeName": "",
            },
            "dropLocation": {
                "city": drop_city.strip(),
                "coordinates": "",
                "placeName": "",
            },
            "startDate": start_date,
            "tripType": trip_type.lower(),
        }
        
        # Add end date for round trips
        if trip_type.lower() == "round-trip":
            if not end_date:
                logger.error("End date is required for round-trip")
                return None
            payload["endDate"] = end_date
        
        logger.info(f"Creating trip: {pickup_city} -> {drop_city} ({trip_type})")
        logger.debug(f"Trip payload: {json.dumps(payload, indent=2)}")
        
        # Make API request
        response = api_client._make_request("POST", config.CREATE_TRIP_URL, json_data=payload)
        
        # Validate response
        if not isinstance(response, dict):
            logger.error("Invalid response format from create trip API")
            return None
        
        if "tripId" not in response:
            logger.warning("Trip ID not found in response")
            logger.debug(f"Response: {response}")
        
        logger.info(f"Trip created successfully: {response.get('tripId', 'Unknown ID')}")
        return response
        
    except APIError as e:
        logger.error(f"API error creating trip: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error creating trip: {e}")
        return None


def send_availability_request(
    trip_id: str,
    driver_ids: List[str],
    trip_details: Dict[str, Any],
    customer_details: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Send availability request to drivers with enhanced validation
    
    Args:
        trip_id: ID of the trip
        driver_ids: List of driver IDs to check
        trip_details: Trip information
        customer_details: Customer information
        
    Returns:
        Availability request response or None on failure
    """
    try:
        # Validate required parameters
        if not all([trip_id, driver_ids, trip_details, customer_details]):
            logger.error("Missing required parameters for availability request")
            return None
        
        if not isinstance(driver_ids, list) or not driver_ids:
            logger.error("driver_ids must be a non-empty list")
            return None
        
        # Validate trip details structure
        required_trip_fields = ["from", "to", "trip_time", "trip_date", "trip_type"]
        for field in required_trip_fields:
            if field not in trip_details:
                logger.error(f"Missing required trip detail: {field}")
                return None
        
        # Build availability request payload
        payload = {
            "driverIds": driver_ids,
            "tripId": trip_id,
            "data": {
                "trip_details": trip_details,
                "customerDetails": {
                    "name": customer_details.get("name", ""),
                    "id": customer_details.get("id", ""),
                    "phoneNo": customer_details.get("phone", ""),
                    "profile_image": customer_details.get("profile_image", ""),
                },
                "message": "Please confirm your availability for this trip.",
            },
        }
        
        logger.info(f"Sending availability request for trip {trip_id} to {len(driver_ids)} drivers")
        logger.debug(f"Availability payload: {json.dumps(payload, indent=2)}")
        
        # Make API request
        response = api_client._make_request(
            "POST", 
            config.SEND_AVAILABILITY_REQUEST_URL, 
            json_data=payload
        )
        
        logger.info(f"Availability request sent successfully for trip {trip_id}")
        return response
        
    except APIError as e:
        logger.error(f"API error sending availability request: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error sending availability request: {e}")
        return None


def get_driver_details(driver_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed information for a specific driver
    
    Args:
        driver_id: The driver's unique identifier
        
    Returns:
        Driver details or None if not found
    """
    try:
        if not driver_id or not driver_id.strip():
            logger.error("Driver ID is required")
            return None
        
        # Use the existing get_drivers function with ID filter
        drivers = get_drivers(city="", limit=1, filters={"id": driver_id.strip()})
        
        if drivers:
            logger.info(f"Found details for driver {driver_id}")
            return drivers[0]
        else:
            logger.warning(f"No details found for driver {driver_id}")
            return None
            
    except Exception as e:
        logger.error(f"Error getting driver details: {e}")
        return None


def test_api_connection() -> bool:
    """Test API connectivity and basic functionality"""
    try:
        # Test with a simple request
        response = api_client._make_request("GET", config.GET_PREMIUM_DRIVERS_URL, params={
            "city": "Delhi",
            "limit": 1
        })
        
        if isinstance(response, dict) and "success" in response:
            logger.info("API connection test successful")
            return True
        else:
            logger.warning("API connection test failed - unexpected response format")
            return False
            
    except Exception as e:
        logger.error(f"API connection test failed: {e}")
        return False


# Backward compatibility - keep existing function signatures
def get_drivers_legacy(city: str, page: int = 1, limit: int = 20, filters: Optional[Dict] = None):
    """Legacy function for backward compatibility"""
    return get_drivers(city, page, limit, filters)