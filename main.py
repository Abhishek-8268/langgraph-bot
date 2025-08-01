# main.py
import os
import config
import logging
import asyncio
from typing import Dict, Any
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, Request, BackgroundTasks
from slack_sdk import WebClient
from langchain_core.messages import HumanMessage

from langgraph_agent.graph.builder import app as cab_agent
from services.slack_service import SlackService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
slack_bot = FastAPI(title="Cab Booking Slack Bot")

# Initialize services
slack_service = SlackService()

# Store user conversations with timestamps
user_conversations = {}

# Thread pool for processing messages
executor = ThreadPoolExecutor(max_workers=10)

# Lock for thread-safe operations
conversations_lock = asyncio.Lock()


class UserSession:
    """User session with timestamp and state"""

    def __init__(self):
        self.state = {
            "chat_history": [],
            "all_fetched_drivers": [],
            "drivers_with_full_details": [],
            "filtered_drivers": [],
            "applied_filters": {},
            "pickup_location": None,
            "last_bot_response": None,
            "tool_calls": [],
            "current_display_index": 0,
            "current_page": 1,
            "fetch_count": 0,
        }
        self.last_activity = datetime.now()
        self.is_processing = False


async def cleanup_old_sessions():
    """Remove sessions older than 15 minutes"""
    while True:
        try:
            async with conversations_lock:
                current_time = datetime.now()
                expired_users = []

                for user_id, session in user_conversations.items():
                    if current_time - session.last_activity > timedelta(minutes=15):
                        expired_users.append(user_id)

                for user_id in expired_users:
                    del user_conversations[user_id]
                    logger.info(f"Cleaned up expired session for user {user_id}")

                if expired_users:
                    logger.info(f"Cleaned up {len(expired_users)} expired sessions")

        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

        # Run cleanup every 5 minutes
        await asyncio.sleep(300)


async def get_user_session(user_id: str) -> UserSession:
    """Get or create user session"""
    async with conversations_lock:
        if user_id not in user_conversations:
            user_conversations[user_id] = UserSession()

        session = user_conversations[user_id]
        session.last_activity = datetime.now()
        return session


def process_message_sync(state: dict, message: str) -> dict:
    """Synchronous message processing"""
    state["chat_history"].append(HumanMessage(content=message))

    try:
        # Process through agent
        result = cab_agent.invoke(state)
        return result
    except Exception as e:
        logger.error(f"Error in agent processing: {e}")
        raise


async def process_message_async(user_id: str, message: str) -> str:
    """Process user message asynchronously"""
    logger.info(f"Processing message from {user_id}: {message}")

    # Get user session
    session = await get_user_session(user_id)

    # Check if already processing
    if session.is_processing:
        return (
            "⏳ Your previous request is still being processed. Please wait a moment..."
        )

    # Handle reset
    if message.lower().strip() == "reset":
        async with conversations_lock:
            user_conversations[user_id] = UserSession()
        return "🔄 Reset! Tell me your pickup location to find drivers."

    # Handle max drivers reached
    if session.state.get("fetch_count", 0) >= config.MAX_FETCH_DEPTH:
        total_drivers = len(session.state.get("all_fetched_drivers", []))
        if total_drivers >= config.MAX_TOTAL_DRIVERS:
            # Still allow filtering on existing drivers
            if any(
                word in message.lower()
                for word in [
                    "filter",
                    "show",
                    "age",
                    "language",
                    "vehicle",
                    "pet",
                    "married",
                ]
            ):
                logger.info(f"Applying filter on {total_drivers} existing drivers")
            else:
                return f"I've already fetched the maximum of {config.MAX_TOTAL_DRIVERS} drivers. You can apply filters to find specific drivers or type 'reset' to start a new search."

    try:
        # Mark as processing
        session.is_processing = True

        # Run processing in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            process_message_sync,
            session.state.copy(),  # Pass a copy to avoid conflicts
            message,
        )

        # Update session state
        async with conversations_lock:
            session.state = result
            session.is_processing = False

        # Extract response
        response = result.get("last_bot_response")

        if not response:
            # Try to get from chat history
            for msg in reversed(result.get("chat_history", [])):
                if hasattr(msg, "content") and "AI" in str(type(msg)):
                    response = msg.content
                    break

        if not response:
            response = "I'm here to help you find drivers! Please tell me your pickup location."

        return response

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        session.is_processing = False
        return "Sorry, I encountered an error. Please try again or type 'reset'."


@slack_bot.on_event("startup")
async def startup_event():
    """Start background tasks on startup"""
    asyncio.create_task(cleanup_old_sessions())


@slack_bot.post("/slack/events")
async def handle_slack_events(request: Request, background_tasks: BackgroundTasks):
    """Handle Slack events"""
    data = await request.json()

    # URL verification
    if "challenge" in data:
        return {"challenge": data["challenge"]}

    # Handle messages
    event = data.get("event", {})
    if (
        event.get("type") == "message"
        and "bot_id" not in event
        and "subtype" not in event
    ):
        # Skip duplicates
        if slack_service.is_duplicate_message(event):
            return {"status": "ok"}

        user_id = event.get("user")
        channel = event.get("channel")
        text = event.get("text", "").strip()

        if not user_id or not text:
            return {"status": "ok"}

        logger.info(f"Message from {user_id}: {text}")

        # Process message asynchronously
        response = await process_message_async(user_id, text)

        # Send response in background to not block
        background_tasks.add_task(slack_service.send_message, channel, f"🚗 {response}")

    return {"status": "ok"}


@slack_bot.post("/slack/commands")
async def handle_slash_commands(request: Request):
    """Handle /cab slash command"""
    form_data = await request.form()
    user_id = form_data.get("user_id")
    text = form_data.get("text", "").strip()

    if not text:
        response = (
            "🚗 Tell me your pickup location!\nExample: `/cab I need drivers in Jaipur`"
        )
    else:
        response = await process_message_async(user_id, text)

    return {"text": f"🚗 {response}"}


@slack_bot.get("/")
async def home():
    """Status page"""
    active_sessions = len(user_conversations)
    processing_count = sum(1 for s in user_conversations.values() if s.is_processing)

    return {
        "status": "running",
        "bot": "Cab Booking Assistant",
        "active_sessions": active_sessions,
        "processing_requests": processing_count,
        "session_timeout": "15 minutes",
    }


@slack_bot.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy", "active_sessions": len(user_conversations)}


@slack_bot.get("/stats")
async def stats():
    """Get detailed statistics"""
    stats = {
        "total_sessions": len(user_conversations),
        "processing_sessions": sum(
            1 for s in user_conversations.values() if s.is_processing
        ),
        "sessions_by_state": {},
    }

    for user_id, session in user_conversations.items():
        drivers_count = len(session.state.get("all_fetched_drivers", []))
        fetch_count = session.state.get("fetch_count", 0)
        key = f"fetches_{fetch_count}_drivers_{drivers_count}"
        stats["sessions_by_state"][key] = stats["sessions_by_state"].get(key, 0) + 1

    return stats


if __name__ == "__main__":
    import uvicorn

    if not config.SLACK_BOT_TOKEN:
        print("❌ Set SLACK_BOT_TOKEN environment variable")
        exit(1)

    print(f"🚀 Starting Cab Booking Slack Bot on port {config.PORT}")
    uvicorn.run(slack_bot, host="0.0.0.0", port=config.PORT)
