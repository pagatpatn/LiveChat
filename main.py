import os
import requests
import json
import time

# 🔑 Environment variables (set these in Railway)
PAGE_ID = os.getenv("FB_PAGE_ID")
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")

if not PAGE_ID or not PAGE_TOKEN:
    raise ValueError("❌ Missing required environment variables: FB_PAGE_ID, FB_PAGE_TOKEN")


def get_live_video(page_id, page_token):
    """Fetch currently active live video from Page"""
    print("📺 Checking for live video...")
    url = f"https://graph.facebook.com/v20.0/{page_id}"
    params = {
        "fields": "live_videos.limit(1){id,title,creation_time,status}",
        "access_token": page_token
    }
    res = requests.get(url, params=params).json()
    if "error" in res:
        print(f"⚠️ API Error: {json.dumps(res, indent=2)}")
        return None

    videos = res.get("live_videos", {}).get("data", [])
    if not videos:
        print("❌ No live stream currently active.")
        return None

    live_video = videos[0]
    print(f"✅ Live video found: {live_video['id']} | {live_video.get('title', '(no title)')}")
    return live_video["id"]


def get_live_comments(video_id, page_token, since_time=None):
    """Fetch new comments from the live video"""
    url = f"https://graph.facebook.com/v20.0/{video_id}/comments"
    params = {
        "fields": "from{name},message,created_time",
        "order": "chronological",
        "access_token": page_token,
        "filter": "toplevel",
        "limit": 10
    }
    if since_time:
        params["since"] = since_time

    res = requests.get(url, params=params).json()
    if "error" in res:
        print(f"⚠️ API Error fetching comments: {json.dumps(res, indent=2)}")
        return []

    return res.get("data", [])


if __name__ == "__main__":
    video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
    if not video_id:
        exit(1)

    print(f"🎯 Active live video ID: {video_id}")

    # Start polling for new comments
    last_timestamp = int(time.time())
    while True:
        comments = get_live_comments(video_id, PAGE_TOKEN, since_time=last_timestamp)
        if comments:
            for c in comments:
                user = c["from"]["name"]
                msg = c["message"]
                ts = c["created_time"]
                print(f"[{ts}] {user}: {msg}")

            # update marker to "now" so we only fetch new ones next time
            last_timestamp = int(time.time())

        time.sleep(5)
