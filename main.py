# main.py
import os
import config
import logging
from typing import Dict, Any
from datetime import datetime

from fastapi import FastAPI, Request
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

# Store user conversations
user_conversations = {}


def get_user_state(user_id: str) -> dict:
    """Get or create user conversation state"""
    if user_id not in user_conversations:
        user_conversations[user_id] = {
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
    return user_conversations[user_id]


def process_message(user_id: str, message: str) -> str:
    """Process user message through cab agent"""
    logger.info(f"Processing message from {user_id}: {message}")

    # Get user state
    state = get_user_state(user_id)

    # Handle reset
    if message.lower().strip() == "reset":
        user_conversations[user_id] = get_user_state("new_user")
        return "🔄 Reset! Tell me your pickup location to find drivers."

    # Add message to chat history
    state["chat_history"].append(HumanMessage(content=message))

    try:
        # Process through agent
        result = cab_agent.invoke(state)

        # Update state
        user_conversations[user_id] = result

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
        return "Sorry, I encountered an error. Please try again or type 'reset'."


@slack_bot.post("/slack/events")
async def handle_slack_events(request: Request):
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

        # Process message
        response = process_message(user_id, text)

        # Send response
        slack_service.send_message(channel, f"🚗 {response}")

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
        response = process_message(user_id, text)

    return {"text": f"🚗 {response}"}


@slack_bot.get("/")
async def home():
    """Status page"""
    return {
        "status": "running",
        "bot": "Cab Booking Assistant",
        "active_users": len(user_conversations),
    }


@slack_bot.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    if not config.SLACK_BOT_TOKEN:
        print("❌ Set SLACK_BOT_TOKEN environment variable")
        exit(1)

    print(f"🚀 Starting Cab Booking Slack Bot on port {config.PORT}")
    uvicorn.run(slack_bot, host="0.0.0.0", port=config.PORT)

