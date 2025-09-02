import os
import time
import requests
import json

# 🔑 Permanent Page Token (set in Railway ENV)
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
PAGE_ID = os.getenv("FB_PAGE_ID")

def get_live_video(page_id, page_token):
    """Fetch active live video from the Page videos list"""
    url = f"https://graph.facebook.com/v20.0/{page_id}/videos"
    params = {
        "fields": "id,description,live_status,created_time",
        "access_token": page_token,
        "limit": 5
    }
    res = requests.get(url, params=params).json()
    print("📺 Checking for live video...")

    if "error" in res:
        print("⚠️ API Error:", json.dumps(res, indent=2))
        return None

    if "data" not in res:
        print("⚠️ No videos data found")
        return None

    for v in res["data"]:
        if v.get("live_status") == "LIVE":
            print(f"✅ Live video found: {v['id']} | {v.get('description','(no desc)')}")
            return v["id"]

    print("❌ No active LIVE video found.")
    return None

def get_live_comments(video_id, page_token, since=None):
    """Fetch comments from live video"""
    url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
    params = {
        "fields": "from{name},message,created_time",
        "order": "reverse_chronological",
        "access_token": page_token,
        "since": since or 0
    }
    res = requests.get(url, params=params).json()

    if "error" in res:
        print("⚠️ API Error fetching comments:", json.dumps(res, indent=2))
        return [], since

    comments = res.get("data", [])
    new_since = since

    if comments:
        for c in comments:
            name = c["from"]["name"] if "from" in c else "Unknown"
            msg = c.get("message", "")
            t = c.get("created_time", "")
            print(f"[{t}] {name}: {msg}")

        # update since with the latest timestamp
        last_time = comments[0]["created_time"]
        new_since = int(time.mktime(time.strptime(last_time, "%Y-%m-%dT%H:%M:%S+0000")))

    return comments, new_since

if __name__ == "__main__":
    if not PAGE_TOKEN or not PAGE_ID:
        raise ValueError("❌ Missing FB_PAGE_TOKEN or FB_PAGE_ID in environment variables")

    # Step 1: Find active live video
    video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
    if not video_id:
        print("❌ No live stream currently active. Exiting.")
        exit(0)

    print(f"🎯 Active live video ID: {video_id}")

    # Step 2: Poll comments
    since = None
    while True:
        comments, since = get_live_comments(video_id, PAGE_TOKEN, since)
        time.sleep(5)  # poll every 5s
