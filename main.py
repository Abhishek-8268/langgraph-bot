import os
import re
import logging
from fastapi import FastAPI, Request, HTTPException
from slack_sdk import WebClient
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Any, List
import asyncio
from datetime import datetime

# Import your existing agent
from langgraph_agent.graph.builder import app as cab_agent
from schemas.driver_schema import DriverFilters, CabBookingState

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Simple setup
app = FastAPI(
    title="Enhanced Cab Booking Bot", 
    version="2.0.0",
    description="AI-powered cab booking assistant with comprehensive filtering capabilities"
)

slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "https://www.cabswale.ai", 
        "https://cabswale-landing-page-dev--cabswale-ai.us-central1.hosted.app"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# Enhanced in-memory storage with type safety
user_conversations: Dict[str, Dict[str, Any]] = {}
processed_messages = set()

# --- Enhanced Pydantic models ---
class CustomerDetails(BaseModel):
    """Customer details model"""
    customer_id: Optional[str] = Field(None, alias="customerId")
    customer_name: Optional[str] = Field(None, alias="customerName") 
    customer_profile: Optional[str] = Field(None, alias="customerProfile")
    customer_phone: Optional[str] = Field(None, alias="customerPhone", pattern=r'^\d{10}$')


class ChatRequest(BaseModel):
    """Enhanced chat request model"""
    user_id: str = Field(..., min_length=1, description="Unique user identifier")
    message: str = Field(..., min_length=1, description="User message content")
    customer_id: Optional[str] = Field(None, alias="customerId")
    customer_name: Optional[str] = Field(None, alias="customerName")
    customer_profile: Optional[str] = Field(None, alias="customerProfile")  
    customer_phone: Optional[str] = Field(None, alias="customerPhone")
    
    # Optional filter preferences for power users
    filters: Optional[Dict[str, Any]] = Field(None, description="Pre-applied filters")


class ChatResponse(BaseModel):
    """Enhanced chat response model"""
    response: Any = Field(..., description="Bot response content")
    type: str = Field(..., description="Response type: 'text' or 'driverList'")
    applied_filters: Optional[Dict[str, Any]] = Field(None, description="Currently applied filters")
    available_filters: Optional[List[str]] = Field(None, description="Available filter options")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")


class DriverListResponse(BaseModel):
    """Driver list response model"""
    drivers: List[Dict[str, Any]] = Field(..., description="List of driver information")
    suggestion: str = Field(..., description="Bot suggestion or instruction text")
    filters_applied: Dict[str, Any] = Field(default_factory=dict, description="Applied filters")
    total_count: Optional[int] = Field(None, description="Total drivers found")


def get_user_state(user_id: str) -> Dict[str, Any]:
    """Get or create enhanced user conversation state"""
    if user_id not in user_conversations:
        user_conversations[user_id] = {
            "chat_history": [],
            "all_fetched_drivers": [],
            "drivers_with_full_details": [],
            "filtered_drivers": [],
            "applied_filters": {},  # Now properly typed as dict
            "pickup_location": None,
            "drop_location": None,
            "trip_type": None,
            "trip_id": None,
            "last_bot_response": None,
            "tool_calls": [],
            "current_display_index": 0,
            "current_page": 1,
            "fetch_count": 0,
            # Customer details
            "customer_id": None,
            "customer_name": None,
            "customer_profile": None,
            "customer_phone": None,
            # Enhanced metadata
            "session_start": datetime.now().isoformat(),
            "last_activity": datetime.now().isoformat(),
            "total_requests": 0,
        }
    
    # Update last activity
    user_conversations[user_id]["last_activity"] = datetime.now().isoformat()
    user_conversations[user_id]["total_requests"] = user_conversations[user_id].get("total_requests", 0) + 1
    
    return user_conversations[user_id]


def is_duplicate_message(event: dict) -> bool:
    """Enhanced duplicate detection with multiple identifiers"""
    user_id = event.get("user")
    text = event.get("text", "").strip()
    timestamp = event.get("ts", "")
    event_ts = event.get("event_ts", "")

    # Create multiple unique identifiers
    identifiers = [
        f"{user_id}:{text}:{timestamp}",
        f"{user_id}:{timestamp}",
        f"event:{event_ts}" if event_ts else None
    ]

    # Remove None values
    identifiers = [id for id in identifiers if id]

    # Check if any identifier was already processed
    for identifier in identifiers:
        if identifier in processed_messages:
            logger.debug(f"Duplicate detected: {identifier}")
            return True

    # Add all identifiers to processed set
    for identifier in identifiers:
        processed_messages.add(identifier)

    # Keep only last 200 messages to prevent memory leak
    if len(processed_messages) > 200:
        new_set = set(list(processed_messages)[-100:])
        processed_messages.clear()
        processed_messages.update(new_set)

    return False


def process_message(user_id: str, message: str, customer_details: Optional[Dict] = None) -> str:
    """Enhanced message processing with better error handling and filtering awareness"""
    logger.info(f"Processing for {user_id}: {message}")

    try:
        # Get user state
        state = get_user_state(user_id)
        
        # Update customer details if provided
        if customer_details:
            state.update(customer_details)

        # Handle simple commands
        if message.lower().strip() == "reset":
            if user_id in user_conversations:
                # Keep session metadata but reset conversation
                session_start = user_conversations[user_id].get("session_start")
                total_requests = user_conversations[user_id].get("total_requests", 0)
                del user_conversations[user_id]
                
                # Reinitialize with preserved metadata
                new_state = get_user_state(user_id)
                new_state["session_start"] = session_start
                new_state["total_requests"] = total_requests
                
            return "🔄 Conversation reset! Let's start fresh. Where would you like to travel?"

        # Handle filter status requests
        if message.lower().strip() in ["show filters", "what filters", "current filters"]:
            applied_filters = state.get("applied_filters", {})
            if not applied_filters:
                return "No filters are currently applied. You can filter by gender, age, vehicle type, languages, experience, and more!"
            
            filter_descriptions = []
            for key, value in applied_filters.items():
                if key == "gender":
                    filter_descriptions.append(f"Gender: {value}")
                elif key == "vehicleTypes":
                    filter_descriptions.append(f"Vehicles: {value}")
                elif key == "verifiedLanguages":
                    filter_descriptions.append(f"Languages: {value}")
                elif key == "isPetAllowed":
                    filter_descriptions.append(f"Pet-friendly: {'Yes' if value else 'No'}")
                elif key in ["minAge", "maxAge"]:
                    filter_descriptions.append(f"Age: {key.replace('Age', '')} {value}")
                else:
                    filter_descriptions.append(f"{key}: {value}")
            
            return f"Current filters applied:\n• " + "\n• ".join(filter_descriptions)

        # Add message to chat history
        state["chat_history"].append(HumanMessage(content=message))

        # Process through enhanced agent with timeout
        try:
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError("Agent call timed out")

            # Set timeout to 45 seconds
            signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(45)

            try:
                result = cab_agent.invoke(state)
            finally:
                signal.alarm(0)

            # Validate result
            if not isinstance(result, dict):
                logger.warning(f"Agent returned non-dict: {type(result)}")
                return "Sorry, I had a technical issue. Please try again."

            # Update state
            user_conversations[user_id] = result
            logger.info(f"State updated for {user_id}")

            # Extract response with enhanced fallbacks
            response = extract_response(result)
            
            if not response or not response.strip():
                response = "I'm here to help you find drivers! Please tell me your pickup location or what you're looking for."
                logger.info("Using final fallback response")

            return response

        except TimeoutError:
            logger.error(f"Agent call timed out for {user_id}")
            return "Sorry, that request is taking too long. Please try a simpler query or type 'reset'."
        
    except ValidationError as e:
        logger.error(f"Validation error for user {user_id}: {e}")
        return "Sorry, there was an issue with your request format. Please try again."
    except Exception as e:
        logger.error(f"Error processing message for {user_id}: {e}", exc_info=True)
        return "Sorry, I encountered an issue. Please try again or type 'reset'."


def extract_response(result: Dict[str, Any]) -> str:
    """Enhanced response extraction with better fallbacks"""
    response = None

    # Try 1: Direct last_bot_response
    if result.get("last_bot_response"):
        response = result["last_bot_response"]
        logger.debug(f"Got direct response: {response[:50]}...")

    # Try 2: Last AI message from chat history
    if not response:
        chat_history = result.get("chat_history", [])
        for msg in reversed(chat_history):
            if hasattr(msg, 'content') and 'AI' in str(type(msg)):
                if msg.content and msg.content.strip():
                    response = msg.content
                    logger.debug(f"Got AI message: {response[:50]}...")
                    break

    # Try 3: Check if we have drivers and create contextual response
    if not response:
        drivers = result.get("all_fetched_drivers", [])
        applied_filters = result.get("applied_filters", {})
        
        if drivers:
            filter_text = ""
            if applied_filters:
                filter_descriptions = []
                for key, value in applied_filters.items():
                    if key == "gender":
                        filter_descriptions.append(f"{value}")
                    elif key == "vehicleTypes":
                        filter_descriptions.append(f"{value} vehicles")
                    elif key == "verifiedLanguages":
                        filter_descriptions.append(f"{value} speaking")
                filter_text = f" matching your criteria ({', '.join(filter_descriptions)})" if filter_descriptions else ""
            
            response = f"I found {len(drivers)} drivers{filter_text}. What specific information would you like about them?"
            logger.debug("Generated contextual response with filter awareness")

    return response or ""


def parse_driver_string(response_str: str) -> Dict[str, Any]:
    """Enhanced driver string parser with filter awareness"""
    drivers = []
    suggestion = ""
    applied_filters = {}
    
    # Split the response by double newlines
    blocks = response_str.strip().split('\n\n')

    driver_blocks = []
    other_blocks = []

    for block in blocks:
        if "Driver Name:" in block:
            driver_blocks.append(block)
        else:
            other_blocks.append(block.strip())

    # Join non-driver blocks as suggestion
    suggestion = " ".join(other_blocks)

    # Parse driver blocks
    for block in driver_blocks:
        driver = {}
        lines = block.strip().split('\n')

        try:
            # First line is always "Driver Name: ..."
            driver['name'] = lines[0].replace('Driver Name:', '').strip()
        except IndexError:
            continue

        # Parse other lines
        for line in lines[1:]:
            line = line.replace('•', '').strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower().replace(' ', '_').replace('per_km', 'price_per_km')
                driver[key] = value.strip()
        
        drivers.append(driver)

    return {
        "drivers": drivers, 
        "suggestion": suggestion,
        "filters_applied": applied_filters,
        "total_count": len(drivers)
    }


def get_available_filter_options() -> List[str]:
    """Get list of all available filter options"""
    return [
        "gender", "age", "married", "vehicleTypes", "isPetAllowed", 
        "verifiedLanguages", "experience", "connections", "verified",
        "profileVerified", "fraudReports", "allowHandicappedPersons",
        "availableForCustomersPersonalCar", "availableForDrivingInEventWedding",
        "availableForPartTimeFullTime"
    ]


# --- Enhanced API Endpoint ---
@app.post("/chat", response_model=ChatResponse)
async def chat_with_bot(chat_request: ChatRequest):
    """
    Enhanced chat endpoint with comprehensive filtering and type safety
    """
    try:
        # Validate input
        customer_details = {
            "customer_id": chat_request.customer_id,
            "customer_name": chat_request.customer_name,
            "customer_profile": chat_request.customer_profile,
            "customer_phone": chat_request.customer_phone,
        }

        # Process message
        response = process_message(
            chat_request.user_id, 
            chat_request.message, 
            customer_details
        )

        # Get current state for metadata
        state = user_conversations.get(chat_request.user_id, {})
        applied_filters = state.get("applied_filters", {})
        
        # Determine response type and format
        if "Driver Name:" in response and "• City:" in response:
            # Parse driver list response
            parsed_response = parse_driver_string(response)
            
            return ChatResponse(
                response=parsed_response,
                type="driverList",
                applied_filters=applied_filters,
                available_filters=get_available_filter_options(),
                metadata={
                    "total_drivers_fetched": len(state.get("all_fetched_drivers", [])),
                    "current_page": state.get("current_page", 1),
                    "has_more": len(state.get("all_fetched_drivers", [])) > state.get("current_display_index", 0) + 5,
                    "session_duration": calculate_session_duration(state.get("session_start")),
                    "total_requests": state.get("total_requests", 0)
                }
            )
        else:
            # Text response
            return ChatResponse(
                response=response,
                type="text",
                applied_filters=applied_filters,
                available_filters=get_available_filter_options(),
                metadata={
                    "session_duration": calculate_session_duration(state.get("session_start")),
                    "total_requests": state.get("total_requests", 0)
                }
            )

    except ValidationError as e:
        logger.error(f"Validation error in chat endpoint: {e}")
        raise HTTPException(
            status_code=422, 
            detail=f"Invalid request format: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail="Internal server error. Please try again."
        )


def calculate_session_duration(session_start: Optional[str]) -> Optional[str]:
    """Calculate session duration in human-readable format"""
    if not session_start:
        return None
    
    try:
        start_time = datetime.fromisoformat(session_start.replace('Z', '+00:00'))
        duration = datetime.now() - start_time.replace(tzinfo=None)
        
        if duration.days > 0:
            return f"{duration.days}d {duration.seconds // 3600}h"
        elif duration.seconds > 3600:
            return f"{duration.seconds // 3600}h {(duration.seconds % 3600) // 60}m"
        else:
            return f"{duration.seconds // 60}m {duration.seconds % 60}s"
    except:
        return None


# --- Additional API Endpoints ---
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "2.0.0"
    }


@app.get("/stats")
async def get_stats():
    """Get system statistics"""
    total_users = len(user_conversations)
    total_conversations = sum(
        len(state.get("chat_history", [])) 
        for state in user_conversations.values()
    )
    total_drivers_fetched = sum(
        len(state.get("all_fetched_drivers", []))
        for state in user_conversations.values()
    )
    
    return {
        "total_users": total_users,
        "total_conversations": total_conversations,
        "total_drivers_fetched": total_drivers_fetched,
        "available_filters": get_available_filter_options()
    }


@app.post("/reset/{user_id}")
async def reset_user_conversation(user_id: str):
    """Reset a user's conversation state"""
    if user_id in user_conversations:
        del user_conversations[user_id]
        return {"message": f"Conversation reset for user {user_id}"}
    return {"message": f"No conversation found for user {user_id}"}


@app.get("/filters")
async def get_filter_info():
    """Get detailed information about available filters"""
    return {
        "available_filters": {
            "gender": {
                "type": "string",
                "options": ["male", "female"],
                "description": "Filter drivers by gender"
            },
            "minAge": {
                "type": "integer",
                "range": [18, 80],
                "description": "Minimum age of drivers"
            },
            "maxAge": {
                "type": "integer", 
                "range": [18, 80],
                "description": "Maximum age of drivers"
            },
            "married": {
                "type": "boolean",
                "description": "Marital status of drivers"
            },
            "vehicleTypes": {
                "type": "string",
                "options": ["sedan", "suv", "hatchback", "innova", "innovaCrysta", "tempoTraveller12Seater"],
                "description": "Vehicle types (comma-separated for multiple)"
            },
            "isPetAllowed": {
                "type": "boolean",
                "description": "Whether driver allows pets"
            },
            "verifiedLanguages": {
                "type": "string",
                "options": ["English", "Hindi", "Punjabi", "Tamil", "Telugu", "Marathi", "Gujarati", "Bengali", "Kannada", "Malayalam", "Urdu", "Odia", "Assamese", "Nepali"],
                "description": "Languages spoken by driver (comma-separated for multiple)"
            },
            "minExperience": {
                "type": "integer",
                "description": "Minimum years of experience"
            },
            "minConnections": {
                "type": "integer",
                "description": "Minimum number of connections"
            },
            "verified": {
                "type": "boolean",
                "description": "Whether driver is verified"
            },
            "profileVerified": {
                "type": "boolean",
                "description": "Whether driver profile is verified"
            },
            "fraudReports": {
                "type": "integer",
                "description": "Maximum number of fraud reports"
            }
        }
    }


# --- Slack Integration (if needed) ---
@app.post("/slack/events")
async def slack_events(request: Request):
    """Handle Slack events"""
    try:
        body = await request.json()
        
        # Handle URL verification
        if body.get("type") == "url_verification":
            return {"challenge": body.get("challenge")}
        
        # Handle app mentions and DMs
        if body.get("type") == "event_callback":
            event = body.get("event", {})
            
            # Skip bot messages and duplicates
            if event.get("subtype") == "bot_message" or is_duplicate_message(event):
                return {"status": "ok"}
            
            user_id = event.get("user")
            text = event.get("text", "").strip()
            channel = event.get("channel")
            
            if user_id and text and channel:
                # Process message
                response = process_message(user_id, text)
                
                # Send response to Slack
                try:
                    slack_client.chat_postMessage(
                        channel=channel,
                        text=response,
                        thread_ts=event.get("ts")
                    )
                except Exception as e:
                    logger.error(f"Error sending Slack message: {e}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Error handling Slack event: {e}")
        return {"status": "error"}


# --- Main Application Entry Point ---
if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8000))
    
    logger.info(f"Starting Enhanced Cab Booking Bot on port {port}")
    logger.info("Features enabled:")
    logger.info("✅ Comprehensive driver filtering")
    logger.info("✅ Type-safe Pydantic v2 schemas") 
    logger.info("✅ Enhanced error handling")
    logger.info("✅ Session management")
    logger.info("✅ Real-time statistics")
    logger.info("✅ Slack integration")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        reload=False
    )