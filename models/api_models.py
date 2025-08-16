# schemas/api_models.py
"""Pydantic models for API responses and requests"""

from pydantic import BaseModel, Field, ConfigDict, computed_field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


# ============== ENUMS ==============
class TripType(str, Enum):
    ONE_WAY = "one-way"
    ROUND_TRIP = "round-trip"


class SearchStrategy(str, Enum):
    CITY = "city"
    GEO = "geo"
    HYBRID = "hybrid"


# ============== DRIVER API MODELS ==============
class VehicleImage(BaseModel):
    """Vehicle image URLs"""
    model_config = ConfigDict(extra="ignore")

    url: str
    type: Optional[str] = None


class VehicleImageSet(BaseModel):
    """Set of vehicle images in different sizes"""
    model_config = ConfigDict(extra="ignore")

    thumb: Optional[VehicleImage] = None
    full: Optional[VehicleImage] = None
    mob: Optional[VehicleImage] = None
    verified: Optional[bool] = False
    error_message: Optional[str] = Field(default="", alias="errorMessage")
    type: Optional[str] = None


class Vehicle(BaseModel):
    """Vehicle information"""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    reg_no: str = Field(alias="reg_no")
    model: str
    vehicle_type: str = Field(alias="vehicleType")
    per_km_cost: float = Field(alias="perKmCost")
    is_commercial: Optional[bool] = Field(default=False, alias="is_commercial")
    images: List[VehicleImageSet] = Field(default_factory=list)

    @property
    def primary_image_url(self) -> Optional[str]:
        """Get the first available vehicle image URL"""
        if self.images:
            first_image = self.images[0]
            if first_image.mob:
                return first_image.mob.url
            elif first_image.full:
                return first_image.full.url
            elif first_image.thumb:
                return first_image.thumb.url
        return None


class PhotoSet(BaseModel):
    """Driver photo set"""
    model_config = ConfigDict(extra="ignore")

    mob: Optional[VehicleImage] = None
    thumb: Optional[VehicleImage] = None
    full: Optional[VehicleImage] = None
    verified: Optional[bool] = False
    error_message: Optional[str] = Field(default="", alias="errorMessage")


class Membership(BaseModel):
    """Driver membership details"""
    model_config = ConfigDict(extra="ignore")

    plan: Optional[str] = None
    duration: Optional[int] = None
    end_date: Optional[datetime] = Field(default=None, alias="endDate")


class Driver(BaseModel):
    """Complete driver information from API"""
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    # Basic Information
    id: str
    name: str
    phone_no: str = Field(alias="phoneNo")
    username: str = Field(alias="userName")
    city: Optional[str] = None
    profile_image: Optional[str] = Field(default=None, alias="profileImage")

    # Arrays
    photos: List[PhotoSet] = Field(default_factory=list)
    verified_vehicles: List[Vehicle] = Field(default_factory=list, alias="verifiedVehicles")
    notification_locations: List[str] = Field(default_factory=list, alias="notificationLocations")
    from_top_routes: List[str] = Field(default_factory=list, alias="fromTopRoutes")
    to_top_routes: List[str] = Field(default_factory=list, alias="toTopRoutes")
    verified_languages: List[str] = Field(default_factory=list, alias="verifiedLanguages")

    # Timestamps
    last_access: Optional[int] = Field(default=None, alias="lastAccess")
    location_updated_at: Optional[str] = Field(default=None, alias="locationUpdatedAt")

    # Boolean fields
    is_pet_allowed: bool = Field(default=False, alias="isPetAllowed")
    verified: bool = Field(default=False)
    profile_verified: bool = Field(default=False, alias="profileVerified")
    premium_driver: bool = Field(default=False, alias="premiumDriver")
    allow_handicapped_persons: bool = Field(default=False, alias="allowHandicappedPersons")
    available_for_customers_personal_car: bool = Field(default=False, alias="availableForCustomersPersonalCar")
    available_for_driving_in_event_wedding: bool = Field(default=False, alias="availableForDrivingInEventWedding")
    available_for_part_time_full_time: bool = Field(default=False, alias="availableForPartTimeFullTime")
    married: bool = Field(default=False)

    # Numeric fields
    age: Optional[int] = None
    connections: int = Field(default=0)
    experience: int = Field(default=0)
    driving_license_experience: int = Field(default=0, alias="drivingLicenseExperience")
    profile_completion_percentage: int = Field(default=0, alias="profileCompletionPercentage")
    fraud_reports: int = Field(default=0, alias="fraudReports")

    # String fields
    gender: Optional[str] = None
    identity: Optional[str] = None
    driver_id: Optional[str] = Field(default=None, alias="driverId")

    # Complex fields
    membership: Optional[Membership] = None
    current_location: Optional[List[float]] = Field(default=None, alias="currentLocation")

    # URLs
    qr_code_url: Optional[str] = Field(default=None, alias="qrCodeUrl")

    @computed_field
    @property
    def profile_url(self) -> str:
        """Generate profile URL from username"""
        return f"https://cabswale.ai/profile/{self.username}" if self.username else ""

    @computed_field
    @property
    def primary_vehicle(self) -> Optional[Dict[str, Any]]:
        """Get the primary (cheapest) vehicle"""
        if not self.verified_vehicles:
            return None

        # Sort by cost and return the first
        sorted_vehicles = sorted(self.verified_vehicles, key=lambda v: v.per_km_cost)
        vehicle = sorted_vehicles[0]

        return {
            "model": vehicle.model,
            "type": vehicle.vehicle_type,
            "price_per_km": vehicle.per_km_cost,
            "image_url": vehicle.primary_image_url
        }


class PaginationInfo(BaseModel):
    """Pagination information"""
    model_config = ConfigDict(extra="ignore")

    page: int = 1
    limit: int = 10
    total: int = 0
    has_more: bool = Field(default=False, alias="hasMore")


class SearchInfo(BaseModel):
    """Search metadata"""
    model_config = ConfigDict(extra="ignore")

    city: str
    coordinates: Optional[Dict[str, float]] = None
    radius: Optional[str] = None
    strategy: str = "hybrid"
    filters: Dict[str, Any] = Field(default_factory=dict)
    sort_by: str = Field(default="lastAccess:desc", alias="sortBy")
    query_by: str = Field(default="default", alias="queryBy")


class DriversSearchResponse(BaseModel):
    """Complete response from drivers search API"""
    model_config = ConfigDict(extra="ignore")

    success: bool
    data: List[Driver] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    search: Optional[SearchInfo] = None
    message: Optional[str] = None  # For error cases


# ============== TRIP API MODELS ==============
class TripCreationResponse(BaseModel):
    """Response from trip creation API"""
    model_config = ConfigDict(extra="ignore")

    message: str
    trip_id: str = Field(alias="tripId")


# ============== AVAILABILITY API MODELS ==============
class PushResult(BaseModel):
    """Push notification result"""
    model_config = ConfigDict(extra="ignore")

    success: bool
    success_count: int = Field(default=0, alias="successCount")
    failure_count: int = Field(default=0, alias="failureCount")


class WhatsAppResult(BaseModel):
    """WhatsApp notification result"""
    model_config = ConfigDict(extra="ignore")

    success: bool
    error: Optional[Dict[str, Any]] = None


class DriverAvailabilityDetail(BaseModel):
    """Individual driver availability check result"""
    model_config = ConfigDict(extra="ignore")

    driver_id: str = Field(alias="driverId")
    status: str
    push: Optional[PushResult] = None
    whatsapp: Optional[WhatsAppResult] = None


class AvailabilitySummary(BaseModel):
    """Summary of availability check"""
    model_config = ConfigDict(extra="ignore")

    total_drivers: int = Field(alias="totalDrivers")
    success_count: int = Field(alias="successCount")
    failure_count: int = Field(alias="failureCount")


class AvailabilityResponse(BaseModel):
    """Response from availability check API"""
    model_config = ConfigDict(extra="ignore")

    success: bool
    message: str
    summary: Optional[AvailabilitySummary] = None
    details: List[DriverAvailabilityDetail] = Field(default_factory=list)
