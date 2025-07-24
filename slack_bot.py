"""
Simple Slack Bot for Cab Booking Assistant
KISS principle: Keep It Simple, Stupid
"""

import os
from fastapi import FastAPI, Request
from slack_sdk import WebClient
from langchain_core.messages import HumanMessage

# Import your existing agent
from langgraph_agent.graph.builder import app as cab_agent

# Simple setup
slack_bot = FastAPI(title="Cab Booking Slack Bot")
slack_client = WebClient(token=os.environ.get("SLACK_BOT_TOKEN"))

# Simple in-memory storage (for demo - use Redis/DB in production)
user_conversations = {}
processed_messages = set()  # Track processed messages to avoid duplicates

def get_user_state(user_id: str) -> dict:
    """Get or create user conversation state"""
    if user_id not in user_conversations:
        user_conversations[user_id] = {
            "chat_history": [],
            "drivers_with_full_details": [],
            "filtered_drivers": [],
            "applied_filters": {},
            "pickup_location": None,
            "last_bot_response": None,
            "tool_calls": []
        }
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

def process_message(user_id: str, message: str) -> str:
    """Process user message through cab agent - OPTIMIZED"""
    print(f"🔄 Processing for {user_id}: {message}")
    
    # Get user state
    state = get_user_state(user_id)
    
    # Handle simple commands
    if message.lower().strip() == "reset":
        user_conversations[user_id] = get_user_state("new_user")  # Reset
        return "🔄 Reset! Tell me your pickup location to find drivers."
    
    # Add message to chat history
    state["chat_history"].append(HumanMessage(content=message))
    
    # Process through your existing agent with timeout
    try:
        print(f"🤖 Invoking agent...")
        import signal
        
        # Set a timeout for the agent call
        def timeout_handler(signum, frame):
            raise TimeoutError("Agent call timed out")
        
        # Set timeout to 45 seconds
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(45)
        
        try:
            result = cab_agent.invoke(state)
        finally:
            signal.alarm(0)  # Cancel the alarm
        
        # Ensure result is valid
        if not isinstance(result, dict):
            print(f"⚠️ Agent returned non-dict: {type(result)}")
            return "Sorry, I had a technical issue. Please try again."
        
        # Update state
        user_conversations[user_id] = result
        print(f"✅ State updated for {user_id}")
        
        # Extract response with better fallbacks
        response = None
        
        # Try 1: Direct last_bot_response
        if result.get("last_bot_response"):
            response = result["last_bot_response"]
            print(f"📤 Got direct response: {response[:50]}...")
        
        # Try 2: Last AI message from chat history
        if not response:
            chat_history = result.get("chat_history", [])
            for msg in reversed(chat_history):
                if hasattr(msg, 'content') and 'AI' in str(type(msg)):
                    if msg.content and msg.content.strip():
                        response = msg.content
                        print(f"📤 Got AI message: {response[:50]}...")
                        break
        
        # Try 3: Check if we have drivers and create a response
        if not response:
            drivers = result.get("drivers_with_full_details", [])
            filtered_drivers = result.get("filtered_drivers", [])
            
            if drivers or filtered_drivers:
                response = f"I found {len(drivers or filtered_drivers)} drivers for you. Please let me know what specific information you'd like about them."
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
        import traceback
        traceback.print_exc()
        return "Sorry, I had an issue processing your request. Please try again or type 'reset'."

@slack_bot.post("/slack/events")
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
                    text="🔍 Searching for drivers... This may take a moment."
                )
                print("📤 Sent immediate acknowledgment")
            except Exception as ack_error:
                print(f"⚠️ Failed to send acknowledgment: {ack_error}")
                # Don't fail the whole process if acknowledgment fails
        
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
                # First open a DM conversation with the user
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
            # You might want to store this in a database or send to an error channel
    
    return {"status": "ok"}

@slack_bot.post("/slack/commands")
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

@slack_bot.get("/test_agent/{message}")
async def test_agent_directly(message: str):
    """Test the agent directly without Slack to debug issues"""
    try:
        test_user = "test_user"
        response = process_message(test_user, message)
        state = user_conversations.get(test_user, {})
        
        return {
            "message": message,
            "response": response,
            "response_length": len(response),
            "state_keys": list(state.keys()),
            "chat_history_length": len(state.get("chat_history", [])),
            "drivers_count": len(state.get("drivers_with_full_details", [])),
            "last_bot_response": state.get("last_bot_response", "")[:100] + "..."
        }
    except Exception as e:
        return {"error": str(e)}

@slack_bot.get("/debug/{user_id}")
async def debug_user(user_id: str):
    """Debug user state"""
    if user_id in user_conversations:
        state = user_conversations[user_id]
        return {
            "user_id": user_id,
            "messages": len(state.get("chat_history", [])),
            "drivers": len(state.get("drivers_with_full_details", [])),
            "pickup": state.get("pickup_location"),
            "last_response": state.get("last_bot_response", "")[:200] + "...",
            "processed_messages_count": len(processed_messages)
        }
    return {"error": "User not found"}

@slack_bot.get("/clear_cache")
async def clear_cache():
    """Clear message cache and user states (for debugging)"""
    global processed_messages, user_conversations
    processed_messages.clear()
    user_conversations.clear()
    return {"status": "Cache cleared"}

@slack_bot.get("/")
async def home():
    """Simple status page"""
    return {
        "status": "running",
        "bot": "Cab Booking Assistant", 
        "active_users": len(user_conversations),
        "processed_messages": len(processed_messages),
        "endpoints": {
            "events": "/slack/events",
            "commands": "/slack/commands", 
            "debug": "/debug/{user_id}",
            "clear_cache": "/clear_cache",
            "health": "/health"
        }
    }

@slack_bot.get("/health")
async def health():
    """Health check"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    
    # Check environment
    if not os.environ.get("SLACK_BOT_TOKEN"):
        print("❌ Set SLACK_BOT_TOKEN environment variable")
        print("   export SLACK_BOT_TOKEN='xoxb-your-token'")
        exit(1)
    
    print("🚀 Starting Cab Booking Slack Bot")
    print("📍 Server: http://localhost:8000")
    print("🔗 Slack Events URL: https://your-ngrok-url.ngrok.io/slack/events")
    
    uvicorn.run(slack_bot, host="0.0.0.0", port=8000)