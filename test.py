# test.py
"""Simple test to verify the agent works"""

import asyncio
from langchain_core.messages import HumanMessage

from langgraph_agent.graph.builder import app as cab_agent


def test_agent():
    """Test the agent with sample queries"""
    print("🧪 Testing Cab Booking Agent...\n")

    # Test 1: Simple city query
    print("Test 1: City query")
    state = {
        "chat_history": [HumanMessage(content="I need drivers in Jaipur")],
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

    result = cab_agent.invoke(state)
    print(f"Response: {result.get('last_bot_response', 'No response')}")
    print(f"Total drivers fetched: {len(result.get('all_fetched_drivers', []))}")
    print(f"Drivers shown: 5 (pagination enabled)\n")

    # Test 2: Filter query with specific criteria
    if result.get("all_fetched_drivers"):
        print("Test 2: Filter query - SUV and age < 30")
        state = result
        state["chat_history"].append(
            HumanMessage(content="Show me drivers with suv and age less than 30")
        )

        result = cab_agent.invoke(state)
        print(f"Response: {result.get('last_bot_response', 'No response')}")
        print(f"Filtered drivers: {len(result.get('filtered_drivers', []))}\n")

        # Test 3: Test language filter
        print("Test 3: Language filter - English speaking")
        state = result
        state["chat_history"].append(
            HumanMessage(content="show me english speaking drivers")
        )

        result = cab_agent.invoke(state)
        print(f"Response: {result.get('last_bot_response', 'No response')}")
        print(f"Filtered drivers: {len(result.get('filtered_drivers', []))}\n")

        # Test 4: Show more functionality
        print("Test 4: Show more drivers")
        state = result
        state["chat_history"].append(HumanMessage(content="show more"))

        result = cab_agent.invoke(state)
        print(f"Response: {result.get('last_bot_response', 'No response')}")
        print(f"Current display index: {result.get('current_display_index', 0)}\n")

        # Test 5: Pet friendly filter
        print("Test 5: Pet friendly filter")
        state["chat_history"].append(
            HumanMessage(content="show me pet friendly drivers")
        )

        result = cab_agent.invoke(state)
        print(f"Response: {result.get('last_bot_response', 'No response')}")
        print(f"Filtered drivers: {len(result.get('filtered_drivers', []))}\n")

    print("✅ Testing complete!")


if __name__ == "__main__":
    test_agent()
