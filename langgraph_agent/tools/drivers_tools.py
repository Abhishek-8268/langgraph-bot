import time
import requests
from typing import List, Dict, Any, Optional
from langchain_core.tools import tool
import config
from concurrent.futures import ThreadPoolExecutor, as_completed

@tool
def show_more_drivers() -> str:
    """
    Use this tool when the user asks to see more drivers from the list that has already been fetched.
    This action does not require any arguments. It will display the next available set of drivers.
    """
    return "Showing next set of drivers."

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
def get_drivers_for_city(city: str, page: int = 1, limit: int = 25) -> List[Dict]:
    """
    Get a batch of up to 25 drivers for a specific city with full details.
    """
    try:
        premium_url = f"{config.BASE_URL}/{config.GET_DRIVERS_URL}"
        premium_data = { "city": city, "page": page, "limit": limit, "timestamp": int(time.time()) }
        response = requests.post(url=premium_url, data=premium_data, timeout=30)
        if response.status_code != 200: return []
        
        premium_result = response.json()
        if not premium_result.get("success", False): return []
        
        premium_drivers = premium_result.get("data", [])
        if not premium_drivers: return []
        
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
                return None

        with ThreadPoolExecutor(max_workers=15) as executor:
            future_to_driver = {executor.submit(fetch_driver_details, driver): driver for driver in premium_drivers}
            for future in as_completed(future_to_driver, timeout=45):
                try:
                    result = future.result()
                    if result:
                        drivers_with_details.append(result)
                except Exception:
                    continue
        
        return drivers_with_details
    except requests.exceptions.RequestException:
        return []

def process_driver_data(premium_driver: Dict, details: Dict, driver_id: str) -> Dict:
    """Quickly process and combine driver data, ensuring image URLs are correctly handled."""
    profile_image = None
    photos = premium_driver.get("photos", [])
    if photos and isinstance(photos, list):
        for photo in photos:
            # Ensure it's a valid firebase URL and not a government ID
            url = photo.get("full", {}).get("url", "")
            if "firebasestorage" in url and "government ID" not in photo.get("errorMessage", ""):
                profile_image = url
                break
    
    vehicles = []
    all_vehicle_images = []
    for vehicle in premium_driver.get("verifiedVehicles", []):
        vehicle_image_url = None
        try:
            if vehicle.get("images"):
                for img in vehicle.get("images", []):
                    img_url = img.get("full", {}).get("url", "")
                    if "firebasestorage" in img_url:
                        all_vehicle_images.append(img_url)
                if all_vehicle_images:
                    vehicle_image_url = all_vehicle_images[0]
        except (IndexError, AttributeError, TypeError):
            vehicle_image_url = None

        vehicle_info = {
            "model": vehicle.get("model", "Unknown"),
            "type": vehicle.get("vehicleType") or vehicle.get("vehicle_type") or "Unknown",
            "per_km_cost": float(vehicle.get("perKmCost", 0)) if vehicle.get("perKmCost") else 0.0,
        }
        vehicles.append(vehicle_info)
    
    return {
        "id": driver_id,
        "name": premium_driver.get("name", "Unknown"),
        "city": premium_driver.get("city", ""),
        "username": premium_driver.get("userName", ""),
        "profile_image": profile_image,
        "age": details.get("age"),
        "experience": details.get("experience", 0),
        "bio": details.get("driverBio", ""),
        "is_pet_allowed": details.get("isPetAllowed", False),
        "is_married": details.get("married", False),
        "languages": details.get("languages", []),
        "vehicles": vehicles,
        "all_vehicle_images": all_vehicle_images
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
                new_list = [d for d in filtered_list if d.get("age") is not None and (
                    (op == ">" and d["age"] > val) or
                    (op == "<" and d["age"] < val) or
                    (op == ">=" and d["age"] >= val) or
                    (op == "<=" and d["age"] <= val) or
                    (op == "==" and d["age"] == val)
                )]
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
        
        elif key == "experience" and isinstance(value, dict):
            op = value.get("operator", ">=")
            val = value.get("value")
            if val is not None:
                filtered_list = [d for d in filtered_list if d.get("experience", 0) >= val]

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
