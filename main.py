import os
import time
import requests
import json

GRAPH = "https://graph.facebook.com/v20.0"

# ✅ Use the *same* env var names as your working setup
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
PAGE_ID = os.getenv("FB_PAGE_ID")

if not PAGE_TOKEN or not PAGE_ID:
    raise ValueError("❌ Missing env vars: FB_PAGE_TOKEN, FB_PAGE_ID")

# Track comment IDs we've already printed
seen_comment_ids = set()


def safe_request(url, params):
    """GET with basic error handling."""
    try:
        res = requests.get(url, params=params, timeout=15)
        data = res.json()
        if "error" in data:
            print(f"⚠️ API Error: {json.dumps(data, indent=2)}")
            return {}
        return data
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return {}


def get_live_video(page_id, page_token):
    """
    Find the currently LIVE video using /{page_id}/videos.
    This avoids the live-video-api endpoints completely.
    """
    url = f"{GRAPH}/{page_id}/videos"
    params = {
        "fields": "id,description,live_status,created_time",
        "access_token": page_token,
        "limit": 10,
    }
    res = safe_request(url, params)
    data = res.get("data", [])
    if not data:
        print("⏳ No videos data found yet.")
        return None

    for v in data:
        if v.get("live_status") == "LIVE":
            print(f"✅ Live video found: {v['id']} | {v.get('description','(no desc)')}")
            return v["id"]

    print("❌ No active LIVE video right now.")
    return None


def fetch_new_comments(video_id, page_token):
    """
    Pull the most recent comments and return only ones we haven't printed yet.
    No 'since' param needed — we dedupe by comment ID.
    """
    url = f"{GRAPH}/{video_id}/comments"
    params = {
        "fields": "id,from{name},message,created_time",
        "order": "reverse_chronological",  # newest first
        "access_token": page_token,
        "limit": 25,
        # You can optionally add: "filter": "toplevel"
    }
    res = safe_request(url, params)
    items = res.get("data", [])
    if not items:
        return []

    fresh = []
    for c in items:
        cid = c.get("id")
        if not cid:
            continue
        if cid not in seen_comment_ids:
            seen_comment_ids.add(cid)
            fresh.append(c)

    # Print from oldest to newest
    fresh.reverse()
    return fresh


def main():
    print("🚀 Facebook Live Chat Fetcher started")

    # Find current live video (retry until live starts)
    video_id = None
    while not video_id:
        print("\n📺 Checking for live video…")
        video_id = get_live_video(PAGE_ID, PAGE_TOKEN)
        if not video_id:
            time.sleep(10)

    print(f"🎯 Active live video ID: {video_id}")
    print("💬 Listening for new comments…")

    while True:
        new_comments = fetch_new_comments(video_id, PAGE_TOKEN)
        for c in new_comments:
            user = c.get("from", {}).get("name", "Unknown")
            msg = c.get("message", "")
            ts = c.get("created_time", "")
            print(f"[{ts}] {user}: {msg}")

        time.sleep(5)


if __name__ == "__main__":
    main()
