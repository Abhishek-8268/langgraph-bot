#!/usr/bin/env python3
"""
Test performance improvements for the optimized driver tools
"""

import time
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_driver_fetch_performance():
    """Test the performance of the optimized driver fetching"""
    print("⚡ Testing Driver Fetch Performance")
    print("=" * 50)
    
    try:
        from langgraph_agent.tools.drivers_tools import get_drivers_for_city
        
        print("🧪 Testing optimized get_drivers_for_city...")
        
        start_time = time.time()
        
        # Test with Jaipur (should return multiple drivers)
        drivers = get_drivers_for_city.invoke({
            "city": "jaipur",
            "page": 1,
            "limit": 8  # Test with 8 drivers
        })
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"\n📊 PERFORMANCE RESULTS:")
        print(f"   ⏱️  Total time: {elapsed:.2f} seconds")
        print(f"   👥 Drivers fetched: {len(drivers)}")
        print(f"   ⚡ Time per driver: {elapsed/len(drivers):.2f} seconds" if drivers else "   ❌ No drivers")
        
        if elapsed < 30:
            print(f"   ✅ GOOD: Under 30 seconds")
        elif elapsed < 60:
            print(f"   ⚠️  OK: Under 1 minute but could be better")
        else:
            print(f"   ❌ SLOW: Over 1 minute - needs optimization")
        
        # Test sample driver data quality
        if drivers:
            sample_driver = drivers[0]
            print(f"\n🔍 Sample driver data:")
            print(f"   Name: {sample_driver.get('name')}")
            print(f"   Age: {sample_driver.get('age')}")
            print(f"   Languages: {sample_driver.get('languages')}")
            print(f"   Vehicles: {len(sample_driver.get('vehicles', []))}")
            print(f"   Routes: {len(sample_driver.get('routes', []))}")
        
        return elapsed < 30  # Consider it good if under 30 seconds
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_concurrent_requests():
    """Test how the system handles concurrent requests"""
    print("\n🚀 Testing Concurrent Request Handling")
    print("=" * 40)
    
    try:
        from langgraph_agent.tools.drivers_tools import get_drivers_for_city
        from concurrent.futures import ThreadPoolExecutor
        import threading
        
        def fetch_for_city(city):
            start = time.time()
            drivers = get_drivers_for_city.invoke({"city": city, "limit": 3})
            elapsed = time.time() - start
            return city, len(drivers), elapsed
        
        cities = ["jaipur", "delhi", "mumbai"]
        
        print(f"📡 Testing {len(cities)} concurrent requests...")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(fetch_for_city, cities))
        
        total_time = time.time() - start_time
        
        print(f"\n📊 CONCURRENT TEST RESULTS:")
        print(f"   ⏱️  Total time for {len(cities)} cities: {total_time:.2f} seconds")
        
        for city, driver_count, city_time in results:
            print(f"   🏙️  {city}: {driver_count} drivers in {city_time:.2f}s")
        
        avg_time = total_time / len(cities)
        print(f"   📈 Average time per city: {avg_time:.2f} seconds")
        
        if total_time < 45:
            print(f"   ✅ EXCELLENT: Concurrent requests handled well")
            return True
        else:
            print(f"   ⚠️  Concurrent requests could be faster")
            return False
            
    except Exception as e:
        print(f"❌ Concurrent test failed: {e}")
        return False

def test_slack_bot_performance():
    """Test the Slack bot processing speed"""
    print("\n💬 Testing Slack Bot Performance")
    print("=" * 35)
    
    try:
        # Import from your optimized slack bot
        from slack_bot import process_message
        
        test_messages = [
            "i want drivers from jaipur",
            "show me hindi speaking drivers", 
            "drivers under 30 years old"
        ]
        
        for i, message in enumerate(test_messages, 1):
            print(f"\n{i}. Testing: '{message}'")
            start = time.time()
            
            response = process_message(f"test_user_{i}", message)
            
            elapsed = time.time() - start
            print(f"   ⏱️  Response time: {elapsed:.2f} seconds")
            print(f"   📝 Response length: {len(response)} characters")
            
            if elapsed < 30:
                print(f"   ✅ GOOD")
            elif elapsed < 60:
                print(f"   ⚠️  OK")
            else:
                print(f"   ❌ SLOW")
        
        return True
        
    except Exception as e:
        print(f"❌ Slack bot test failed: {e}")
        return False

def main():
    """Run all performance tests"""
    print("🚀 PERFORMANCE TESTING SUITE")
    print("=" * 60)
    
    # Test 1: Basic driver fetch performance
    perf_ok = test_driver_fetch_performance()
    
    # Test 2: Concurrent requests
    concurrent_ok = test_concurrent_requests()
    
    # Test 3: Slack bot performance  
    slack_ok = test_slack_bot_performance()
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 PERFORMANCE SUMMARY")
    print("=" * 60)
    
    print(f"Driver fetch performance: {'✅ PASS' if perf_ok else '❌ NEEDS WORK'}")
    print(f"Concurrent handling: {'✅ PASS' if concurrent_ok else '❌ NEEDS WORK'}")
    print(f"Slack bot speed: {'✅ PASS' if slack_ok else '❌ NEEDS WORK'}")
    
    if all([perf_ok, concurrent_ok, slack_ok]):
        print("\n🎉 ALL PERFORMANCE TESTS PASSED!")
        print("Your Slack bot should now respond much faster!")
    else:
        print("\n⚠️ Some performance issues remain")
        print("Consider further optimizations")
    
    print("\n💡 Tips for better performance:")
    print("• Use smaller limit values (5-8 drivers max)")
    print("• Consider caching frequent requests")
    print("• Monitor API response times")

if __name__ == "__main__":
    main()