# schemas/driver_schema.py
"""Driver data schemas with Pydantic v2"""

from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any, Union, Literal
from datetime import datetime
from langchain_core.messages import BaseMessage
from enum import Enum


class VehicleType(str, Enum):
    """Supported vehicle types"""
    SEDAN = "sedan"
    SUV = "suv"
    HATCHBACK = "hatchback"
    INNOVA = "innova"
    INNOVA_CRYSTA = "innovaCrysta"
    TEMPO_TRAVELLER_12_SEATER = "tempoTraveller12Seater"


class TripType(str, Enum):
    """Supported trip types"""
    ONE_WAY = "one-way"
    ROUND_TRIP = "round-trip"


class SearchStrategy(str, Enum):
    """Search strategies for driver lookup"""
    CITY = "city"
    GEO = "geo"
    HYBRID = "hybrid"


class SortOrder(str, Enum):
    """Sort order options"""
    ASC = "asc"
    DESC = "desc"


class Gender(str, Enum):
    """Gender options"""
    MALE = "male"
    FEMALE = "female"


class Language(str, Enum):
    """Supported languages"""
    ENGLISH = "English"
    HINDI = "Hindi"
    PUNJABI = "Punjabi"
    TAMIL = "Tamil"
    TELUGU = "Telugu"
    MARATHI = "Marathi"
    GUJARATI = "Gujarati"
    BENGALI = "Bengali"
    KANNADA = "Kannada"
    MALAYALAM = "Malayalam"
    URDU = "Urdu"
    ODIA = "Odia"
    ASSAMESE = "Assamese"
    NEPALI = "Nepali"


class VehicleImageUrl(BaseModel):
    """Vehicle image URL structure"""
    model_config = ConfigDict(extra="allow")
    
    url: str


class VehicleImages(BaseModel):
    """Vehicle images structure"""
    model_config = ConfigDict(extra="allow")
    
    full: VehicleImageUrl


class Vehicle(BaseModel):
    """Vehicle information"""
    model_config = ConfigDict(extra="allow")
    
    reg_no: Optional[str] = None
    model: str
    is_commercial: Optional[bool] = None
    per_km_cost: Optional[float] = Field(None, ge=0)
    vehicle_type: Optional[VehicleType] = None
    fuel_type: Optional[str] = None
    images: List[VehicleImages] = Field(default_factory=list)
    image_url: Optional[str] = None  # Direct image URL


class Route(BaseModel):
    """Route information"""
    model_config = ConfigDict(extra="allow")
    
    from_city: str = Field(alias="from")
    to_city: str = Field(alias="to")


class LanguageInfo(BaseModel):
    """Language verification info"""
    model_config = ConfigDict(extra="allow")
    
    name: Language
    verified: bool = True


class TrainingContent(BaseModel):
    """Training content information"""
    model_config = ConfigDict(extra="allow")
    
    title: str
    description: str


class PremiumDriver(BaseModel):
    """Premium driver base information"""
    model_config = ConfigDict(extra="allow")
    
    id: str
    name: Optional[str] = None
    city: Optional[str] = None
    phoneNo: str = Field(pattern=r'^\d{10}$')  # 10-digit phone number
    profile_image: Optional[str] = None
    username: Optional[str] = None
    verifiedVehicles: List[Vehicle] = Field(default_factory=list)


class Driver(BaseModel):
    """Complete driver information"""
    model_config = ConfigDict(extra="allow")
    
    # Basic info
    id: str
    name: Optional[str] = None
    city: Optional[str] = None
    phone: str = Field(pattern=r'^\d{10}$')
    username: Optional[str] = None
    profile_image: Optional[str] = None
    
    # Demographics
    age: Optional[int] = Field(None, ge=18, le=80)
    gender: Optional[Gender] = None
    married: Optional[bool] = None
    
    # Experience and verification
    experience: int = Field(0, ge=0)
    connections: int = Field(0, ge=0)
    profile_verified: Optional[bool] = None
    verified: Optional[bool] = None
    
    # Preferences and capabilities
    is_pet_allowed: Optional[bool] = None
    allow_handicapped_persons: Optional[bool] = None
    available_for_customers_personal_car: Optional[bool] = None
    available_for_driving_in_event_wedding: Optional[bool] = None
    available_for_part_time_full_time: Optional[bool] = None
    
    # Languages
    languages: List[str] = Field(default_factory=list)
    verified_languages: List[str] = Field(default_factory=list)
    
    # Professional info
    bio: Optional[str] = None
    driving_experience: Optional[int] = Field(None, ge=0)
    fraud_reports: int = Field(0, ge=0)
    
    # Vehicles and routes
    vehicles: List[Vehicle] = Field(default_factory=list)
    routes: List[Route] = Field(default_factory=list)
    trip_types: List[str] = Field(default_factory=list)
    
    # Timestamps
    last_access: Optional[int] = None
    onboarded_at: Optional[datetime] = None
    
    # Training and ownership
    training_content: List[TrainingContent] = Field(default_factory=list)
    vehicle_ownership: List[bool] = Field(default_factory=list)


class DriverFilters(BaseModel):
    """Driver search filters with proper types"""
    model_config = ConfigDict(extra="allow")
    
    # Basic demographics
    gender: Optional[Gender] = None
    min_age: Optional[int] = Field(None, ge=18, le=80, alias="minAge")
    max_age: Optional[int] = Field(None, ge=18, le=80, alias="maxAge")
    married: Optional[bool] = None
    
    # Verification and experience
    profile_verified: Optional[bool] = Field(None, alias="profileVerified")
    verified: Optional[bool] = None
    min_driving_experience: Optional[int] = Field(None, ge=0, alias="minDrivingExperience")
    min_experience: Optional[int] = Field(None, ge=0, alias="minExperience")
    min_connections: Optional[int] = Field(None, ge=0, alias="minConnections")
    fraud_reports: Optional[int] = Field(None, ge=0, alias="fraudReports")
    
    # Vehicle preferences
    vehicle_types: Optional[str] = Field(None, alias="vehicleTypes")  # Comma-separated
    is_pet_allowed: Optional[bool] = Field(None, alias="isPetAllowed")
    
    # Availability preferences
    allow_handicapped_persons: Optional[bool] = Field(None, alias="allowHandicappedPersons")
    available_for_customers_personal_car: Optional[bool] = Field(None, alias="availableForCustomersPersonalCar")
    available_for_driving_in_event_wedding: Optional[bool] = Field(None, alias="availableForDrivingInEventWedding")
    available_for_part_time_full_time: Optional[bool] = Field(None, alias="availableForPartTimeFullTime")
    
    # Languages
    verified_languages: Optional[str] = Field(None, alias="verifiedLanguages")  # Comma-separated
    
    # Numeric comparisons (using operators)
    connections: Optional[str] = None  # e.g., ">=50", ">100"
    profile_completion_percentage: Optional[str] = Field(None, alias="profileCompletionPercentage")  # e.g., ">=80"
    
    def to_api_params(self) -> Dict[str, Any]:
        """Convert to API parameters, excluding None values"""
        params = {}
        
        # Convert to dict and exclude None values
        for field_name, value in self.model_dump(by_alias=True, exclude_none=True).items():
            if value is not None:
                params[field_name] = value
                
        return params


class PaginationInfo(BaseModel):
    """Pagination information"""
    model_config = ConfigDict(extra="allow")
    
    page: int = Field(1, ge=1)
    limit: int = Field(10, ge=1, le=100)
    total: Optional[int] = None
    has_more: bool = False


class SearchInfo(BaseModel):
    """Search information"""
    model_config = ConfigDict(extra="allow")
    
    city: str
    coordinates: Optional[Dict[str, float]] = None
    radius: Optional[str] = None
    strategy: SearchStrategy = SearchStrategy.HYBRID
    filters: Dict[str, Any] = Field(default_factory=dict)


class DriversResponse(BaseModel):
    """API response for drivers"""
    model_config = ConfigDict(extra="allow")
    
    success: bool
    data: List[Driver] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    search: Optional[SearchInfo] = None


class CustomerDetails(BaseModel):
    """Customer information"""
    model_config = ConfigDict(extra="allow")
    
    id: Optional[str] = None
    name: Optional[str] = None
    phone: Optional[str] = Field(None, pattern=r'^\d{10}$')
    profile_image: Optional[str] = None


class TripLocation(BaseModel):
    """Trip location information"""
    model_config = ConfigDict(extra="allow")
    
    city: str
    coordinates: Optional[str] = ""
    place_name: Optional[str] = ""


class TripDetails(BaseModel):
    """Trip details for availability requests"""
    model_config = ConfigDict(extra="allow")
    
    from_city: str = Field(alias="from")
    to_city: str = Field(alias="to")
    trip_time: str
    trip_date: str
    trip_type: TripType


class CreateTripRequest(BaseModel):
    """Trip creation request"""
    model_config = ConfigDict(extra="allow")
    
    customer_id: Optional[str] = Field(None, alias="customerId")
    customer_name: Optional[str] = Field(None, alias="customerName")
    customer_phone: Optional[str] = Field(None, alias="customerPhone")
    customer_profile_image: Optional[str] = Field(None, alias="customerProfileImage")
    pickup_location: TripLocation = Field(alias="pickUpLocation")
    drop_location: TripLocation = Field(alias="dropLocation")
    start_date: str = Field(alias="startDate")
    end_date: Optional[str] = Field(None, alias="endDate")
    trip_type: TripType = Field(alias="tripType")


class CreateTripResponse(BaseModel):
    """Trip creation response"""
    model_config = ConfigDict(extra="allow")
    
    trip_id: Optional[str] = Field(None, alias="tripId")
    status: str
    message: Optional[str] = None


class AvailabilityRequest(BaseModel):
    """Availability request payload"""
    model_config = ConfigDict(extra="allow")
    
    driver_ids: List[str] = Field(alias="driverIds")
    trip_id: str = Field(alias="tripId")
    data: Dict[str, Any]


class CabBookingState(BaseModel):
    """Main state for the cab booking agent with Pydantic v2"""
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="allow")

    # Chat history
    chat_history: List[BaseMessage] = Field(default_factory=list)

    # Driver data - storing all fetched drivers
    all_fetched_drivers: List[Dict[str, Any]] = Field(default_factory=list)
    drivers_with_full_details: List[Dict[str, Any]] = Field(default_factory=list)
    filtered_drivers: List[Dict[str, Any]] = Field(default_factory=list)

    # Pagination state
    current_display_index: int = Field(0, ge=0)
    current_page: int = Field(1, ge=1)
    fetch_count: int = Field(0, ge=0)

    # Filters with proper typing
    applied_filters: DriverFilters = Field(default_factory=DriverFilters)

    # Booking details
    pickup_location: Optional[str] = None
    drop_location: Optional[str] = None
    passenger_count: Optional[int] = Field(None, ge=1, le=20)
    trip_type: Optional[TripType] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    trip_id: Optional[str] = None

    # State info
    last_bot_response: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)

    # Customer details
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_profile: Optional[str] = None
    customer_phone: Optional[str] = Field(None, pattern=r'^\d{10}$')


class ToolResponse(BaseModel):
    """Base tool response"""
    model_config = ConfigDict(extra="allow")
    
    status: Literal["success", "error"]
    message: Optional[str] = None


class DriversToolResponse(ToolResponse):
    """Response from get_drivers_for_city tool"""
    drivers: List[Driver] = Field(default_factory=list)
    page: int = Field(1, ge=1)
    has_more: bool = False
    total_fetched: int = Field(0, ge=0)


class ShowMoreDriversResponse(BaseModel):
    """Response from show_more_drivers tool"""
    model_config = ConfigDict(extra="allow")
    
    next_index: int = Field(ge=0)
    has_more_in_current: bool
    should_fetch_new: bool