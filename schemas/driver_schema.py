from pydantic import BaseModel, Field
from typing import Any, List, Optional, Literal, Dict
from datetime import datetime
from langchain_core.chat_history import BaseMessage

# Reusing previously defined models
class User(BaseModel):
    id: str
    name: str
    username: str
    preferredLanguage: str


class VehicleImageUrl(BaseModel):
    url: str


class VehicleImages(BaseModel):
    full: VehicleImageUrl


class Vehicles(BaseModel):
    reg_no: str
    model: str
    is_commercial: Optional[bool] = None
    per_km_cost: Optional[float] = None
    vehicle_type: str
    fuel_type: str
    images: List[VehicleImages]


class PremiumDriver(BaseModel):
    id: str
    name: Optional[str] = None
    city: Optional[str] = None
    phoneNo: str
    profile_image: Optional[str] = None
    username: Optional[str] = None
    verifiedVehicles: List[Vehicles]


class Routes(BaseModel):
    from_: str
    to_: str


class Languages(BaseModel):
    name: str
    verified: bool


class TrainingContent(BaseModel):
    title: str
    description: str


class Driver(BaseModel):
    existingInfo: PremiumDriver
    age: Optional[int] = None
    connections: int = 0
    bio: Optional[str] = None
    experience: int = 0
    is_pet_allowed: Optional[bool] = None
    languages: List[str]
    is_married: Optional[bool] = None
    phoneNo: str
    routes: List[Routes]
    trip_types: List[str]
    username: Optional[str] = None
    trainingContent: List[TrainingContent] = []
    vehicle_ownership: List[bool]
    verified_languages: List[Languages]
    onboarded_at: Optional[datetime] = None


# class MessageTurn(BaseModel):
#     sender: Literal["user", "assistant"]
#     message: str
#     timestamp: Optional[datetime] = None

# 🧠 The Main LangGraph State
class CabBookingState(BaseModel):
    user: Optional[User] = None

    # List of drivers from DB or search
    drivers_with_full_details: List[Driver] = []
    premium_drivers: List[PremiumDriver] = []
    
    # Filtered based on user preferences
    filtered_drivers: List[Driver] = []

    # Filters applied
    applied_filters: Dict[str, str] = {}

    # Full chat memory
    chat_history: List[BaseMessage] = Field(default_factory=list)

    # Booking details captured
    pickup_location: Optional[str] = None
    drop_location: Optional[str] = None
    # travel_date: Optional[str] = None
    # return_date: Optional[str] = None
    passenger_count: Optional[int] = None
    trip_type: Optional[Literal["one-way", "round-trip"]] = None

    # Other state info
    current_step: Optional[str] = None  # e.g., "collecting_pickup", "filtering_drivers"
    selected_driver_id: Optional[str] = None
    selected_driver_info: Optional[Driver] = None
    booking_confirmed: bool = False
    drivers_to_display: List[Driver] = []
    last_bot_response: Optional[str] = None
    

    #filter
    filter_search_depth: int = 0
    max_filter_search_depth: int = 5

    # pagination
    # API pagination and search state
    page_no: int = 1
    no_more_drivers_from_api: bool = False

    tool_calls: list = Field(default_factory=list)


class FilterDriversArgs(BaseModel):
    """Input model for the filter_drivers tool."""
    drivers: List[Driver] = Field(description="The list of drivers with their full details to be filtered.")
    filters: Dict[str, Any] = Field(description="A dictionary of filters to apply. Keys are driver attributes, and values are the criteria. All filters are applied together (AND logic).")