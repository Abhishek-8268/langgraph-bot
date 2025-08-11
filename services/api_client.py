# services/api_client.py
"""Enhanced API client with comprehensive filtering and type safety using proper schemas"""

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
    DriversResponse,
    CustomerDetails,
    TripLocation,
    TripDetails,
    Driver,
    VehicleType,
    Gender,
    Language
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
            'User-Agent': 'CabBot/2.0',
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
    Get drivers with comprehensive filtering support using proper schemas
    
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
            # Use DriverFilters schema for validation
            try:
                validated_filters = DriverFilters(**filters)
                filter_params = validated_filters.to_api_params()
                params.update(filter_params)
                logger.info(f"Applied validated filters: {filter_params}")
            except ValidationError as e:
                logger.warning(f"Filter validation error: {e}")
                # Fallback to basic filter validation
                cleaned_filters = validate_filters_basic(filters)
                params.update(cleaned_filters)
        
        logger.info(f"Fetching drivers for {city} (page {page}, limit {limit})")
        
        # Make API request
        result = api_client._make_request("GET", config.GET_PREMIUM_DRIVERS_URL, params=params)
        
        # Validate response structure using schema
        try:
            # Note: We expect the API to return a structure like {"success": True, "data": [...]}
            # but we'll validate the drivers data using our Driver schema
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
            
        except Exception as e:
            logger.error(f"Error validating API response: {e}")
            return []
        
    except APIError as e:
        logger.error(f"API error getting drivers: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error getting drivers: {e}")
        return []


def validate_filters_basic(filters: Dict[str, Any]) -> Dict[str, Any]:
    """Basic filter validation without Pydantic"""
    if not filters:
        return {}
    
    cleaned_filters = {}
    
    for key, value in filters.items():
        try:
            # Numeric filters
            if key in ["minAge", "maxAge", "minExperience", "minDrivingExperience", "minConnections", "fraudReports"]:
                if isinstance(value, (int, str)) and str(value).isdigit():
                    age_val = int(value)
                    if key in ["minAge", "maxAge"] and (age_val < 18 or age_val > 80):
                        logger.warning(f"Age value {age_val} out of range [18-80], skipping")
                        continue
                    cleaned_filters[key] = age_val
            
            # String filters with validation
            elif key == "gender":
                if isinstance(value, str) and value.lower() in ["male", "female"]:
                    cleaned_filters[key] = value.lower()
            
            elif key == "vehicleTypes":
                if isinstance(value, str):
                    valid_types = ["sedan", "suv", "hatchback", "innova", "innovaCrysta", "tempoTraveller12Seater"]
                    vehicle_types = [vt.strip().lower() for vt in value.split(",")]
                    valid_vehicles = [vt for vt in vehicle_types if vt in valid_types]
                    if valid_vehicles:
                        cleaned_filters[key] = ",".join(valid_vehicles)
            
            elif key == "verifiedLanguages":
                if isinstance(value, str):
                    valid_languages = ["English", "Hindi", "Punjabi", "Tamil", "Telugu", "Marathi", 
                                     "Gujarati", "Bengali", "Kannada", "Malayalam", "Urdu", "Odia", "Assamese", "Nepali"]
                    languages = [lang.strip() for lang in value.split(",")]
                    valid_langs = [lang for lang in languages if lang in valid_languages]
                    if valid_langs:
                        cleaned_filters[key] = ",".join(valid_langs)
            
            # Boolean filters
            elif key in ["married", "profileVerified", "verified", "isPetAllowed", "allowHandicappedPersons",
                        "availableForCustomersPersonalCar", "availableForDrivingInEventWedding", 
                        "availableForPartTimeFullTime"]:
                if isinstance(value, bool):
                    cleaned_filters[key] = value
                elif isinstance(value, str):
                    cleaned_filters[key] = value.lower() in ['true', '1', 'yes']
            
            # Operator-based filters
            elif key in ["connections", "profileCompletionPercentage"]:
                if isinstance(value, str) and any(op in value for op in [">=", ">", "<=", "<", "="]):
                    cleaned_filters[key] = value
            
            else:
                # Pass through other filters
                cleaned_filters[key] = value
                
        except Exception as e:
            logger.warning(f"Error validating filter {key}={value}: {e}")
            continue
    
    return cleaned_filters


def create_trip(
    customer_details: Dict[str, str],
    pickup_city: str,
    drop_city: str,
    trip_type: str,
    start_date: str,
    end_date: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Create a trip with enhanced validation using schemas
    
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
        # Validate customer details using schema
        try:
            customer = CustomerDetails(
                id=customer_details.get("id"),
                name=customer_details.get("name", ""),
                phone=customer_details.get("phone", ""),
                profile_image=customer_details.get("profile_image", "")
            )
        except ValidationError as e:
            logger.error(f"Customer details validation failed: {e}")
            return None
        
        # Validate required parameters
        if not all([pickup_city, drop_city, trip_type, start_date]):
            logger.error("Missing required parameters for trip creation")
            return None
        
        # Validate trip type
        if trip_type.lower() not in ["one-way", "round-trip"]:
            logger.error(f"Invalid trip type: {trip_type}")
            return None
        
        # Create trip locations using schema
        pickup_location = TripLocation(
            city=pickup_city.strip(),
            coordinates="",
            place_name=""
        )
        
        drop_location = TripLocation(
            city=drop_city.strip(),
            coordinates="",
            place_name=""
        )
        
        # Build trip request using schema
        try:
            trip_request = CreateTripRequest(
                customerId=customer.id,
                customerName=customer.name,
                customerPhone=customer.phone,
                customerProfileImage=customer.profile_image,
                pickUpLocation=pickup_location,
                dropLocation=drop_location,
                startDate=start_date,
                endDate=end_date if trip_type.lower() == "round-trip" else start_date,
                tripType=trip_type.lower()
            )
        except ValidationError as e:
            logger.error(f"Trip request validation failed: {e}")
            return None
        
        # Convert to dict for API call
        payload = trip_request.model_dump(by_alias=True, exclude_none=True)
        
        logger.info(f"Creating trip: {pickup_city} -> {drop_city} ({trip_type})")
        logger.debug(f"Trip payload: {json.dumps(payload, indent=2)}")
        
        # Make API request
        response = api_client._make_request("POST", config.CREATE_TRIP_URL, json_data=payload)
        
        # Validate response using schema
        try:
            trip_response = CreateTripResponse(**response)
            logger.info(f"Trip created successfully: {trip_response.trip_id}")
            return trip_response.model_dump(by_alias=True)
        except ValidationError as e:
            logger.warning(f"Trip response validation failed: {e}")
            # Return raw response if schema validation fails
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
    Send availability request to drivers with enhanced validation using schemas
    
    Args:
        trip_id: ID of the trip
        driver_ids: List of driver IDs to check
        trip_details: Trip information
        customer_details: Customer information
        
    Returns:
        Availability request response or None on failure
    """
    try:
        # Validate parameters
        if not all([trip_id, driver_ids, trip_details, customer_details]):
            logger.error("Missing required parameters for availability request")
            return None
        
        if not isinstance(driver_ids, list) or not driver_ids:
            logger.error("driver_ids must be a non-empty list")
            return None
        
        # Validate trip details using schema
        try:
            trip_info = TripDetails(
                **{"from": trip_details.get("from", "")}, 
                to=trip_details.get("to", ""),
                trip_time=trip_details.get("trip_time", ""),
                trip_date=trip_details.get("trip_date", ""),
                trip_type=trip_details.get("trip_type", "")
            )
        except ValidationError as e:
            logger.error(f"Trip details validation failed: {e}")
            return None
        
        # Validate customer details
        try:
            customer = CustomerDetails(
                id=customer_details.get("id"),
                name=customer_details.get("name", ""),
                phone=customer_details.get("phone", ""),
                profile_image=customer_details.get("profile_image", "")
            )
        except ValidationError as e:
            logger.error(f"Customer details validation failed: {e}")
            return None
        
        # Build availability request using schema
        try:
            availability_request = AvailabilityRequest(
                driverIds=driver_ids,
                tripId=trip_id,
                data={
                    "trip_details": trip_info.model_dump(by_alias=True),
                    "customerDetails": {
                        "name": customer.name,
                        "id": customer.id,
                        "phoneNo": customer.phone,
                        "profile_image": customer.profile_image,
                    },
                    "message": "Please confirm your availability for this trip.",
                }
            )
        except ValidationError as e:
            logger.error(f"Availability request validation failed: {e}")
            return None
        
        # Convert to dict for API call
        payload = availability_request.model_dump(by_alias=True)
        
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
            driver_data = drivers[0]
            
            # Optionally validate using Driver schema
            try:
                validated_driver = Driver(**driver_data)
                return validated_driver.model_dump(by_alias=True, exclude_none=True)
            except ValidationError as e:
                logger.warning(f"Driver data validation failed: {e}")
                # Return raw data if validation fails
                return driver_data
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


def get_available_cities() -> List[str]:
    """Get list of available cities (mock implementation)"""
    # This would typically come from an API endpoint
    return [
        "Delhi", "Mumbai", "Bangalore", "Chennai", "Kolkata", "Hyderabad",
        "Pune", "Ahmedabad", "Jaipur", "Surat", "Lucknow", "Kanpur",
        "Nagpur", "Indore", "Thane", "Bhopal", "Visakhapatnam", "Pimpri",
        "Patna", "Vadodara", "Ghaziabad", "Ludhiana", "Agra", "Nashik"
    ]


def validate_city(city: str) -> bool:
    """Validate if city is supported"""
    if not city or not isinstance(city, str):
        return False
    
    # Basic validation - city should be non-empty string
    city = city.strip()
    if len(city) < 2:
        return False
    
    # Could add more sophisticated validation here
    return True


# Helper functions for filter interpretation
def get_filter_suggestions(partial_query: str) -> List[Dict[str, Any]]:
    """Get filter suggestions based on partial query"""
    suggestions = []
    query_lower = partial_query.lower()
    
    # Gender suggestions
    if any(word in query_lower for word in ["female", "male", "woman", "man"]):
        suggestions.append({
            "type": "gender",
            "suggestions": ["male", "female"],
            "description": "Filter drivers by gender"
        })
    
    # Vehicle suggestions
    if any(word in query_lower for word in ["car", "vehicle", "suv", "sedan"]):
        suggestions.append({
            "type": "vehicleTypes", 
            "suggestions": ["sedan", "suv", "hatchback", "innova", "innovaCrysta"],
            "description": "Filter by vehicle type"
        })
    
    # Language suggestions
    if any(word in query_lower for word in ["hindi", "english", "language", "speaking"]):
        suggestions.append({
            "type": "verifiedLanguages",
            "suggestions": ["English", "Hindi", "Punjabi", "Tamil"],
            "description": "Filter by languages spoken"
        })
    
    return suggestions


# Backward compatibility functions
def get_drivers_legacy(city: str, page: int = 1, limit: int = 20, filters: Optional[Dict] = None):
    """Legacy function for backward compatibility"""
    return get_drivers(city, page, limit, filters)


# Export commonly used functions
__all__ = [
    'get_drivers', 
    'create_trip', 
    'send_availability_request', 
    'get_driver_details',
    'test_api_connection',
    'validate_filters_basic',
    'get_available_cities',
    'validate_city',
    'get_filter_suggestions',
    'APIError',
    'APIClient'
]