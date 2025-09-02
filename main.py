import os
import time
import requests
import json
from datetime import datetime

# 🔑 Load from environment variables
PAGE_ID = os.getenv("FB_PAGE_ID")
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")  # Permanent token

def get_live_video(page_id, page_token):
    """Fetch active live video for the page"""
    print("📺 Checking for live video...")
    url = f"https://graph.facebook.com/v20.0/{page_id}/live_videos"
    params = {
        "fields": "id,title,status,creation_time",
        "broadcast_status": "LIVE",
        "access_token": page_token,
        "limit": 5
    }
    res = requests.get(url, params=params).json()
    if "error" in res:
        print(f"⚠️ API Error: {json.dumps(res, indent=2)}")
        return None

    videos = res.get("data", [])
    if not videos:
        print("❌ No live stream currently active.")
        return None

    live_video = videos[0]
    print(f"✅ Live video found: {live_video['id']} | {live_video.get('title', '(no title)')}")
    return live_video["id"]

def get_live_comments(video_id, page_token, last_timestamp=None):
    """Fetch live comments from a live video"""
    url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
    params = {
        "fields": "from{name},message,created_time",
        "order": "chronological",
        "access_token": page_token,
        "limit": 10
    }

    # ✅ Only add since if we already have a timestamp
    if last_timestamp:
        params["since"] = int(last_timestamp)

    res = requests.get(url, params=params).json()
    if "error" in res:
        print(f"⚠️ API Error fetching comments: {json.dumps(res, indent=2)}")
        return []

    comments = res.get("data", [])
    if comments:
        print("💬 Latest comments:")
        for c in comments:
            user = c.get("from", {}).get("name", "Unknown")
            msg = c.get("message", "")
            ts = c.get("created_time")
            print(f"[{ts}] {user}: {msg}")

    return comments

if __name__ == "__main__":
    if not PAGE_ID or not PAGE_TOKEN:
        raise ValueError("❌ Missing required env variables: FB_PAGE_ID, FB_PAGE_TOKEN")

    live_video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
    if not live_video_id:
        exit(1)

    print(f"🎯 Active live video ID: {live_video_id}")

    last_timestamp = None

    # 🔁 Keep polling every 10 seconds
    while True:
        comments = get_live_comments(live_video_id, PAGE_TOKEN, last_timestamp)

        # Update last_timestamp with the latest comment
        if comments:
            last_time_str = comments[-1]["created_time"]
            last_timestamp = int(datetime.fromisoformat(last_time_str.replace("Z", "+00:00")).timestamp())

        time.sleep(10)
