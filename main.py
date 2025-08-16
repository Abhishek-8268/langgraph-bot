import os
import signal
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request
from slack_sdk import WebClient
from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import traceback

# Import your agent and state model
from langgraph_agent.graph.builder import app as cab_agent
from models.state_model import ConversationState

# Simple setup
app = FastAPI(title="Cab Booking Bot")
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

# Simple in-memory storage (for demo - use Redis/DB in production)
user_conversations: Dict[str, ConversationState] = {}
processed_messages = set()  # Track processed messages to avoid duplicates


# --- Pydantic model for the /chat endpoint ---
class ChatRequest(BaseModel):
    user_id: str
    message: str
    customer_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_profile: Optional[str] = None
    customer_phone: Optional[str] = None


def get_user_state(user_id: str) -> ConversationState:
    """Get or create user conversation state using Pydantic model"""
    if user_id not in user_conversations:
        # Create new state using Pydantic model
        user_conversations[user_id] = ConversationState(
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
            customer_id=None,
            customer_name=None,
            customer_phone=None,
            customer_profile=None,
            last_bot_response=None,
            tool_calls=[]
        )
    return user_conversations[user_id]


def is_duplicate_message(event: dict) -> bool:
    """Check if this event was already processed using multiple identifiers"""
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
            print(f"🔄 Duplicate detected: {identifier}")
            return True

    # Add all identifiers to processed set
    for identifier in identifiers:
        processed_messages.add(identifier)

    # Keep only last 200 messages to prevent memory leak
    if len(processed_messages) > 200:
        # Keep only the newest 100
        new_set = set(list(processed_messages)[-100:])
        processed_messages.clear()
        processed_messages.update(new_set)

    return False


def process_message(user_id: str, message: str, customer_details: dict = {}) -> str:
    """Process user message through cab agent with Pydantic state management"""
    print(f"🔄 Processing for {user_id}: {message}")

    # Get user state (Pydantic model)
    state_model = get_user_state(user_id)

    # Update customer details if provided
    if customer_details:
        state_model.customer_id = customer_details.get("customer_id")
        state_model.customer_name = customer_details.get("customer_name")
        state_model.customer_profile = customer_details.get("customer_profile")
        state_model.customer_phone = customer_details.get("customer_phone")

    # Handle simple commands
    if message.lower().strip() == "reset":
        # Clear the specific user's conversation
        if user_id in user_conversations:
            # Reset the state using Pydantic model's reset method
            user_conversations[user_id].reset()
        return "🔄 Reset! Let's start fresh. Where would you like to travel?"

    # Add message to chat history
    state_model.chat_history.append(HumanMessage(content=message))

    # Convert Pydantic model to dict for the agent
    state_dict = state_model.to_dict()

    # Process through your existing agent with timeout
    try:
        print(f"🤖 Invoking agent...")

        # Set a timeout for the agent call
        def timeout_handler(signum, frame):
            raise TimeoutError("Agent call timed out")

        # Set timeout to 45 seconds
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(45)

        try:
            result = cab_agent.invoke(state_dict)
        finally:
            signal.alarm(0)  # Cancel the alarm

        # Ensure result is valid
        if not isinstance(result, dict):
            print(f"⚠️ Agent returned non-dict: {type(result)}")
            return "Sorry, I had a technical issue. Please try again."

        # Update the Pydantic state model from the result
        # We update only the fields that the agent might have modified
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

        print(f"✅ State updated for {user_id}")

        # Extract response with better fallbacks
        response = None

        # Try 1: Direct last_bot_response
        if state_model.last_bot_response:
            response = state_model.last_bot_response
            print(f"📤 Got direct response: {response[:50] if len(response) > 50 else response}...")

        # Try 2: Last AI message from chat history
        if not response:
            for msg in reversed(state_model.chat_history):
                if hasattr(msg, 'content') and 'AI' in str(type(msg)):
                    if msg.content and msg.content.strip():
                        response = msg.content
                        print(f"📤 Got AI message: {response[:50] if len(response) > 50 else response}...")
                        break

        # Try 3: Check if we have drivers and create a response
        if not response:
            if state_model.all_fetched_drivers:
                response = f"I found {len(state_model.all_fetched_drivers)} drivers for you. Please let me know what specific information you'd like about them."
                print(f"📤 Generated fallback response")

        # Final fallback
        if not response or not response.strip():
            response = "I'm here to help you find drivers! Please tell me your pickup location or what you're looking for."
            print(f"📤 Using final fallback response")

        return response

    except TimeoutError:
        print(f"⏰ Agent call timed out for {user_id}")
        return "Sorry, that request is taking too long. Please try again with a simpler query or type 'reset'."
    except Exception as e:
        print(f"❌ Error processing message: {e}")
        traceback.print_exc()
        return "Sorry, I had an issue processing your request. Please try again or type 'reset'."


def parse_driver_string(response_str: str) -> Dict[str, Any]:
    """Parses the string representation of drivers into a structured dictionary."""
    drivers = []
    # Split the response by double newlines to separate driver blocks and the suggestion text
    blocks = response_str.strip().split('\n\n')

    suggestion = ""
    driver_blocks = []

    # Separate driver blocks from the suggestion text
    for block in blocks:
        if "Driver Name:" in block:
            driver_blocks.append(block)
        else:
            suggestion = block.strip()

    for block in driver_blocks:
        driver = {}
        lines = block.strip().split('\n')

        # First line is always "Driver Name: ..."
        try:
            driver['name'] = lines[0].replace('Driver Name:', '').strip()
        except IndexError:
            continue  # Skip empty blocks

        # Other lines are "• Key: Value"
        for line in lines[1:]:
            line = line.replace('•', '').strip()
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip().lower().replace(' ', '_').replace('per_km', 'price_per_km')
                driver[key] = value.strip()
        drivers.append(driver)

    return {"drivers": drivers, "suggestion": suggestion}


# --- API Endpoint for App Integration ---
@app.post("/chat")
async def chat_with_bot(chat_request: ChatRequest):
    """
    Handles a chat message from a user and returns the bot's response.
    Maintains conversation context using user_id.
    """
    customer_details = {
        "customer_id": chat_request.customer_id,
        "customer_name": chat_request.customer_name,
        "customer_profile": chat_request.customer_profile,
        "customer_phone": chat_request.customer_phone,
    }
    response = process_message(chat_request.user_id, chat_request.message, customer_details)

    # Check if the response contains driver details to parse it
    if "Driver Name:" in response and "• City:" in response:
        response_json = parse_driver_string(response)
        return {"response": response_json, "type": "driverList"}
    else:
        # Otherwise, return the plain text response
        return {"response": response, "type": "text"}


@app.post("/slack/events")
async def handle_slack_events(request: Request):
    """Handle Slack events - FIXED for multi-user access"""
    data = await request.json()

    # URL verification
    if "challenge" in data:
        return {"challenge": data["challenge"]}

    # Handle messages
    event = data.get("event", {})
    if (event.get("type") == "message" and
            "bot_id" not in event and
            "subtype" not in event):

        # Skip if duplicate event
        if is_duplicate_message(event):
            return {"status": "ok"}

        user_id = event.get("user")
        channel = event.get("channel")
        text = event.get("text", "").strip()
        channel_type = event.get("channel_type", "")

        # Skip if no text
        if not text:
            return {"status": "ok"}

        print(f"📨 Processing: {user_id} -> {text} (channel: {channel}, type: {channel_type})")

        # Send immediate acknowledgment for search queries
        if any(keyword in text.lower() for keyword in ['driver', 'cab', 'jaipur', 'delhi', 'mumbai', 'find', 'book']):
            try:
                # Try to send acknowledgment
                slack_client.chat_postMessage(
                    channel=channel,
                    text=f"🚗 Thinking...",
                    as_user=False,
                    username="Cab Bot"
                )
                print("📤 Sent immediate acknowledgment")
            except Exception as ack_error:
                print(f"⚠️ Failed to send acknowledgment: {ack_error}")

        # Process message (this is the slow part)
        response = process_message(user_id, text)

        # Ensure we have a valid response
        if not response or not response.strip():
            response = "I'm here to help you find drivers! Please tell me your pickup location."

        # Send final response with multiple fallback strategies
        success = False

        # Strategy 1: Try original channel
        try:
            slack_client.chat_postMessage(
                channel=channel,
                text=f"🚗 {response}"
            )
            print(f"✅ Sent response to channel {channel}")
            success = True
        except Exception as e:
            print(f"❌ Failed to send to channel {channel}: {e}")

        # Strategy 2: If channel failed, try user DM with conversation
        if not success:
            try:
                dm_response = slack_client.conversations_open(users=[user_id])
                if dm_response["ok"]:
                    dm_channel = dm_response["channel"]["id"]
                    slack_client.chat_postMessage(
                        channel=dm_channel,
                        text=f"🚗 {response}\n\n_Note: I'm replying here because I don't have access to send messages in the other channel._"
                    )
                    print(f"✅ Sent as DM to {user_id} via opened conversation")
                    success = True
                else:
                    print(f"❌ Failed to open DM with {user_id}: {dm_response}")
            except Exception as dm_error:
                print(f"❌ Failed to send DM via conversation: {dm_error}")

        # Strategy 3: Last resort - try direct user ID
        if not success:
            try:
                slack_client.chat_postMessage(
                    channel=user_id,
                    text=f"🚗 {response}\n\n_Note: Having trouble with channel permissions. You might need to add me to the channel or your admin needs to update my permissions._"
                )
                print(f"✅ Sent as direct DM to {user_id}")
                success = True
            except Exception as direct_error:
                print(f"❌ Failed direct DM: {direct_error}")

        # Strategy 4: If all else fails, log the issue
        if not success:
            print(f"❌ COMPLETE FAILURE to send message to user {user_id}")
            print(f"   Response was: {response[:100]}...")

    return {"status": "ok"}


@app.post("/slack/commands")
async def handle_slash_commands(request: Request):
    """Handle /cab slash command"""
    form_data = await request.form()
    user_id = form_data.get("user_id")
    text = form_data.get("text", "").strip()

    if not text:
        response = "🚗 Tell me your pickup location!\nExample: `/cab I need drivers in Jaipur`"
    else:
        response = process_message(user_id, text)

    return {"text": f"🚗 {response}"}


@app.get("/test_agent/{message}")
async def test_agent_directly(message: str):
    """Test the agent directly without Slack to debug issues"""
    try:
        test_user = "test_user"
        response = process_message(test_user, message)
        state = get_user_state(test_user)

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
    """Debug user state"""
    if user_id in user_conversations:
        state = user_conversations[user_id]
        return {
            "user_id": user_id,
            "messages": len(state.chat_history),
            "drivers": len(state.all_fetched_drivers),
            "pickup": state.pickup_location,
            "drop": state.drop_location,
            "trip_id": state.trip_id,
            "start_date": state.start_date,
            "end_date": state.end_date,
            "customer_name": state.customer_name,
            "last_response": state.last_bot_response[:200] + "..." if state.last_bot_response and len(state.last_bot_response) > 200 else state.last_bot_response,
            "processed_messages_count": len(processed_messages)
        }
    return {"error": "User not found"}


@app.get("/clear_cache")
async def clear_cache():
    """Clear message cache and user states (for debugging)"""
    global processed_messages, user_conversations
    processed_messages.clear()
    user_conversations.clear()
    return {"status": "Cache cleared"}


@app.get("/")
async def home():
    """Simple status page"""
    return {
        "status": "running",
        "bot": "Cab Booking Assistant",
        "active_users": len(user_conversations),
        "processed_messages": len(processed_messages),
        "endpoints": {
            "chat": "/chat (POST)",
            "slack_events": "/slack/events (POST)",
            "slack_commands": "/slack/commands (POST)",
            "test_agent": "/test_agent/{message} (GET)",
            "debug": "/debug/{user_id} (GET)",
            "clear_cache": "/clear_cache (GET)",
            "health": "/health (GET)"
        }
    }


@app.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    # Check environment
    if not os.environ.get("SLACK_BOT_TOKEN"):
        print("⚠️ SLACK_BOT_TOKEN not set. Slack integration will not work.")
        print("   For Slack integration: export SLACK_BOT_TOKEN='xoxb-your-token'")
        print("   Web API will still work without Slack token.\n")

    print("🚀 Starting Cab Booking Bot API")

    port = int(os.environ.get("PORT", 8080))
    print(f"📍 Server running on: http://localhost:{port}")
    print(f"📊 Test the agent: http://localhost:{port}/test_agent/I need a cab from Delhi to Mumbai")
    print(f"💬 Chat API endpoint: http://localhost:{port}/chat")

    uvicorn.run(app, host="0.0.0.0", port=port)
