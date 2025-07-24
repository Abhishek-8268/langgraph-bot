import time
import requests
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool

# Import config
import config

@tool
def get_drivers_for_city(city: str, page: int = 1, limit: int = 10) -> List[Dict]:
    """
    Get drivers for a specific city with full details.
    
    Args:
        city: The city name to search for drivers
        page: Page number for pagination (default: 1)
        limit: Number of drivers per page (default: 10)
    
    Returns:
        List of driver dictionaries with complete information
    """
    print(f"🔍 Getting drivers for {city} (page {page}, limit {limit})")
    
    try:
        # Step 1: Get premium drivers
        premium_url = f"{config.BASE_URL}/{config.GET_DRIVERS_URL}"
        premium_data = {
            "city": city,
            "page": page,
            "limit": limit,
            "timestamp": int(time.time())
        }
        
        print(f"📡 Calling premium drivers API: {premium_url}")
        response = requests.post(url=premium_url, data=premium_data, timeout=30)
        
        if response.status_code != 200:
            print(f"❌ Premium drivers API error: {response.status_code}")
            return []
        
        premium_result = response.json()
        if not premium_result.get("success", False):
            print(f"❌ Premium drivers API returned success=False")
            return []
        
        premium_drivers = premium_result.get("data", [])
        print(f"📋 Found {len(premium_drivers)} premium drivers")
        
        if not premium_drivers:
            return []
        
        # Step 2: Get detailed info for each driver
        drivers_with_details = []
        
        for premium_driver in premium_drivers:
            try:
                driver_id = premium_driver.get("id")
                if not driver_id:
                    continue
                
                print(f"🔍 Getting details for driver {driver_id}")
                
                # Get driver details
                details_url = f"{config.BASE_URL}/{config.GET_PARTNER_DATA_URL}"
                details_data = {
                    "partnerId": driver_id,
                    "timestamp": int(time.time())
                }
                
                details_response = requests.post(url=details_url, data=details_data, timeout=30)
                
                if details_response.status_code == 200:
                    details_result = details_response.json()
                    if details_result.get("success", False):
                        details = details_result.get("data", {})
                        
                        # Get profile image
                        profile_image = None
                        if premium_driver.get("photos") and len(premium_driver["photos"]) > 0:
                            photos = premium_driver["photos"][0]
                            if "full" in photos and "url" in photos["full"]:
                                profile_image = photos["full"]["url"]
                        
                        # Combine premium info with details
                        combined_driver = {
                            # Basic info from premium driver
                            "id": driver_id,
                            "name": premium_driver.get("name", "Unknown"),
                            "city": premium_driver.get("city", city),
                            "phone": premium_driver.get("phoneNo", ""),
                            "username": premium_driver.get("userName", ""),
                            "profile_image": profile_image,
                            
                            # Details from driver details API
                            "age": details.get("age"),
                            "experience": details.get("experience", 0),
                            "bio": details.get("driverBio", ""),
                            "connections": details.get("connections", 0),
                            "is_pet_allowed": details.get("isPetAllowed", False),
                            "is_married": details.get("married", False),
                            "languages": details.get("languages", []),
                            "trip_types": details.get("tripTypes", []),
                            "routes": [],
                            "verified_languages": [],
                            
                            # Vehicle info (simplified)
                            "vehicles": []
                        }
                        
                        # Add route information
                        for route in details.get("routes", []):
                            route_info = {
                                "from": route.get("from", ""),
                                "to": route.get("to", "")
                            }
                            combined_driver["routes"].append(route_info)
                        
                        # Add verified languages
                        for lang in details.get("verifiedLanguages", []):
                            lang_info = {
                                "name": lang.get("name", ""),
                                "verified": lang.get("verified", False)
                            }
                            combined_driver["verified_languages"].append(lang_info)
                        
                        # Add vehicle information from premium driver data
                        for vehicle in premium_driver.get("verifiedVehicles", []):
                            vehicle_info = {
                                "model": vehicle.get("model", "Unknown"),
                                "type": vehicle.get("vehicleType", "Unknown"),
                                "reg_no": vehicle.get("reg_no", ""),
                                "per_km_cost": float(vehicle.get("perKmCost", 0)) if vehicle.get("perKmCost") else 0.0,
                                "is_commercial": vehicle.get("is_commercial", False),
                                "images": []
                            }
                            
                            # Add vehicle images
                            for image in vehicle.get("images", []):
                                if "full" in image and "url" in image["full"]:
                                    image_info = {
                                        "type": image.get("type", "unknown"),
                                        "url": image["full"]["url"],
                                        "verified": image.get("verified", False)
                                    }
                                    vehicle_info["images"].append(image_info)
                            
                            combined_driver["vehicles"].append(vehicle_info)
                        
                        drivers_with_details.append(combined_driver)
                        print(f"✅ Successfully processed driver {combined_driver['name']}")
                        
                    else:
                        print(f"⚠️ Driver details API returned success=False for {driver_id}")
                else:
                    print(f"⚠️ Driver details API error {details_response.status_code} for {driver_id}")
                    
            except Exception as e:
                print(f"⚠️ Error processing driver {driver_id}: {e}")
                continue
        
        print(f"✅ Successfully processed {len(drivers_with_details)} drivers with full details")
        return drivers_with_details
        
    except Exception as e:
        print(f"❌ Error in get_drivers_for_city: {e}")
        return []


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