#!/usr/bin/env python3
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

def process_message(user_id: str, message: str) -> str:
    """Process user message through cab agent"""
    # Get user state
    state = get_user_state(user_id)
    
    # Handle simple commands
    if message.lower().strip() == "reset":
        user_conversations[user_id] = get_user_state("new_user")  # Reset
        return "🔄 Reset! Tell me your pickup location to find drivers."
    
    # Add message to chat history
    state["chat_history"].append(HumanMessage(content=message))
    
    # Process through your existing agent
    try:
        result = cab_agent.invoke(state)
        user_conversations[user_id] = result  # Update state
        
        # Extract response
        if result.get("last_bot_response"):
            return result["last_bot_response"]
        
        # Fallback: get last AI message
        for msg in reversed(result.get("chat_history", [])):
            if hasattr(msg, 'content') and 'AI' in str(type(msg)):
                return msg.content
                
        return "I'm here to help you find drivers!"
        
    except Exception as e:
        print(f"Error: {e}")
        return "Sorry, I had an issue. Please try again or type 'reset'."

@slack_bot.post("/slack/events")
async def handle_slack_events(request: Request):
    """Handle Slack events - KISS version"""
    data = await request.json()
    
    # URL verification
    if "challenge" in data:
        return {"challenge": data["challenge"]}
    
    # Handle messages
    event = data.get("event", {})
    if (event.get("type") == "message" and 
        "bot_id" not in event and 
        "subtype" not in event):
        
        user_id = event.get("user")
        channel = event.get("channel") 
        text = event.get("text", "").strip()
        
        if text:
            # Process message
            response = process_message(user_id, text)
            
            # Send response
            try:
                slack_client.chat_postMessage(
                    channel=channel,
                    text=f"🚗 {response}"
                )
            except Exception as e:
                print(f"Failed to send message: {e}")
    
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

@slack_bot.get("/")
async def home():
    """Simple status page"""
    return {
        "status": "running",
        "bot": "Cab Booking Assistant", 
        "active_users": len(user_conversations)
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