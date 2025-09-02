import os
import time
import requests
import json

PAGE_ID = os.getenv("FB_PAGE_ID")
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")

def safe_request(url, params):
    """Helper to handle requests safely and print errors"""
    res = requests.get(url, params=params)
    try:
        data = res.json()
    except Exception:
        print("⚠️ Failed to parse response")
        return {}
    if "error" in data:
        print("⚠️ API Error:", json.dumps(data, indent=2))
    return data

def get_live_video(page_id, page_token):
    """Check for currently active live video"""
    url = f"https://graph.facebook.com/v20.0/{page_id}/live_videos"
    params = {"fields": "id,status,title,creation_time", "access_token": page_token}
    res = safe_request(url, params)

    if "data" not in res:
        print("⚠️ No videos data found")
        return None

    for v in res["data"]:
        if v.get("status") == "LIVE":
            print(f"✅ Live video found: {v['id']} | {v.get('title','(no title)')}")
            return v["id"]

    print("❌ No active LIVE video right now")
    return None

def fetch_live_chat(video_id, page_token):
    """Fetch latest comments (live chat)"""
    url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
    params = {
        "fields": "from{name},message,created_time",
        "order": "reverse_chronological",
        "limit": 10,
        "access_token": page_token
    }
    res = safe_request(url, params)
    return res.get("data", [])

if __name__ == "__main__":
    if not PAGE_TOKEN or not PAGE_ID:
        raise RuntimeError("❌ Missing PAGE_ID or FB_PAGE_TOKEN")

    print("📺 Checking for live video...")
    live_video_id = None

    # Keep checking until you go live
    while not live_video_id:
        live_video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
        if not live_video_id:
            time.sleep(15)

    print(f"🎯 ACTIVE LIVE VIDEO ID = {live_video_id}")

    # Start reading live chat
    seen = set()
    print("\n💬 Fetching live comments...\n")
    while True:
        comments = fetch_live_chat(live_video_id, PAGE_TOKEN)
        for c in comments:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            print(f"[{c['created_time']}] {c['from']['name']}: {c['message']}")
        time.sleep(5)
