import os
import time
import requests
import json

# 🔑 Environment variables (set in Railway)
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
PAGE_ID = os.getenv("FB_PAGE_ID")

def safe_request(url, params):
    """Wrapper for GET requests with error handling"""
    try:
        res = requests.get(url, params=params)
        data = res.json()
        if "error" in data:
            print(f"⚠️ API Error: {json.dumps(data, indent=2)}")
            return {}
        return data
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return {}

def get_live_video(page_id, page_token):
    """Check for currently active live video without live-video-api"""
    url = f"https://graph.facebook.com/v20.0/{page_id}/videos"
    params = {
        "fields": "id,description,live_status,created_time",
        "access_token": page_token,
        "limit": 5
    }
    res = safe_request(url, params)

    if "data" not in res:
        print("⚠️ No videos data found")
        return None

    for v in res["data"]:
        if v.get("live_status") == "LIVE":
            print(f"✅ Live video found: {v['id']} | {v.get('description','(no desc)')}")
            return v["id"]

    print("❌ No active LIVE video right now")
    return None

def get_live_chat(video_id, page_token):
    """Fetch live comments/chat for the video"""
    url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
    params = {
        "fields": "from{name},message,created_time",
        "order": "reverse_chronological",
        "access_token": page_token,
        "limit": 10
    }
    res = safe_request(url, params)

    if "data" not in res:
        print("⚠️ No comments data found")
        return []

    return res["data"]

if __name__ == "__main__":
    if not PAGE_TOKEN or not PAGE_ID:
        raise ValueError("❌ Missing required env vars: FB_PAGE_TOKEN, FB_PAGE_ID")

    print("🚀 Facebook Live Chat Fetcher started")

    while True:
        print("\n📺 Checking for live video...")
        live_video_id = get_live_video(PAGE_ID, PAGE_TOKEN)

        if live_video_id:
            print(f"🎯 Active live video ID: {live_video_id}")
            comments = get_live_chat(live_video_id, PAGE_TOKEN)

            if comments:
                print("💬 Latest comments:")
                for c in comments:
                    user = c["from"]["name"]
                    msg = c.get("message", "")
                    t = c["created_time"]
                    print(f"[{t}] {user}: {msg}")
            else:
                print("🕙 No new comments yet.")
        else:
            print("⏳ No live stream currently active.")

        time.sleep(15)  # 🔄 check every 15s
