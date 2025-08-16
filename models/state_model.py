# models/state_model.py
"""State management schema for the cab booking agent"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from langchain_core.messages import BaseMessage


class ConversationState(BaseModel):
    """Complete state for a user's conversation"""
    model_config = {"arbitrary_types_allowed": True}

    # Chat history
    chat_history: List[BaseMessage] = Field(default_factory=list)

    # Driver data
    all_fetched_drivers: List[Dict[str, Any]] = Field(default_factory=list)
    filtered_drivers: List[Dict[str, Any]] = Field(default_factory=list)

    # Pagination state
    current_display_index: int = 0
    current_page: int = 1
    fetch_count: int = 0

    # Applied filters
    applied_filters: Dict[str, Any] = Field(default_factory=dict)

    # Trip details
    trip_id: Optional[str] = None
    pickup_location: Optional[str] = None
    drop_location: Optional[str] = None
    trip_type: Optional[str] = None
    start_date: Optional[str] = None  # YYYY-MM-DD format
    end_date: Optional[str] = None    # YYYY-MM-DD format

    # Customer details
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_profile: Optional[str] = None

    # Agent state
    last_bot_response: Optional[str] = None
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for graph state"""
        return {
            "chat_history": self.chat_history,
            "all_fetched_drivers": self.all_fetched_drivers,
            "filtered_drivers": self.filtered_drivers,
            "current_display_index": self.current_display_index,
            "current_page": self.current_page,
            "fetch_count": self.fetch_count,
            "applied_filters": self.applied_filters,
            "trip_id": self.trip_id,
            "pickup_location": self.pickup_location,
            "drop_location": self.drop_location,
            "trip_type": self.trip_type,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone,
            "customer_profile": self.customer_profile,
            "last_bot_response": self.last_bot_response,
            "tool_calls": self.tool_calls,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationState":
        """Create from dictionary"""
        return cls(**data)

    def reset(self) -> None:
        """Reset the conversation state"""
        self.chat_history = []
        self.all_fetched_drivers = []
        self.filtered_drivers = []
        self.current_display_index = 0
        self.current_page = 1
        self.fetch_count = 0
        self.applied_filters = {}
        self.trip_id = None
        self.pickup_location = None
        self.drop_location = None
        self.trip_type = None
        self.start_date = None
        self.end_date = None
        self.last_bot_response = None
        self.tool_calls = []
