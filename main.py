import requests
import json

# 🔑 Put your long-lived user token here
LONG_LIVED_USER_TOKEN = "PASTE_LONG_LIVED_USER_TOKEN_HERE"
PAGE_ID = "110575327401854"  # Last Move Gaming

def log(title, data):
    print(f"=== {title} ===")
    print("Response:", json.dumps(data, indent=2))
    if "error" in data:
        print("⚠️ Error:", data["error"]["message"])
    print()

# Step 1: Get Page Access Token
url_accounts = f"https://graph.facebook.com/v20.0/me/accounts?access_token={LONG_LIVED_USER_TOKEN}"
resp = requests.get(url_accounts).json()
log("Fetching Page Access Token", resp)

if "data" not in resp or len(resp["data"]) == 0:
    print("❌ No pages found. Check that this user token has pages_show_list permission.")
    exit()

# Extract Page Token
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

# Step 2: Test Live Video Endpoints
endpoints = {
    "Test /live_videos": f"https://graph.facebook.com/v20.0/{PAGE_ID}/live_videos?access_token={PAGE_ACCESS_TOKEN}",
    "Test /videos?type=live": f"https://graph.facebook.com/v20.0/{PAGE_ID}/videos?type=live&access_token={PAGE_ACCESS_TOKEN}",
    "Test /videos": f"https://graph.facebook.com/v20.0/{PAGE_ID}/videos?access_token={PAGE_ACCESS_TOKEN}"
}

for title, url in endpoints.items():
    resp = requests.get(url).json()
    log(title, resp)
