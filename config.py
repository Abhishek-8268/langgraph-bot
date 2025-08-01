# config.py
"""Simple configuration file"""

import os

# API Configuration
BASE_URL = "https://us-central1-cabswale-ai.cloudfunctions.net"
GET_DRIVERS_URL = f"{BASE_URL}/typesense-getPartnersByLocation"
GET_PARTNER_DATA_URL = f"{BASE_URL}/partners-getPartnerData"

# Environment
PORT = int(os.environ.get("PORT", 8000))
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
