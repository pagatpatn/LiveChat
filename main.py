import requests
import json

# 🔑 Replace with your own details
APP_ID = "YOUR_APP_ID"
APP_SECRET = "YOUR_APP_SECRET"
SHORT_LIVED_TOKEN = "PASTE_YOUR_SHORT_LIVED_USER_TOKEN"
PAGE_ID = "110575327401854"  # Last Move Gaming

def log(title, data):
    print(f"=== {title} ===")
    print(json.dumps(data, indent=2))
    if "error" in data:
        print("⚠️ Error:", data["error"]["message"])
    print()

# Step 1: Exchange short-lived for long-lived user token
url_long = (
    f"https://graph.facebook.com/v20.0/oauth/access_token"
    f"?grant_type=fb_exchange_token"
    f"&client_id={APP_ID}"
    f"&client_secret={APP_SECRET}"
    f"&fb_exchange_token={SHORT_LIVED_TOKEN}"
)
resp = requests.get(url_long).json()
log("Exchange for Long-Lived User Token", resp)

if "access_token" not in resp:
    print("❌ Could not get long-lived token")
    exit()

LONG_LIVED_TOKEN = resp["access_token"]

# Step 2: Get Page Access Token
url_accounts = f"https://graph.facebook.com/v20.0/me/accounts?access_token={LONG_LIVED_TOKEN}"
resp = requests.get(url_accounts).json()
log("Fetching Page Access Token", resp)

if "data" not in resp or len(resp["data"]) == 0:
    print("❌ No pages found. Check that this token has pages_show_list and related permissions.")
    exit()

# Extract correct page
page_info = None
for p in resp["data"]:
    if p["id"] == PAGE_ID:
        page_info = p
        break

if not page_info:
    print(f"❌ Page ID {PAGE_ID} not found in your account list")
    exit()

PAGE_ACCESS_TOKEN = page_info["access_token"]
print(f"✅ Got Page Token for {page_info['name']}")

# Step 3: Test Live Video Endpoints
endpoints = {
    "Test /live_videos": f"https://graph.facebook.com/v20.0/{PAGE_ID}/live_videos?access_token={PAGE_ACCESS_TOKEN}",
    "Test /videos?type=live": f"https://graph.facebook.com/v20.0/{PAGE_ID}/videos?type=live&access_token={PAGE_ACCESS_TOKEN}",
    "Test /videos": f"https://graph.facebook.com/v20.0/{PAGE_ID}/videos?access_token={PAGE_ACCESS_TOKEN}"
}

for title, url in endpoints.items():
    resp = requests.get(url).json()
    log(title, resp)
