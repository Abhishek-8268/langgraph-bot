import os
from slack_sdk import WebClient

# Check your bot token
token = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=token)

try:
    # Test the token
    response = client.auth_test()

    print("✅ Token Information:")
    print(f"   Bot ID: {response['user_id']}")
    print(f"   Bot Name: {response['user']}")
    print(f"   Team: {response['team']}")
    print(f"   Token Type: {'Bot Token' if token.startswith('xoxb-') else 'User Token (WRONG!)'}")

    if not token.startswith('xoxb-'):
        print("❌ ERROR: You're using a user token, not a bot token!")
        print("   Bot tokens start with 'xoxb-'")
        print("   User tokens start with 'xoxp-'")

except Exception as e:
    print(f"❌ Token verification failed: {e}")
