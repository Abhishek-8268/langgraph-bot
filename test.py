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
        "drivers_with_full_details": [],
        "filtered_drivers": [],
        "applied_filters": {},
        "tool_calls": [],
    }

    result = cab_agent.invoke(state)
    print(f"Response: {result.get('last_bot_response', 'No response')}")
    print(f"Drivers found: {len(result.get('drivers_with_full_details', []))}\n")

    # Test 2: Filter query
    if result.get("drivers_with_full_details"):
        print("Test 2: Filter query")
        state = result
        state["chat_history"].append(
            HumanMessage(
                content="Show me drivers with suv and age less than 30 with his full details"
            )
        )

        result = cab_agent.invoke(state)
        print(f"Response: {result.get('last_bot_response', 'No response')}")
        print(f"Filtered drivers: {len(result.get('filtered_drivers', []))}\n")

    print("✅ Testing complete!")


if __name__ == "__main__":
    test_agent()
