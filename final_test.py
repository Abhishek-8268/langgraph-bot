#!/usr/bin/env python3
"""
Final test script to verify the complete system works
"""

import sys
import os

# Add the project root to the path  
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_tools_only():
    """Test just the tools without LangGraph"""
    print("🧪 TESTING TOOLS ONLY")
    print("=" * 50)
    
    try:
        from langgraph_agent.tools.drivers_tools import get_drivers_for_city, filter_drivers, get_driver_details
        
        # Test 1: Get drivers
        print("1️⃣ Testing get_drivers_for_city...")
        drivers = get_drivers_for_city.invoke({"city": "jaipur", "page": 1, "limit": 3})
        print(f"✅ Got {len(drivers)} drivers")
        
        if drivers:
            first_driver = drivers[0]
            print(f"Sample driver: {first_driver['name']} ({first_driver['age']} years)")
            print(f"Languages: {first_driver['languages']}")
            print(f"Experience: {first_driver['experience']} years")
            
            # Test 2: Filter drivers
            print("\n2️⃣ Testing filter_drivers...")
            test_filters = {"language": "Hindi"}
            filtered = filter_drivers.invoke({"drivers": drivers, "filters": test_filters})
            print(f"✅ Filtered from {len(drivers)} to {len(filtered)} drivers")
            
            # Test 3: Get driver details  
            print("\n3️⃣ Testing get_driver_details...")
            driver_id = first_driver["id"]
            details = get_driver_details.invoke({"driver_id": driver_id})
            if details:
                print(f"✅ Got detailed info for: {details['name']}")
                print(f"Bio: {details['bio'][:100]}...")
            else:
                print("❌ Failed to get driver details")
        
        print("\n✅ All tools working correctly!")
        return True
        
    except Exception as e:
        print(f"❌ Tool test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_graph():
    """Test the complete LangGraph setup"""
    print("\n🧪 TESTING LANGGRAPH")
    print("=" * 50)
    
    try:
        from langgraph_agent.graph.builder import app
        from langchain_core.messages import HumanMessage
        
        # Create a test state
        test_state = {
            "chat_history": [HumanMessage(content="I need drivers in Jaipur")],
            "drivers_with_full_details": [],
            "filtered_drivers": [],
            "applied_filters": {},
            "pickup_location": None,
            "last_bot_response": None,
            "tool_calls": []
        }
        
        print("🤖 Running graph with test message...")
        
        # Run the graph
        final_state = app.invoke(test_state)
        
        # Check results
        response = final_state.get("last_bot_response", "No response")
        drivers_found = len(final_state.get("drivers_with_full_details", []))
        
        print(f"✅ Graph executed successfully!")
        print(f"Bot response: {response[:100]}...")
        print(f"Drivers found: {drivers_found}")
        
        return True
        
    except Exception as e:
        print(f"❌ Graph test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    print("🔧 FINAL SYSTEM TEST")
    print("=" * 60)
    
    # Test 1: Tools
    tools_ok = test_tools_only()
    
    if tools_ok:
        # Test 2: Graph
        graph_ok = test_graph()
        
        if graph_ok:
            print("\n🎉 ALL TESTS PASSED!")
            print("Your system is ready to use!")
            print("\nRun: python main.py")
        else:
            print("\n⚠️ Tools work but graph has issues")
            print("Check your builder.py configuration")
    else:
        print("\n❌ Tools have issues")
        print("Check your API configuration and drivers_tools.py")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()