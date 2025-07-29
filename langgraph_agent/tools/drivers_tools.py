import time
import requests
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool

# Import config
import config

from typing import List

@tool
def remove_filters_from_search(keys_to_remove: List[str]) -> str:
    """
    Removes one or more specified filters from the current search criteria.
    Use this when the user wants to broaden their search again.
    For example, to remove the language and age filters, the argument should be ["language", "age"].
    To remove all filters, the argument should be ["all"].
    """
    # This tool doesn't need to do anything itself. Its purpose is to be called by the agent.
    # The actual state modification will happen in the tool_executor_node.
    return f"Will attempt to remove the following filters: {', '.join(keys_to_remove)}"

@tool
def get_drivers_for_city(city: str, page: int = 1, limit: int = 10) -> List[Dict]:
    """
    Get drivers for a specific city with full details - BATCH OPTIMIZED VERSION.
    
    Args:
        city: The city name to search for drivers
        page: Page number for pagination (default: 1)
        limit: Number of drivers per page (default: 10)
    
    Returns:
        List of driver dictionaries with complete information
    """
    print(f"🔍 Getting drivers for {city} (page {page}, limit {limit})")
    
    try:
        # Step 1: Get premium drivers with timeout
        premium_url = f"{config.BASE_URL}/{config.GET_DRIVERS_URL}"
        premium_data = {
            "city": city,
            "page": page,
            "limit": limit,
            "timestamp": int(time.time())
        }
        
        print(f"📡 Calling premium drivers API...")
        response = requests.post(url=premium_url, data=premium_data, timeout=15)
        
        if response.status_code != 200:
            print(f"❌ Premium drivers API error: {response.status_code}")
            return []
        
        premium_result = response.json()
        if not premium_result.get("success", False):
            print(f"❌ Premium drivers API returned success=False")
            return []
        
        premium_drivers = premium_result.get("data", [])
        print(f"📋 Found {len(premium_drivers)} premium drivers on page {page}")
        
        if not premium_drivers:
            print(f"📄 No drivers found on page {page}")
            return []
        
        # Step 2: Get detailed info for ALL drivers in parallel - OPTIMIZED
        drivers_with_details = []
        
        def fetch_driver_details(premium_driver):
            """Fetch driver details with timeout and error handling"""
            try:
                driver_id = premium_driver.get("id")
                if not driver_id:
                    return None
                
                details_url = f"{config.BASE_URL}/{config.GET_PARTNER_DATA_URL}"
                details_data = {
                    "partnerId": driver_id,
                    "timestamp": int(time.time())
                }
                
                # Faster timeout for individual requests
                details_response = requests.post(url=details_url, data=details_data, timeout=8)
                
                if details_response.status_code == 200:
                    details_result = details_response.json()
                    if details_result.get("success", False):
                        details = details_result.get("data", {})
                        
                        # Process driver data quickly
                        return process_driver_data(premium_driver, details, driver_id)
                    else:
                        print(f"⚠️ Details API failed for {driver_id}")
                        return None
                else:
                    print(f"⚠️ HTTP {details_response.status_code} for {driver_id}")
                    return None
                        
            except Exception as e:
                print(f"⚠️ Error fetching {premium_driver.get('id', 'unknown')}: {e}")
                return None
        
        # Use ThreadPoolExecutor with higher concurrency and timeout
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        print(f"🚀 Fetching details for {len(premium_drivers)} drivers in parallel...")
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=12) as executor:  # Increased workers for 10 drivers
            # Submit all tasks
            future_to_driver = {
                executor.submit(fetch_driver_details, driver): driver 
                for driver in premium_drivers
            }
            
            # Collect results with timeout
            for future in as_completed(future_to_driver, timeout=25):  # 25 sec max total
                try:
                    result = future.result(timeout=3)  # 3 sec per individual request
                    if result:
                        drivers_with_details.append(result)
                except Exception as e:
                    driver = future_to_driver[future]
                    print(f"⚠️ Timeout/error for {driver.get('id', 'unknown')}: {e}")
        
        elapsed = time.time() - start_time
        print(f"✅ Processed {len(drivers_with_details)} drivers in {elapsed:.2f} seconds")
        return drivers_with_details
        
    except Exception as e:
        print(f"❌ Error in get_drivers_for_city: {e}")
        return []


@tool
def get_drivers_with_pagination(city: str, max_pages: int = 5, filters: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Get drivers with smart pagination and filtering.
    Fetches up to max_pages (50 drivers max) until enough filtered drivers are found.
    
    Args:
        city: The city name to search for drivers
        max_pages: Maximum pages to fetch (default: 5, max 50 drivers)
        filters: Optional filters to apply during fetching
    
    Returns:
        Dictionary with drivers, pagination info, and filtering results
    """
    print(f"🔍 Smart driver search for {city} (max {max_pages} pages, filters: {filters})")
    
    all_drivers = []
    filtered_drivers = []
    current_page = 1
    pages_fetched = 0
    
    # Continue fetching until we have enough drivers or hit max pages
    while current_page <= max_pages and pages_fetched < max_pages:
        print(f"📄 Fetching page {current_page}...")
        
        # Fetch drivers for current page
        page_drivers = get_drivers_for_city.invoke({
            "city": city,
            "page": current_page,
            "limit": 10
        })
        
        if not page_drivers:
            print(f"📄 No more drivers on page {current_page}, stopping")
            break
            
        all_drivers.extend(page_drivers)
        pages_fetched += 1
        print(f"📊 Total drivers so far: {len(all_drivers)}")
        
        # Apply filters if provided
        if filters:
            # Filter all drivers we have so far
            current_filtered = filter_drivers.invoke({
                "drivers": all_drivers,
                "filters": filters
            })
            
            print(f"🔍 After filtering: {len(current_filtered)} drivers match criteria")
            
            # If we have enough filtered drivers (5+), we can stop
            if len(current_filtered) >= 5:
                filtered_drivers = current_filtered
                print(f"✅ Found enough filtered drivers ({len(filtered_drivers)}), stopping search")
                break
                
        current_page += 1
    
    # Final filtering if no filters were applied during pagination
    if not filters:
        filtered_drivers = all_drivers
    elif not filtered_drivers:  # If we didn't find enough during pagination
        filtered_drivers = filter_drivers.invoke({
            "drivers": all_drivers,
            "filters": filters
        })
    
    result = {
        "all_drivers": all_drivers,
        "filtered_drivers": filtered_drivers,
        "total_drivers": len(all_drivers),
        "filtered_count": len(filtered_drivers),
        "pages_searched": pages_fetched,
        "max_pages_reached": pages_fetched >= max_pages,
        "filters_applied": filters or {},
        "city": city
    }
    
    print(f"🎯 Final result: {len(all_drivers)} total, {len(filtered_drivers)} filtered from {pages_fetched} pages")
    return result

# In drivers_tools.py

def process_driver_data(premium_driver, details, driver_id):
    """Quickly process driver data without complex operations"""
    # Get profile image quickly
    profile_image = None
    photos = premium_driver.get("photos", [])
    if photos and photos[0].get("full", {}).get("url"):
        profile_image = photos[0]["full"]["url"]
    
    # Process vehicles quickly
    vehicles = []
    for vehicle in premium_driver.get("verifiedVehicles", []):
        # --- START: UPDATED IMAGE EXTRACTION LOGIC ---
        image_url = None
        # Safely access the nested image URL according to the schema structure
        try:
            # Check if the 'images' list exists and is not empty
            if vehicle.get("images"):
                # Get the first image object from the list
                first_image_obj = vehicle["images"][0]
                # Access the URL through the nested 'full' object
                image_url = first_image_obj.get("full", {}).get("url")
        except (IndexError, AttributeError, TypeError) as e:
            # If any part of the structure is missing, log it and continue
            print(f"Could not process vehicle image for driver {driver_id}: {e}")
            image_url = None
        # --- END: UPDATED IMAGE EXTRACTION LOGIC ---

        vehicle_info = {
            "model": vehicle.get("model", "Unknown"),
            "type": vehicle.get("vehicleType", "Unknown"),
            "reg_no": vehicle.get("reg_no", ""),
            "per_km_cost": float(vehicle.get("perKmCost", 0)) if vehicle.get("perKmCost") else 0.0,
            "is_commercial": vehicle.get("is_commercial", False),
            "image_url": image_url # This now correctly holds the nested URL
        }
        vehicles.append(vehicle_info)
    
    # Create combined driver data - minimal processing
    return {
        "id": driver_id,
        "name": premium_driver.get("name", "Unknown"),
        "city": premium_driver.get("city", ""),
        "phone": premium_driver.get("phoneNo", ""),
        "username": premium_driver.get("userName", ""),
        "profile_image": profile_image,
        "age": details.get("age"),
        "experience": details.get("experience", 0),
        "bio": details.get("driverBio", ""),
        "connections": details.get("connections", 0),
        "is_pet_allowed": details.get("isPetAllowed", False),
        "is_married": details.get("married", False),
        "languages": details.get("languages", []),
        "trip_types": details.get("tripTypes", []),
        "routes": [{"from": r.get("from", ""), "to": r.get("to", "")} for r in details.get("routes", [])],
        "verified_languages": [{"name": l.get("name", ""), "verified": l.get("verified", False)} for l in details.get("verifiedLanguages", [])],
        "vehicles": vehicles
    }


@tool  
def filter_drivers(drivers: List[Dict], filters: Dict[str, Any]) -> List[Dict]:
    """
    Filter drivers based on various criteria.
    
    Args:
        drivers: List of driver dictionaries to filter
        filters: Dictionary of filter criteria
    
    Returns:
        Filtered list of drivers
    """
    print(f"🔍 Filtering {len(drivers)} drivers with filters: {filters}")
    
    if not filters or not drivers:
        return drivers
    
    filtered_drivers = list(drivers)
    
    for filter_key, filter_value in filters.items():
        if not filtered_drivers:
            break
            
        if filter_key == "age" and isinstance(filter_value, dict):
            operator = filter_value.get("operator", ">=")
            value = filter_value.get("value")
            if value is not None:
                new_list = []
                for driver in filtered_drivers:
                    driver_age = driver.get("age")
                    if driver_age is None:
                        continue
                    if operator == ">" and driver_age > value:
                        new_list.append(driver)
                    elif operator == "<" and driver_age < value:
                        new_list.append(driver)
                    elif operator == ">=" and driver_age >= value:
                        new_list.append(driver)
                    elif operator == "<=" and driver_age <= value:
                        new_list.append(driver)
                    elif operator == "==" and driver_age == value:
                        new_list.append(driver)
                filtered_drivers = new_list
                
        elif filter_key == "experience" and isinstance(filter_value, dict):
            operator = filter_value.get("operator", ">=")
            value = filter_value.get("value")
            if value is not None:
                new_list = []
                for driver in filtered_drivers:
                    driver_exp = driver.get("experience", 0)
                    if operator == ">" and driver_exp > value:
                        new_list.append(driver)
                    elif operator == "<" and driver_exp < value:
                        new_list.append(driver)
                    elif operator == ">=" and driver_exp >= value:
                        new_list.append(driver)
                    elif operator == "<=" and driver_exp <= value:
                        new_list.append(driver)
                    elif operator == "==" and driver_exp == value:
                        new_list.append(driver)
                filtered_drivers = new_list
                
        elif filter_key == "language" and isinstance(filter_value, str):
            target_lang = filter_value.lower()
            filtered_drivers = [
                driver for driver in filtered_drivers
                if any(lang.lower() == target_lang for lang in driver.get("languages", []))
            ]
            
        elif filter_key == "vehicle_type" and isinstance(filter_value, str):
            target_type = filter_value.lower()
            filtered_drivers = [
                driver for driver in filtered_drivers
                if any(vehicle.get("type", "").lower() == target_type for vehicle in driver.get("vehicles", []))
            ]
            
        elif filter_key == "is_married" and isinstance(filter_value, bool):
            filtered_drivers = [
                driver for driver in filtered_drivers
                if driver.get("is_married") == filter_value
            ]
            
        elif filter_key == "is_pet_allowed" and isinstance(filter_value, bool):
            filtered_drivers = [
                driver for driver in filtered_drivers
                if driver.get("is_pet_allowed") == filter_value
            ]
            
        elif filter_key == "min_connections" and isinstance(filter_value, (int, float)):
            filtered_drivers = [
                driver for driver in filtered_drivers
                if driver.get("connections", 0) >= filter_value
            ]
            
        elif filter_key == "min_experience" and isinstance(filter_value, (int, float)):
            filtered_drivers = [
                driver for driver in filtered_drivers
                if driver.get("experience", 0) >= filter_value
            ]
            
        elif filter_key == "max_cost_per_km" and isinstance(filter_value, (int, float)):
            new_list = []
            for driver in filtered_drivers:
                has_affordable_vehicle = False
                for vehicle in driver.get("vehicles", []):
                    if vehicle.get("per_km_cost", 0) <= filter_value:
                        has_affordable_vehicle = True
                        break
                if has_affordable_vehicle:
                    new_list.append(driver)
            filtered_drivers = new_list
    
    print(f"✅ Filtering complete: {len(filtered_drivers)} drivers remaining")
    return filtered_drivers


@tool
def get_driver_details(driver_id: str) -> Optional[Dict]:
    """
    Get detailed information for a specific driver.
    
    Args:
        driver_id: The unique ID of the driver
    
    Returns:
        Dictionary with detailed driver information or None if not found
    """
    print(f"🔍 Getting detailed info for driver {driver_id}")
    
    try:
        details_url = f"{config.BASE_URL}/{config.GET_PARTNER_DATA_URL}"
        details_data = {
            "partnerId": driver_id,
            "timestamp": int(time.time())
        }
        
        response = requests.post(url=details_url, data=details_data, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Driver details API error: {response.status_code}")
            return None
        
        result = response.json()
        if not result.get("success", False):
            print(f"❌ Driver details API returned success=False")
            return None
        
        details = result.get("data", {})
        
        # Format the detailed information
        driver_details = {
            "id": driver_id,
            "name": details.get("name", "Unknown"),
            "age": details.get("age"),
            "experience": details.get("experience", 0),
            "bio": details.get("driverBio", ""),
            "city": details.get("city", ""),
            "phone": details.get("phoneNo", ""),
            "username": details.get("userName", ""),
            "connections": details.get("connections", 0),
            "is_pet_allowed": details.get("isPetAllowed", False),
            "is_married": details.get("married", False),
            "languages": details.get("languages", []),
            "verified_languages": details.get("verifiedLanguages", []),
            "trip_types": details.get("tripTypes", []),
            "routes": details.get("routes", []),
            "training_content": details.get("trainingContent", []),
            "vehicle_ownership": details.get("vehicleOwnershipDetails", []),
            "verified_vehicles": details.get("verifiedVehicles", []),
            "profile_pic": details.get("profilePic", ""),
            "onboarded_at": details.get("onboardedAt", ""),
            "created_at": details.get("createdAt", ""),
            "membership_active": details.get("membershipActive", False),
            "aadhar_verified": details.get("aadharCardVerified", False),
            "license_verified": details.get("drivingLicenseVerified", False),
            "smoking_allowed": details.get("smokingAllowedInside", False),
            "available_for_events": details.get("availableForDrivingInEventWedding", False),
            "available_for_personal_car": details.get("availableForCustomersPersonalCar", False),
            "allows_handicapped": details.get("allowHandicappedPersons", False)
        }
        
        print(f"✅ Successfully got detailed info for {driver_details['name']}")
        return driver_details
        
    except Exception as e:
        print(f"❌ Error getting driver details for {driver_id}: {e}")
        return None


# Test function
def test_working_tools():
    """Test the working tools with real API calls"""
    print("🧪 Testing working tools...")
    
    try:
        # Test 1: Get drivers
        print("\n1️⃣ Testing get_drivers_for_city...")
        drivers = get_drivers_for_city.invoke({"city": "jaipur", "page": 1, "limit": 3})
        print(f"Got {len(drivers)} drivers")
        
        if drivers:
            print(f"Sample driver: {drivers[0]['name']} - {drivers[0]['age']} years old")
            print(f"Languages: {drivers[0]['languages']}")
            print(f"Vehicle: {drivers[0]['vehicles'][0]['model'] if drivers[0]['vehicles'] else 'No vehicle'}")
            
            # Test 2: Filter drivers
            print("\n2️⃣ Testing filter_drivers...")
            test_filters = {"language": "Hindi", "experience": {"operator": ">=", "value": 5}}
            filtered = filter_drivers.invoke({"drivers": drivers, "filters": test_filters})
            print(f"Filtered from {len(drivers)} to {len(filtered)} drivers")
            
            # Test 3: Get driver details
            if drivers:
                print("\n3️⃣ Testing get_driver_details...")
                first_driver_id = drivers[0]["id"]
                details = get_driver_details.invoke({"driver_id": first_driver_id})
                if details:
                    print(f"Got detailed info for: {details['name']}")
                    print(f"Bio: {details['bio'][:100]}...")
                else:
                    print("❌ Failed to get driver details")
        else:
            print("❌ No drivers returned")
            
    except Exception as e:
        print(f"❌ Error in test: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n✅ Tool testing complete!")


if __name__ == "__main__":
    test_working_tools()