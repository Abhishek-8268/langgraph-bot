import os
import asyncio
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from slack_sdk import WebClient
from slack_sdk.web.async_client import AsyncWebClient
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import traceback
from datetime import datetime
from contextlib import asynccontextmanager
import logging

# Import your agent and state model
from langgraph_agent.graph.builder import app as cab_agent
from models.state_model import ConversationState
from services.redis_service import redis_manager

# Setup logging
logging.basicConfig(level=getattr(logging, "WARNING"))
logger = logging.getLogger(__name__)


# Lifecycle management for Redis
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle - initialize and cleanup Redis"""
    # Startup
    logger.info("🚀 Starting up - initializing Redis connection...")
    await redis_manager.initialize()

    # Check Redis health
    health = await redis_manager.health_check()
    if health.get("redis_available"):
        logger.info(f"✅ Redis connected: {health.get('status')}")
    else:
        logger.warning("⚠️ Redis not available - using fallback storage")

    yield

    # Shutdown
    logger.info("🔚 Shutting down - closing Redis connections...")
    await redis_manager.close()


# Initialize FastAPI with lifespan
app = FastAPI(title="Cab Booking Bot", lifespan=lifespan)

# Initialize Slack clients
slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))
async_slack_client = AsyncWebClient(token=os.environ.get("SLACK_BOT_TOKEN"))

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

# Fallback in-memory storage for when Redis is unavailable
fallback_storage: Dict[str, ConversationState] = {}


# --- Pydantic model for the /chat endpoint ---
class ChatRequest(BaseModel):
    user_id: str
    message: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_profile: Optional[str] = None
    customer_phone: Optional[str] = None


async def get_user_state(user_id: str, customer_details: dict = None) -> ConversationState:
    """Get or create user conversation state with async Redis integration"""

    # First, try to get from Redis
    state = await redis_manager.get_session(user_id)

    if state:
        # Session exists in Redis
        logger.info(f"✅ Found existing session for {user_id}")

        # Update customer details if provided and changed
        if customer_details:
            updated = False
            if customer_details.get("customer_id") and state.customer_id != customer_details["customer_id"]:
                state.customer_id = customer_details["customer_id"]
                updated = True
            if customer_details.get("customer_name") and state.customer_name != customer_details["customer_name"]:
                state.customer_name = customer_details["customer_name"]
                updated = True
            if customer_details.get("customer_phone") and state.customer_phone != customer_details["customer_phone"]:
                state.customer_phone = customer_details["customer_phone"]
                updated = True
            if customer_details.get("customer_profile") and state.customer_profile != customer_details["customer_profile"]:
                state.customer_profile = customer_details["customer_profile"]
                updated = True

            if updated:
                await redis_manager.save_session(user_id, state)

        return state

    # No session in Redis, check fallback storage
    if user_id in fallback_storage:
        logger.info(f"📦 Using fallback storage for {user_id}")
        return fallback_storage[user_id]

    # Create new session
    logger.info(f"🆕 Creating new session for {user_id}")
    new_state = ConversationState(
        chat_history=[],
        all_fetched_drivers=[],
        filtered_drivers=[],
        applied_filters={},
        current_display_index=0,
        current_page=1,
        fetch_count=0,
        trip_id=None,
        pickup_location=None,
        drop_location=None,
        trip_type=None,
        start_date=None,
        end_date=None,
        customer_id=customer_details.get("customer_id") if customer_details else None,
        customer_name=customer_details.get("customer_name") if customer_details else None,
        customer_phone=customer_details.get("customer_phone") if customer_details else None,
        customer_profile=customer_details.get("customer_profile") if customer_details else None,
        last_bot_response=None,
        tool_calls=[]
    )

    # Save to Redis
    if not await redis_manager.save_session(user_id, new_state):
        # If Redis save fails, use fallback storage
        logger.warning(f"⚠️ Redis save failed, using fallback storage for {user_id}")
        fallback_storage[user_id] = new_state

    return new_state


async def save_user_state(user_id: str, state: ConversationState) -> bool:
    """Save user state to Redis with fallback"""
    success = await redis_manager.save_session(user_id, state)

    if not success:
        # Fallback to in-memory storage
        logger.warning(f"⚠️ Using fallback storage to save state for {user_id}")
        fallback_storage[user_id] = state

    return success


async def clear_user_session(user_id: str) -> bool:
    """Clear user session from Redis and fallback storage"""
    redis_deleted = await redis_manager.delete_session(user_id)

    # Also clear from fallback storage
    if user_id in fallback_storage:
        del fallback_storage[user_id]

    return redis_deleted


async def is_duplicate_message(event: dict) -> bool:
    """Check if this event was already processed using Redis-backed deduplication"""
    user_id = event.get("user")
    text = event.get("text", "").strip()
    timestamp = event.get("ts", "")

    # Use Redis for duplicate checking
    if await redis_manager.is_duplicate_message(user_id, text, timestamp):
        logger.info(f"🔄 Duplicate detected (Redis): {user_id}:{text}")
        return True

    return False


async def process_message_async(user_id: str, message: str, customer_details: dict = {}) -> str:
    """Process user message through cab agent with async Redis-backed state management"""
    logger.info(f"🔄 Processing for {user_id}: {message}")

    # Get user state from Redis/fallback
    state_model = await get_user_state(user_id, customer_details)

    # Handle simple commands
    if message.lower().strip() == "reset":
        # Clear the session from Redis
        await clear_user_session(user_id)
        return "🔄 Reset! Let's start fresh. Where would you like to travel?"

    # Check if session is expired (no trip_id and empty chat history)
    if not state_model.trip_id and len(state_model.chat_history) == 0:
        # This is essentially a new session
        logger.info(f"📝 Starting fresh session for {user_id}")

    # Add message to chat history
    state_model.chat_history.append(HumanMessage(content=message))

    # Convert Pydantic model to dict for the agent
    state_dict = state_model.to_dict()

    # Process through agent in executor (since it's sync)
    try:
        logger.info(f"🤖 Invoking agent...")

        # Run the sync agent in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, cab_agent.invoke, state_dict),
            timeout=45.0
        )

        # Ensure result is valid
        if not isinstance(result, dict):
            logger.warning(f"⚠️ Agent returned non-dict: {type(result)}")
            return "Sorry, I had a technical issue. Please try again."

        # Update the Pydantic state model from the result
        state_model.chat_history = result.get("chat_history", state_model.chat_history)
        state_model.all_fetched_drivers = result.get("all_fetched_drivers", state_model.all_fetched_drivers)
        state_model.filtered_drivers = result.get("filtered_drivers", state_model.filtered_drivers)
        state_model.applied_filters = result.get("applied_filters", state_model.applied_filters)
        state_model.current_display_index = result.get("current_display_index", state_model.current_display_index)
        state_model.current_page = result.get("current_page", state_model.current_page)
        state_model.fetch_count = result.get("fetch_count", state_model.fetch_count)
        state_model.trip_id = result.get("trip_id", state_model.trip_id)
        state_model.pickup_location = result.get("pickup_location", state_model.pickup_location)
        state_model.drop_location = result.get("drop_location", state_model.drop_location)
        state_model.trip_type = result.get("trip_type", state_model.trip_type)
        state_model.start_date = result.get("start_date", state_model.start_date)
        state_model.end_date = result.get("end_date", state_model.end_date)
        state_model.last_bot_response = result.get("last_bot_response", state_model.last_bot_response)
        state_model.tool_calls = result.get("tool_calls", state_model.tool_calls)

        # Save updated state to Redis
        await save_user_state(user_id, state_model)

        logger.info(f"✅ State updated and saved for {user_id}")

        # Extract response with better fallbacks
        response = None

        # Try 1: Direct last_bot_response
        if state_model.last_bot_response:
            response = state_model.last_bot_response
            logger.info(f"📤 Got direct response: {response[:50] if len(response) > 50 else response}...")

        # Try 2: Last AI message from chat history
        if not response:
            for msg in reversed(state_model.chat_history):
                if hasattr(msg, 'content') and 'AI' in str(type(msg)):
                    if msg.content and msg.content.strip():
                        response = msg.content
                        logger.info(f"📤 Got AI message: {response[:50] if len(response) > 50 else response}...")
                        break

        # Try 3: Check if we have drivers and create a response
        if not response:
            if state_model.all_fetched_drivers:
                response = f"I found {len(state_model.all_fetched_drivers)} drivers for you. Please let me know what specific information you'd like about them."
                logger.info(f"📤 Generated fallback response")

        # Final fallback
        if not response or not response.strip():
            response = "I'm here to help you find drivers! Please tell me your pickup location or what you're looking for."
            logger.info(f"📤 Using final fallback response")

        # Extend session TTL on successful interaction
        await redis_manager.extend_session(user_id)

        return response

    except asyncio.TimeoutError:
        logger.error(f"⏰ Agent call timed out for {user_id}")
        return "Sorry, that request is taking too long. Please try again with a simpler query or type 'reset'."
    except Exception as e:
        logger.error(f"❌ Error processing message: {e}")
        traceback.print_exc()
        return "Sorry, I had an issue processing your request. Please try again or type 'reset'."



def parse_driver_string(response_str: str) -> Dict[str, Any]:
    """Parses the string representation of drivers into a structured dictionary."""
    drivers = []
    suggestion = ""

    # First, check if there's a clear suggestion section
    # Look for common suggestion patterns
    suggestion_patterns = [
        "Here are 5 drivers",
        "Here are drivers",
        "Want me to check",
        "Tip:",
        "You can also",
        "Would you like"
    ]

    # Split the response into lines for processing
    lines = response_str.strip().split('\n')

    current_driver = None
    driver_section_active = False

    for i, line in enumerate(lines):
        line = line.strip()

        # Skip empty lines
        if not line:
            # If we have a current driver, save it before moving on
            if current_driver and 'name' in current_driver:
                drivers.append(current_driver)
                current_driver = None
                driver_section_active = False
            continue

        # Check if this line starts a new driver entry
        if line.startswith("Driver Name:"):
            # Save previous driver if exists
            if current_driver and 'name' in current_driver:
                drivers.append(current_driver)

            # Start new driver
            current_driver = {}
            driver_section_active = True
            current_driver['name'] = line.replace("Driver Name:", "").strip()

        # If we're in a driver section, process driver fields
        elif driver_section_active and line.startswith("•"):
            if current_driver is not None:
                line = line.replace('•', '').strip()
                if ':' in line:
                    # Check if this line contains suggestion text (shouldn't be in driver fields)
                    if any(pattern.lower() in line.lower() for pattern in suggestion_patterns):
                        # This is actually the suggestion, not a driver field
                        suggestion = line
                        driver_section_active = False
                    else:
                        key, value = line.split(':', 1)
                        key = key.strip().lower().replace(' ', '_')

                        # Fix the key names
                        if key == 'price_per_km':
                            key = 'price_per_km'
                        elif key == 'car_name':
                            key = 'car_name'
                        elif key == 'profile_url':
                            key = 'profile_url'
                        elif key == 'driver_id':
                            key = 'driver_id'
                        elif key == 'profile_image':
                            key = 'profile_image'
                        elif key == 'lastaccess':
                            key = 'lastaccess'
                        elif key == 'mobileno':
                            key = 'mobileno'

                        current_driver[key] = value.strip()

        # Check if this line is the suggestion (not part of driver info)
        elif any(pattern in line for pattern in suggestion_patterns):
            # Save current driver if exists
            if current_driver and 'name' in current_driver:
                drivers.append(current_driver)
                current_driver = None
                driver_section_active = False

            # Collect all remaining lines as suggestion
            suggestion_lines = [line]
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    suggestion_lines.append(lines[j].strip())
            suggestion = " ".join(suggestion_lines)
            break

    # Save last driver if exists
    if current_driver and 'name' in current_driver:
        drivers.append(current_driver)

    # Clean up drivers - remove any fields that contain suggestion text
    cleaned_drivers = []
    for driver in drivers:
        cleaned_driver = {}
        for key, value in driver.items():
            # Check if this field accidentally contains the suggestion
            if isinstance(value, str) and any(pattern.lower() in value.lower() for pattern in suggestion_patterns):
                # Don't include this field, it's part of the suggestion
                if not suggestion:
                    suggestion = value
            else:
                cleaned_driver[key] = value
        cleaned_drivers.append(cleaned_driver)

    return {"drivers": cleaned_drivers, "suggestion": suggestion}


@app.post("/chat")
async def chat_with_bot(chat_request: ChatRequest):
    """
    Handles a chat message from a user and returns the bot's response.
    Maintains conversation context using async Redis-backed sessions.
    """
    customer_details = {
        "customer_id": chat_request.customer_id,
        "customer_name": chat_request.customer_name,
        "customer_profile": chat_request.customer_profile,
        "customer_phone": chat_request.customer_phone,
    }

    response = await process_message_async(chat_request.user_id, chat_request.message, customer_details)

    # Check if response contains driver listing pattern
    if "Driver Name:" in response and "• City:" in response:
        # Parse the driver list
        parsed_response = parse_driver_string(response)

        # Ensure we have a valid structure
        if not parsed_response.get("suggestion"):
            # Extract suggestion from response if it wasn't properly parsed
            lines = response.split('\n')
            for line in reversed(lines):
                if any(keyword in line for keyword in ["Here are", "Want me to check", "Tip:", "You can also"]):
                    parsed_response["suggestion"] = line.strip()
                    break

        return {"response": parsed_response, "type": "driverList"}
    else:
        return {"response": response, "type": "text"}


@app.post("/slack/events")
async def handle_slack_events(request: Request):
    """Handle Slack events with async Redis-backed session management"""
    data = await request.json()

    if "challenge" in data:
        return {"challenge": data["challenge"]}

    event = data.get("event", {})
    if (event.get("type") == "message" and
            "bot_id" not in event and
            "subtype" not in event):

        if await is_duplicate_message(event):
            return {"status": "ok"}

        user_id = event.get("user")
        channel = event.get("channel")
        text = event.get("text", "").strip()
        channel_type = event.get("channel_type", "")

        if not text:
            return {"status": "ok"}

        logger.info(f"📨 Processing: {user_id} -> {text} (channel: {channel}, type: {channel_type})")

        # Send immediate acknowledgment for search queries
        if any(keyword in text.lower() for keyword in ['driver', 'cab', 'jaipur', 'delhi', 'mumbai', 'find', 'book']):
            try:
                await async_slack_client.chat_postMessage(
                    channel=channel,
                    text=f"🚗 Thinking...",
                    as_user=False,
                    username="Cab Bot"
                )
                logger.info("📤 Sent immediate acknowledgment")
            except Exception as ack_error:
                logger.warning(f"⚠️ Failed to send acknowledgment: {ack_error}")

        # Process message asynchronously
        response = await process_message_async(user_id, text)

        if not response or not response.strip():
            response = "I'm here to help you find drivers! Please tell me your pickup location."

        # Try to send response
        success = False

        try:
            await async_slack_client.chat_postMessage(
                channel=channel,
                text=f"🚗 {response}"
            )
            logger.info(f"✅ Sent response to channel {channel}")
            success = True
        except Exception as e:
            logger.error(f"❌ Failed to send to channel {channel}: {e}")

        if not success:
            try:
                dm_response = await async_slack_client.conversations_open(users=[user_id])
                if dm_response["ok"]:
                    dm_channel = dm_response["channel"]["id"]
                    await async_slack_client.chat_postMessage(
                        channel=dm_channel,
                        text=f"🚗 {response}\n\n_Note: I'm replying here because I don't have access to send messages in the other channel._"
                    )
                    logger.info(f"✅ Sent as DM to {user_id} via opened conversation")
                    success = True
            except Exception as dm_error:
                logger.error(f"❌ Failed to send DM: {dm_error}")

        if not success:
            logger.error(f"❌ Complete failure to send message to user {user_id}")

    return {"status": "ok"}


@app.post("/slack/commands")
async def handle_slash_commands(request: Request):
    """Handle /cab slash command with async Redis sessions"""
    form_data = await request.form()
    user_id = form_data.get("user_id")
    text = form_data.get("text", "").strip()

    if not text:
        response = "🚗 Tell me your pickup location!\nExample: `/cab I need drivers in Jaipur`"
    else:
        response = await process_message_async(user_id, text)

    return {"text": f"🚗 {response}"}


@app.get("/test_agent/{message}")
async def test_agent_directly(message: str):
    """Test the agent directly without Slack to debug issues"""
    try:
        test_user = "test_user"
        response = await process_message_async(test_user, message)
        state = await get_user_state(test_user)

        return {
            "message": message,
            "response": response,
            "response_length": len(response),
            "state_keys": list(state.to_dict().keys()),
            "chat_history_length": len(state.chat_history),
            "drivers_count": len(state.all_fetched_drivers),
            "trip_details": {
                "trip_id": state.trip_id,
                "pickup": state.pickup_location,
                "drop": state.drop_location,
                "start_date": state.start_date,
                "end_date": state.end_date,
            },
            "last_bot_response": state.last_bot_response[:100] + "..." if state.last_bot_response and len(state.last_bot_response) > 100 else state.last_bot_response
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/debug/{user_id}")
async def debug_user(user_id: str):
    """Debug user state from Redis"""
    state = await get_user_state(user_id)

    if state:
        session_info = await redis_manager.get_session_info(user_id)
        return {
            "user_id": user_id,
            "session_info": session_info,
            "messages": len(state.chat_history),
            "drivers": len(state.all_fetched_drivers),
            "pickup": state.pickup_location,
            "drop": state.drop_location,
            "trip_id": state.trip_id,
            "start_date": state.start_date,
            "end_date": state.end_date,
            "customer_name": state.customer_name,
            "last_response": state.last_bot_response[:200] + "..." if state.last_bot_response and len(state.last_bot_response) > 200 else state.last_bot_response,
        }
    return {"error": "User session not found"}


@app.get("/sessions")
async def get_all_sessions():
    """Get information about all active sessions"""
    active_users = await redis_manager.get_all_active_sessions()
    sessions_info = []

    for user_id in active_users:
        info = await redis_manager.get_session_info(user_id)
        if info:
            sessions_info.append(info)

    redis_health = await redis_manager.health_check()

    return {
        "total_active_sessions": len(active_users),
        "sessions": sessions_info,
        "fallback_storage_users": len(fallback_storage),
        "redis_health": redis_health
    }


@app.delete("/session/{user_id}")
async def delete_session(user_id: str):
    """Manually delete a user session"""
    deleted = await clear_user_session(user_id)
    return {
        "user_id": user_id,
        "deleted": deleted,
        "message": "Session cleared successfully" if deleted else "Session not found or deletion failed"
    }


@app.get("/clear_cache")
async def clear_cache():
    """Clear all sessions and caches (for debugging)"""
    # Get all active sessions
    active_users = await redis_manager.get_all_active_sessions()
    cleared_count = 0

    for user_id in active_users:
        if await clear_user_session(user_id):
            cleared_count += 1

    # Clear fallback storage
    fallback_count = len(fallback_storage)
    fallback_storage.clear()

    return {
        "status": "Cache cleared",
        "redis_sessions_cleared": cleared_count,
        "fallback_storage_cleared": fallback_count
    }


@app.get("/")
async def home():
    """Simple status page with Redis info"""
    redis_health = await redis_manager.health_check()
    active_sessions = await redis_manager.get_all_active_sessions()

    return {
        "status": "running",
        "bot": "Cab Booking Assistant",
        "active_sessions": len(active_sessions),
        "fallback_storage_users": len(fallback_storage),
        "redis_status": redis_health.get("status"),
        "redis_available": redis_health.get("redis_available"),
        "endpoints": {
            "chat": "/chat (POST)",
            "slack_events": "/slack/events (POST)",
            "slack_commands": "/slack/commands (POST)",
            "test_agent": "/test_agent/{message} (GET)",
            "debug": "/debug/{user_id} (GET)",
            "sessions": "/sessions (GET)",
            "delete_session": "/session/{user_id} (DELETE)",
            "clear_cache": "/clear_cache (GET)",
            "health": "/health (GET)"
        }
    }


@app.get("/health")
async def health():
    """Health check with Redis status"""
    redis_health = await redis_manager.health_check()

    return {
        "status": "healthy",
        "redis": redis_health,
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn

    # Check environment
    if not os.environ.get("SLACK_BOT_TOKEN"):
        print("⚠️ SLACK_BOT_TOKEN not set. Slack integration will not work.")
        print("   For Slack integration: export SLACK_BOT_TOKEN='xoxb-your-token'")
        print("   Web API will still work without Slack token.\n")

    print("\n🚀 Starting Cab Booking Bot API with Async Redis Session Management")

    port = int(os.environ.get("PORT", 8080))
    print(f"📍 Server running on: http://localhost:{port}")
    print(f"📊 Test the agent: http://localhost:{port}/test_agent/I need a cab from Delhi to Mumbai")
    print(f"💬 Chat API endpoint: http://localhost:{port}/chat")
    print(f"📈 View active sessions: http://localhost:{port}/sessions")

    uvicorn.run(app, host="0.0.0.0", port=port)
