import time
import requests
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
import config
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- START: NEW TOOL ---
@tool
def show_more_drivers() -> str:
    """
    Use this tool when the user asks to see more drivers from the list that has already been fetched.
    This action does not require any arguments. It will display the next available set of drivers.
    """
    # This tool is a signal for the agent's logic. It doesn't perform an action itself,
    # but its invocation will be handled in the tool_executor_node to update the display.
    return "Showing next set of drivers."
# --- END: NEW TOOL ---

@tool
def remove_filters_from_search(keys_to_remove: List[str]) -> str:
    """
    Removes one or more specified filters from the current search criteria.
    Use this when the user wants to broaden their search again.
    For example, to remove the language and age filters, the argument should be ["language", "age"].
    To remove all filters, the argument should be ["all"].
    """
    return f"Will attempt to remove the following filters: {', '.join(keys_to_remove)}"

@tool
def get_drivers_for_city(city: str, page: int = 1, limit: int = 50) -> List[Dict]:
    """
    Get a batch of up to 50 drivers for a specific city with full details.
    
    Args:
        city: The city name to search for drivers.
        page: Page number for pagination.
        limit: Number of drivers per page.
    
    Returns:
        List of driver dictionaries with complete information.
    """
    try:
        premium_url = f"{config.BASE_URL}/{config.GET_DRIVERS_URL}"
        premium_data = {
            "city": city,
            "page": page,
            "limit": limit,
            "timestamp": int(time.time())
        }
        
        response = requests.post(url=premium_url, data=premium_data, timeout=30) # Increased timeout for larger payload
        
        if response.status_code != 200:
            return []
        
        premium_result = response.json()
        if not premium_result.get("success", False):
            return []
        
        premium_drivers = premium_result.get("data", [])
        if not premium_drivers:
            return []
        
        drivers_with_details = []
        
        def fetch_driver_details(premium_driver):
            try:
                driver_id = premium_driver.get("id")
                if not driver_id: return None
                
                details_url = f"{config.BASE_URL}/{config.GET_PARTNER_DATA_URL}"
                details_data = {"partnerId": driver_id, "timestamp": int(time.time())}
                details_response = requests.post(url=details_url, data=details_data, timeout=10)
                
                if details_response.status_code == 200:
                    details_result = details_response.json()
                    if details_result.get("success", False):
                        return process_driver_data(premium_driver, details_result.get("data", {}), driver_id)
                return None
            except requests.exceptions.RequestException:
                # Silently fail on network errors for individual drivers
                return None

        with ThreadPoolExecutor(max_workers=15) as executor:
            future_to_driver = {executor.submit(fetch_driver_details, driver): driver for driver in premium_drivers}
            for future in as_completed(future_to_driver, timeout=45):
                try:
                    result = future.result()
                    if result:
                        drivers_with_details.append(result)
                except Exception:
                    # Silently fail on timeout/errors for individual drivers
                    continue
        
        return drivers_with_details
        
    except requests.exceptions.RequestException:
        # Silently fail on primary API call network errors
        return []

def process_driver_data(premium_driver: Dict, details: Dict, driver_id: str) -> Dict:
    """Quickly process and combine driver data from two API sources."""
    profile_image = None
    photos = premium_driver.get("photos", [])
    if photos and isinstance(photos, list) and len(photos) > 0 and photos[0].get("full", {}).get("url"):
        profile_image = photos[0]["full"]["url"]
    
    vehicles = []
    for vehicle in premium_driver.get("verifiedVehicles", []):
        image_url = None
        try:
            if vehicle.get("images"):
                first_image_obj = vehicle["images"][0]
                image_url = first_image_obj.get("full", {}).get("url")
        except (IndexError, AttributeError, TypeError):
            image_url = None

        vehicle_info = {
            "model": vehicle.get("model", "Unknown"),
            "type": vehicle.get("vehicleType") or vehicle.get("vehicle_type") or "Unknown",
            "reg_no": vehicle.get("reg_no", ""),
            "per_km_cost": float(vehicle.get("perKmCost", 0)) if vehicle.get("perKmCost") else 0.0,
            "is_commercial": vehicle.get("is_commercial", False),
            "image_url": image_url
        }
        vehicles.append(vehicle_info)
    
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
    """Filter a list of drivers based on various criteria."""
    if not filters or not drivers:
        return drivers
    
    filtered_list = list(drivers)
    
    for key, value in filters.items():
        if not filtered_list: break
            
        if key == "age" and isinstance(value, dict):
            op = value.get("operator", ">=")
            val = value.get("value")
            if val is not None:
                new_list = []
                for d in filtered_list:
                    age = d.get("age")
                    if age is None: continue
                    if op == ">" and age > val: new_list.append(d)
                    elif op == "<" and age < val: new_list.append(d)
                    elif op == ">=" and age >= val: new_list.append(d)
                    elif op == "<=" and age <= val: new_list.append(d)
                    elif op == "==" and age == val: new_list.append(d)
                filtered_list = new_list
                
        elif key == "language" and isinstance(value, str):
            lang = value.lower()
            filtered_list = [d for d in filtered_list if any(l.lower() == lang for l in d.get("languages", []))]
            
        elif key == "vehicle_type" and isinstance(value, str):
            v_type = value.lower()
            filtered_list = [d for d in filtered_list if any(v.get("type", "").lower() == v_type for v in d.get("vehicles", []))]
            
        elif key == "is_married" and isinstance(value, bool):
            filtered_list = [d for d in filtered_list if d.get("is_married") == value]
            
        elif key == "is_pet_allowed" and isinstance(value, bool):
            filtered_list = [d for d in filtered_list if d.get("is_pet_allowed") == value]
            
    return filtered_list

@tool
def get_driver_details(driver_id: str) -> Optional[Dict]:
    """Get detailed information for a specific driver by their ID."""
    try:
        details_url = f"{config.BASE_URL}/{config.GET_PARTNER_DATA_URL}"
        details_data = {"partnerId": driver_id, "timestamp": int(time.time())}
        response = requests.post(url=details_url, data=details_data, timeout=30)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success", False):
                return result.get("data", {})
        return None
    except requests.exceptions.RequestException:
        return None
