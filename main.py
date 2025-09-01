import os
import requests
import time

# ----------------------
# Configuration
# ----------------------
PAGE_ID = os.getenv("FB_PAGE_ID")
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
POLL_INTERVAL = 5  # seconds

if not PAGE_ID or not PAGE_TOKEN:
    print("Please set environment variables FB_PAGE_ID and FB_PAGE_TOKEN")
    exit(1)

# ----------------------
# Functions
# ----------------------
def get_current_live_video():
    url = f"https://graph.facebook.com/v18.0/{PAGE_ID}/live_videos"
    params = {"status": "LIVE_NOW", "access_token": PAGE_TOKEN}
    
    resp = requests.get(url, params=params).json()
    if "data" in resp and resp["data"]:
        return resp["data"][0]["id"]
    return None

def fetch_new_comments(video_id, seen_ids):
    """
    Fetches only new comments since last fetch.
    """
    url = f"https://graph.facebook.com/v18.0/{video_id}/comments"
    params = {
        "order": "chronological",  # oldest first
        "access_token": PAGE_TOKEN,
        "limit": 50  # max per request
    }
    resp = requests.get(url, params=params).json()
    
    for comment in resp.get("data", []):
        cid = comment["id"]
        if cid not in seen_ids:
            seen_ids.add(cid)
            author = comment.get("from", {}).get("name", "Unknown")
            message = comment.get("message", "")
            print(f"[Facebook] {author}: {message}")
    return seen_ids

# ----------------------
# Main loop
# ----------------------
def main():
    seen_ids = set()
    last_video_id = None

    print("Starting Facebook Live chat fetcher...")

    while True:
        video_id = get_current_live_video()
        if video_id:
            if video_id != last_video_id:
                print(f"Connected to Facebook live video: {video_id}")
                seen_ids.clear()  # reset seen comments for new video
                last_video_id = video_id

            seen_ids = fetch_new_comments(video_id, seen_ids)
        else:
            print("No live video currently.")
            last_video_id = None
            seen_ids.clear()
        
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
