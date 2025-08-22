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

    # Create new session WITH customer details
    logger.info(f"🆕 Creating new session for {user_id}")
    new_state = ConversationState(
        chat_history=[],
        applied_filters={},
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
        tool_calls=[],
        booking_status=None,
        drivers_notified=0
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

    # Get user state from Redis/fallback - IMPORTANT: Pass customer details
    state_model = await get_user_state(user_id, customer_details)

    # Handle simple commands
    if message.lower().strip() in ["reset", "start over", "restart"]:
        # Clear the session from Redis
        await clear_user_session(user_id)
        return "🔄 Let's start fresh! Please tell me your pickup city, destination, travel date, and whether it's a one-way or round trip."

    # Add message to chat history
    state_model.chat_history.append(HumanMessage(content=message))

    # Convert Pydantic model to dict for the agent - INCLUDE ALL STATE FIELDS
    state_dict = state_model.to_dict()

    # Process through agent in executor (since it's sync)
    try:
        logger.info(f"🤖 Invoking agent...")

        # Run the sync agent in a thread pool to avoid blocking
        loop = asyncio.get_event_loop()

        # Increased timeout for background operations
        result = await asyncio.wait_for(
            loop.run_in_executor(None, cab_agent.invoke, state_dict),
            timeout=60.0  # Increased timeout for trip creation + availability check
        )

        # Ensure result is valid
        if not isinstance(result, dict):
            logger.warning(f"⚠️ Agent returned non-dict: {type(result)}")
            return "Sorry, I had a technical issue. Please try again."

        # Update the Pydantic state model from the result - ONLY UPDATE FIELDS THAT EXIST
        # IMPORTANT: Update ALL fields, including those set during agent_node execution
        state_model.chat_history = result.get("chat_history", state_model.chat_history)
        state_model.applied_filters = result.get("applied_filters", state_model.applied_filters)

        # Update trip details - these might be set in agent_node even without tool calls
        if result.get("trip_id") is not None:
            state_model.trip_id = result.get("trip_id")
        if result.get("pickup_location") is not None:
            state_model.pickup_location = result.get("pickup_location")
        if result.get("drop_location") is not None:
            state_model.drop_location = result.get("drop_location")
        if result.get("trip_type") is not None:
            state_model.trip_type = result.get("trip_type")
        if result.get("start_date") is not None:
            state_model.start_date = result.get("start_date")
        if result.get("end_date") is not None:
            state_model.end_date = result.get("end_date")

        state_model.last_bot_response = result.get("last_bot_response", state_model.last_bot_response)
        state_model.tool_calls = result.get("tool_calls", state_model.tool_calls)

        if result.get("booking_status") is not None:
            state_model.booking_status = result.get("booking_status")
        if result.get("drivers_notified") is not None:
            state_model.drivers_notified = result.get("drivers_notified")

        # Save updated state to Redis
        await save_user_state(user_id, state_model)

        logger.info(f"✅ State updated and saved for {user_id}")

        # Extract response
        response = state_model.last_bot_response

        if not response or not response.strip():
            # Check last AI message
            for msg in reversed(state_model.chat_history):
                if hasattr(msg, 'content') and 'AI' in str(type(msg)):
                    if msg.content and msg.content.strip():
                        response = msg.content
                        break

        # Final fallback
        if not response or not response.strip():
            response = "I'm here to help you book an outstation cab. Please tell me your pickup city, destination, and travel date."

        # Extend session TTL on successful interaction
        await redis_manager.extend_session(user_id)

        return response

    except asyncio.TimeoutError:
        logger.error(f"⏰ Agent call timed out for {user_id}")
        return "The booking process is taking longer than expected. Please wait a moment and I'll update you on the status."
    except Exception as e:
        logger.error(f"❌ Error processing message: {e}")
        traceback.print_exc()
        return "Sorry, I encountered an issue processing your request. Please try again or type 'reset' to start over."


@app.post("/chat")
async def chat_with_bot(chat_request: ChatRequest):
    """
    Handles a chat message from a user and returns the bot's response.
    Simplified for new flow without driver display.
    """
    customer_details = {
        "customer_id": chat_request.customer_id,
        "customer_name": chat_request.customer_name,
        "customer_profile": chat_request.customer_profile,
        "customer_phone": chat_request.customer_phone,
    }

    response = await process_message_async(
        chat_request.user_id,
        chat_request.message,
        customer_details
    )

    # Return simplified response
    return {
        "type": "text",
        "response": response
    }


@app.get("/booking_status/{user_id}")
async def get_booking_status(user_id: str):
    """Check the status of a user's booking"""
    state = await get_user_state(user_id)

    if not state or not state.trip_id:
        return {
            "status": "no_booking",
            "message": "No active booking found"
        }

    return {
        "status": "active",
        "trip_id": state.trip_id,
        "route": f"{state.pickup_location} to {state.drop_location}",
        "trip_type": state.trip_type,
        "dates": {
            "start": state.start_date,
            "end": state.end_date
        },
        "preferences": state.applied_filters if state.applied_filters else "No specific preferences",
        "drivers_notified": state.drivers_notified
    }


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
                    text=f"🚗 Processing your request...",
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
        response = "🚗 Tell me your pickup location!\nExample: `/cab I need to go from Delhi to Jaipur tomorrow`"
    else:
        response = await process_message_async(user_id, text)

    return {"text": f"🚗 {response}"}


@app.get("/test_agent/{message}")
async def test_agent_directly(message: str):
    """Test the agent directly without Slack to debug issues"""
    try:
        test_user = "test_user"

        # Create test customer details
        test_customer = {
            "customer_id": "test_id",
            "customer_name": "Test User",
            "customer_phone": "9999999999",
            "customer_profile": "test_profile_url"
        }

        response = await process_message_async(test_user, message, test_customer)
        state = await get_user_state(test_user)

        return {
            "message": message,
            "response": response,
            "response_length": len(response),
            "state_keys": list(state.to_dict().keys()),
            "chat_history_length": len(state.chat_history),
            "trip_details": {
                "trip_id": state.trip_id,
                "pickup": state.pickup_location,
                "drop": state.drop_location,
                "start_date": state.start_date,
                "end_date": state.end_date,
            },
            "booking_status": state.booking_status,
            "drivers_notified": state.drivers_notified,
            "customer_details": {
                "id": state.customer_id,
                "name": state.customer_name,
                "phone": state.customer_phone
            },
            "last_bot_response": state.last_bot_response[:100] + "..." if state.last_bot_response and len(state.last_bot_response) > 100 else state.last_bot_response
        }
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


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
            "pickup": state.pickup_location,
            "drop": state.drop_location,
            "trip_id": state.trip_id,
            "start_date": state.start_date,
            "end_date": state.end_date,
            "customer_name": state.customer_name,
            "booking_status": state.booking_status,
            "drivers_notified": state.drivers_notified,
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
        "bot": "Cab Booking Assistant - Streamlined Flow",
        "version": "2.0",
        "active_sessions": len(active_sessions),
        "fallback_storage_users": len(fallback_storage),
        "redis_status": redis_health.get("status"),
        "redis_available": redis_health.get("redis_available"),
        "endpoints": {
            "chat": "/chat (POST)",
            "booking_status": "/booking_status/{user_id} (GET)",
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

    print("\n🚀 Starting Cab Booking Bot API - STREAMLINED FLOW v2.0")

    port = int(os.environ.get("PORT", 8080))
    print(f"📍 Server running on: http://localhost:{port}")
    print(f"📊 Test the agent: http://localhost:{port}/test_agent/I need a cab from Delhi to Mumbai tomorrow")
    print(f"💬 Chat API endpoint: http://localhost:{port}/chat")
    print(f"📈 View active sessions: http://localhost:{port}/sessions")

    uvicorn.run(app, host="0.0.0.0", port=port)
