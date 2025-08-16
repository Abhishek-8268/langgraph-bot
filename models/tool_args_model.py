# schemas/tool_args.py
"""Pydantic models for tool arguments"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime


# ============== DRIVER SEARCH TOOL ARGS ==============
class DriverFilters(BaseModel):
    """Filters for driver search"""
    # Age filters
    min_age: Optional[int] = Field(default=None, alias="minAge")
    max_age: Optional[int] = Field(default=None, alias="maxAge")

    # Experience filters
    min_experience: Optional[int] = Field(default=None, alias="minExperience")
    min_driving_experience: Optional[int] = Field(default=None, alias="minDrivingExperience")
    min_connections: Optional[int] = Field(default=None, alias="minConnections")

    # Boolean filters
    is_pet_allowed: Optional[bool] = Field(default=None, alias="isPetAllowed")
    married: Optional[bool] = None
    profile_verified: Optional[bool] = Field(default=None, alias="profileVerified")
    verified: Optional[bool] = None
    allow_handicapped_persons: Optional[bool] = Field(default=None, alias="allowHandicappedPersons")
    available_for_customers_personal_car: Optional[bool] = Field(default=None, alias="availableForCustomersPersonalCar")
    available_for_driving_in_event_wedding: Optional[bool] = Field(default=None, alias="availableForDrivingInEventWedding")
    available_for_part_time_full_time: Optional[bool] = Field(default=None, alias="availableForPartTimeFullTime")

    # String filters
    gender: Optional[str] = None
    verified_languages: Optional[str] = Field(default=None, alias="verifiedLanguages")
    vehicle_types: Optional[str] = Field(default=None, alias="vehicleTypes")


    def to_api_params(self) -> Dict[str, Any]:
        """Convert to API parameters, removing None values"""
        params = {}
        for field_name, field_value in self:
            if field_value is not None:
                field_info = type(self).model_fields[field_name]

                # Convert booleans to strings for API
                if isinstance(field_value, bool):
                    params[field_info.alias or field_name] = "true" if field_value else "false"
                else:
                    params[field_info.alias or field_name] = field_value
        return params


class GetDriversArgs(BaseModel):
    """Arguments for get_drivers_for_city tool"""
    city: str = Field(description="The city name to search for drivers")
    page: int = Field(default=1, description="Page number for pagination")
    filters: Optional[DriverFilters] = Field(default=None, description="Optional filters to apply")


class ShowMoreDriversArgs(BaseModel):
    """Arguments for show_more_drivers tool"""
    current_index: int = Field(description="Current display index")
    total_drivers: int = Field(description="Total number of drivers available")


class RemoveFiltersArgs(BaseModel):
    """Arguments for remove_filters_from_search tool"""
    keys_to_remove: List[str] = Field(
        description='List of filter keys to remove, or ["all"] to remove all filters'
    )


class GetDriverDetailsArgs(BaseModel):
    """Arguments for get_driver_details tool"""
    driver_id: str = Field(description="The unique ID of the driver")
    drivers: Optional[List[Dict]] = Field(
        default_factory=list,
        description="Optional list of driver dictionaries to search through"
    )


# ============== TRIP CREATION TOOL ARGS ==============
class CustomerDetails(BaseModel):
    """Customer information"""
    id: str
    name: str
    phone: str
    profile_image: Optional[str] = Field(default="")


class CreateTripArgs(BaseModel):
    """Arguments for create_trip tool"""
    pickup_city: str = Field(description="The city from where the trip starts")
    drop_city: str = Field(description="The city where the trip ends")
    trip_type: str = Field(description="Type of trip: 'one-way' or 'round-trip'")
    customer_details: CustomerDetails = Field(description="Customer information")
    start_date: str = Field(description="Start date in YYYY-MM-DD format")
    return_date: Optional[str] = Field(default=None, description="Return date for round-trip in YYYY-MM-DD format")

    @field_validator('trip_type')
    @classmethod
    def validate_trip_type(cls, v: str) -> str:
        valid_types = ['one-way', 'round-trip']
        if v.lower() not in valid_types:
            raise ValueError(f"trip_type must be one of {valid_types}")
        return v.lower()

    @field_validator('start_date', 'return_date')
    @classmethod
    def validate_date_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        try:
            # Validate YYYY-MM-DD format
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError(f"Date must be in YYYY-MM-DD format, got: {v}")


# ============== AVAILABILITY CHECK TOOL ARGS ==============
class CheckAvailabilityArgs(BaseModel):
    """Arguments for check_driver_availability tool"""
    driver_ids: List[str] = Field(description="List of driver IDs to check")
    trip_id: str = Field(description="The ID of the current trip")
    pickup_location: str = Field(description="The pickup city")
    drop_location: str = Field(description="The drop-off city")
    trip_type: str = Field(description="Type of trip")
    start_date: str = Field(description="Start date in mm/dd/yy format")
    end_date: str = Field(description="End date in mm/dd/yy format")
    customer_details: CustomerDetails = Field(description="Customer information")
