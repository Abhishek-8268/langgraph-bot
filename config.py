# API Endpoints
# BASE_URL = "https://us-central1-cabswale-ai.cloudfunctions.net"
# GET_DRIVERS_URL = f"{BASE_URL}/typesense-getPartnersByLocation"
# GET_PARTNER_DATA_URL = f"{BASE_URL}/partners-getPartnerData"



# config.py

# --- API Configuration ---

# The main domain of your API. This should end with the base path if applicable,
# but NOT the final endpoint name.
BASE_URL = "https://us-central1-cabswale-ai.cloudfunctions.net"

# CORRECT: This should ONLY be the name or path of the specific function/endpoint.
# It should NOT repeat the base URL.
GET_DRIVERS_URL = "typesense-getPartnersByLocation"

# CORRECT: This should also be just the endpoint name/path.
# Please verify the correct name for this endpoint from your API documentation.
GET_PARTNER_DATA_URL = "partners-getPartnerData" # Example: Please verify this is the correct name

