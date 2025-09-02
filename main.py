import os
import requests
import json

# 🔑 Load from environment variables
USER_SHORT_TOKEN = os.getenv("SHORT_LIVED_TOKEN")
APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")
PAGE_ID = os.getenv("FB_PAGE_ID")

def exchange_for_long_lived(user_short_token, app_id, app_secret):
    """Exchange short-lived user token for a long-lived one"""
    url = "https://graph.facebook.com/v20.0/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": user_short_token,
    }
    res = requests.get(url, params=params).json()
    print("=== Long-Lived User Token Response ===")
    print(json.dumps(res, indent=2))
    return res.get("access_token")

def get_page_token(user_token, page_id):
    """Get Page access token from user token"""
    url = f"https://graph.facebook.com/v20.0/{page_id}"
    params = {"fields": "access_token", "access_token": user_token}
    res = requests.get(url, params=params).json()
    print("=== Page Token Response ===")
    print(json.dumps(res, indent=2))
    return res.get("access_token")

def get_live_video(page_id, page_token):
    """Fetch active live video for the page"""
    url = f"https://graph.facebook.com/v20.0/{page_id}/videos"
    params = {
        "fields": "id,description,live_status,created_time",
        "access_token": page_token,
        "limit": 10
    }
    res = requests.get(url, params=params).json()
    print("=== Videos Response ===")
    print(json.dumps(res, indent=2))

    if "data" not in res:
        print("⚠️ No videos found. Check token/permissions.")
        return None

    live_videos = [v for v in res["data"] if v.get("live_status") == "LIVE"]

    if not live_videos:
        print("❌ No active LIVE video found.")
        return None

    print("✅ Live video(s) found:")
    for v in live_videos:
        print(f"▶️ ID: {v['id']} | {v.get('description','(no desc)')}")

    return live_videos[0]["id"]

if __name__ == "__main__":
    if not USER_SHORT_TOKEN or not APP_ID or not APP_SECRET or not PAGE_ID:
        raise ValueError("❌ Missing required env variables")

    # Step 1: Exchange short → long
    long_token = exchange_for_long_lived(USER_SHORT_TOKEN, APP_ID, APP_SECRET)
    if not long_token:
        raise RuntimeError("❌ Failed to get long-lived token")

    # Step 2: Get page token
    page_token = get_page_token(long_token, PAGE_ID)
    if not page_token:
        raise RuntimeError("❌ Failed to get page token")

    # Step 3: Get live video
    live_video_id = get_live_video(PAGE_ID, page_token)
    if live_video_id:
        print(f"\n🎯 ACTIVE LIVE VIDEO ID = {live_video_id}")
    else:
        print("\n❌ No live stream currently active.")
