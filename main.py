import os
import time
import requests
import json

# 🔑 Permanent Page Access Token (from Graph API Explorer with manage_pages & pages_read_engagement)
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
PAGE_ID = os.getenv("FB_PAGE_ID")

GRAPH_API = "https://graph.facebook.com/v20.0"

def get_live_video(page_id, page_token):
    """Get currently active live video using safe fields=live_videos expansion"""
    url = f"{GRAPH_API}/{page_id}"
    params = {
        "fields": "live_videos.limit(1){id,title,creation_time,status}",
        "access_token": page_token
    }
    res = requests.get(url, params=params).json()

    if "error" in res:
        print("⚠️ API Error:", json.dumps(res, indent=2))
        return None

    videos = res.get("live_videos", {}).get("data", [])
    if not videos:
        print("❌ No live stream currently active.")
        return None

    live = videos[0]
    if live.get("status") != "LIVE":
        print("❌ No active LIVE video found.")
        return None

    print(f"✅ Live video found: {live['id']} | {live.get('title','(no title)')}")
    return live["id"]

def fetch_comments(video_id, page_token, since=None):
    """Fetch comments on the live video. Use 'since' to only get new ones."""
    url = f"{GRAPH_API}/{video_id}/comments"
    params = {
        "order": "reverse_chronological",
        "access_token": page_token,
        "fields": "from,message,created_time"
    }
    if since:
        params["since"] = since

    res = requests.get(url, params=params).json()
    if "error" in res:
        print("⚠️ API Error fetching comments:", json.dumps(res, indent=2))
        return [], since

    comments = res.get("data", [])
    new_since = since
    if comments:
        # Update "since" to the latest comment timestamp
        new_since = comments[0]["created_time"]

    return comments, new_since

def run():
    if not PAGE_TOKEN or not PAGE_ID:
        raise ValueError("❌ Missing FB_PAGE_TOKEN or FB_PAGE_ID env vars")

    print("📺 Checking for live video...")
    video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
    if not video_id:
        return

    print(f"🎯 Active live video ID: {video_id}")
    last_seen = None

    while True:
        comments, last_seen = fetch_comments(video_id, PAGE_TOKEN, last_seen)
        for c in reversed(comments):  # oldest first
            user = c["from"]["name"] if "from" in c else "Unknown"
            msg = c.get("message", "")
            ts = c.get("created_time", "")
            print(f"[{ts}] {user}: {msg}")
        time.sleep(5)

if __name__ == "__main__":
    run()
