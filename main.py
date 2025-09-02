import os
import time
import requests
import json

# 🔑 Permanent Page Token + Page ID
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")  # permanent token
PAGE_ID = os.getenv("FB_PAGE_ID")

def get_live_video(page_id, page_token):
    """Fetch currently active live video for the page"""
    url = f"https://graph.facebook.com/v20.0/{page_id}/live_videos"
    params = {"fields": "id,status,title", "access_token": page_token}
    res = requests.get(url, params=params).json()

    if "error" in res:
        print("⚠️ API Error:", json.dumps(res, indent=2))
        return None

    if "data" not in res or not res["data"]:
        print("❌ No live videos found.")
        return None

    for v in res["data"]:
        if v.get("status") == "LIVE":
            print(f"✅ Live video found: {v['id']} | {v.get('title','(no title)')}")
            return v["id"]

    print("❌ No active LIVE stream.")
    return None

def fetch_live_comments(video_id, page_token, seen_ids):
    """Fetch new comments from live video"""
    url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
    params = {
        "fields": "from{name},message,created_time",
        "order": "reverse_chronological",  # newest first
        "access_token": page_token,
        "limit": 10
    }
    res = requests.get(url, params=params).json()

    if "error" in res:
        print("⚠️ API Error:", json.dumps(res, indent=2))
        return

    if "data" not in res:
        return

    new_comments = []
    for c in res["data"]:
        if c["id"] not in seen_ids:
            seen_ids.add(c["id"])
            new_comments.append(c)

    # Print in chronological order
    for c in reversed(new_comments):
        user = c["from"]["name"]
        msg = c.get("message", "")
        ts = c["created_time"]
        print(f"[{ts}] {user}: {msg}")

def main():
    if not PAGE_TOKEN or not PAGE_ID:
        raise ValueError("❌ Missing PAGE_TOKEN or PAGE_ID env variables")

    print("📺 Checking for live video...")
    video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
    if not video_id:
        print("❌ No live stream currently active. Exiting.")
        return

    print(f"🎯 Active live video ID: {video_id}")
    seen_ids = set()

    print("💬 Fetching live comments... (press Ctrl+C to stop)")
    try:
        while True:
            fetch_live_comments(video_id, PAGE_TOKEN, seen_ids)
            time.sleep(5)  # poll every 5 sec
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")

if __name__ == "__main__":
    main()
