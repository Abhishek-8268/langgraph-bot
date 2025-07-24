from langgraph_agent.graph.builder import app
from schemas.driver_schema import CabBookingState
from langchain_core.messages import HumanMessage, AIMessage




def initialize_state() -> dict:
    """Initialize the conversation state."""
    return {
        "chat_history": [],
        "drivers_with_full_details": [],
        "premium_drivers": [],
        "filtered_drivers": [],
        "applied_filters": {},
        "pickup_location": None,
        "drop_location": None,
        "passenger_count": None,
        "trip_type": None,
        "current_step": None,
        "selected_driver_id": None,
        "selected_driver_info": None,
        "booking_confirmed": False,
        "drivers_to_display": [],
        "last_bot_response": None,
        "filter_search_depth": 0,
        "max_filter_search_depth": 3,
        "page_no": 1,
        "no_more_drivers_from_api": False,
        "tool_calls": []
    }


def extract_bot_response(state: dict) -> str:
    """Extract the bot's response from the state."""
    try:
        # First check if there's a direct last_bot_response
        if isinstance(state, dict) and state.get("last_bot_response"):
            return state["last_bot_response"]
        
        # Otherwise, look for the last AI message in chat history
        chat_history = state.get("chat_history", []) if isinstance(state, dict) else []
        if chat_history:
            for msg in reversed(chat_history):
                if hasattr(msg, 'content') and hasattr(msg, '__class__'):
                    # Check if it's an AI message by class name
                    msg_type = str(type(msg))
                    if 'AI' in msg_type or 'Assistant' in msg_type:
                        if msg.content:
                            return msg.content
        
        return "I'm here to help you find drivers. What would you like to know?"
        
    except Exception as e:
        print(f"Debug - Error extracting response: {e}")
        return "I'm ready to help you with your cab booking needs."


def print_state_info(state: dict):
    """Print helpful state information for debugging."""
    try:
        drivers_count = len(state.get("drivers_with_full_details", []))
        filtered_count = len(state.get("filtered_drivers", []))
        pickup = state.get("pickup_location", "Not set")
        filters = state.get("applied_filters", {})
        
        if drivers_count > 0 or pickup != "Not set":
            print(f"\n📊 Status: {drivers_count} total drivers, {filtered_count} after filters")
            if pickup != "Not set":
                print(f"📍 Pickup: {pickup}")
            if filters:
                print(f"🔍 Active filters: {filters}")
            print()
    except Exception as e:
        print(f"Debug - Error printing state info: {e}")


def run_graph_safely(state: dict) -> dict:
    """Run the graph with better error handling."""
    try:
        # Use invoke instead of stream for more reliability
        print("🤔 Thinking...", end="", flush=True)
        
        final_state = app.invoke(state)
        
        # Clear the thinking message
        print("\r" + " " * 20 + "\r", end="", flush=True)
        
        # Ensure we got a valid state back
        if not isinstance(final_state, dict):
            print(f"⚠️ Warning: Got non-dict state: {type(final_state)}")
            return state
        
        # Ensure required keys exist
        required_keys = ["chat_history", "drivers_with_full_details", "filtered_drivers"]
        for key in required_keys:
            if key not in final_state:
                final_state[key] = state.get(key, [] if key.endswith("drivers") or key == "chat_history" else None)
        
        return final_state
        
    except Exception as e:
        print(f"\r❌ Error processing request: {e}")
        print(f"Debug - State keys: {list(state.keys()) if isinstance(state, dict) else 'Not a dict'}")
        
        # Return original state with error message
        error_state = dict(state)
        error_state["last_bot_response"] = "I encountered an issue processing your request. Please try again."
        return error_state


def main():
    """Main function to run the interactive cab booking bot."""
    
    # Initialize conversation state
    current_state = initialize_state()
    
    while True:
        try:
            # Get user input
            user_input = input("You: ").strip()
            
            # Handle exit command
            if user_input.lower() in ['exit', 'quit', 'bye']:
                print("\n👋 Bot: Thank you for using our cab booking service! Goodbye!")
                break
            
            # Handle empty input
            if not user_input:
                print("Bot: Please tell me what you need help with.")
                continue
            
            # Handle special commands
            if user_input.lower() == 'status':
                print_state_info(current_state)
                continue
            elif user_input.lower() == 'reset':
                current_state = initialize_state()
                print("Bot: I've reset our conversation. How can I help you today?")
                continue
            elif user_input.lower() == 'help':
                print("\n🆘 Available commands:")
                print("• 'status' - Show current booking status")
                print("• 'reset' - Start a new conversation")
                print("• 'help' - Show this help message")
                print("• 'exit' - End the conversation")
                print("\nOr just tell me what you need!")
                continue
            elif user_input.lower() == 'debug':
                print(f"\n🔍 Debug info:")
                print(f"State type: {type(current_state)}")
                if isinstance(current_state, dict):
                    print(f"State keys: {list(current_state.keys())}")
                    print(f"Chat history length: {len(current_state.get('chat_history', []))}")
                    print(f"Drivers count: {len(current_state.get('drivers_with_full_details', []))}")
                continue
            
            # Add user message to chat history
            if "chat_history" not in current_state:
                current_state["chat_history"] = []
            current_state["chat_history"].append(HumanMessage(content=user_input))
            
            # Process through the graph
            current_state = run_graph_safely(current_state)
            
            # Extract and display bot response
            bot_response = extract_bot_response(current_state)
            print(f"🤖 Bot: {bot_response}")
            
            # Show status if we have useful information
            if current_state.get("drivers_with_full_details") or current_state.get("pickup_location"):
                print_state_info(current_state)
                
        except KeyboardInterrupt:
            print("\n\n👋 Bot: Goodbye!")
            break
        except EOFError:
            print("\n\n👋 Bot: Goodbye!")
            break
        except Exception as e:
            print(f"\n❌ An unexpected error occurred: {e}")
            print("Bot: I encountered an issue. Please try again or type 'reset' to start over.")
            # Don't break the loop, just continue


if __name__ == "__main__":
    main()