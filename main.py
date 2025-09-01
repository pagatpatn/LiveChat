import os
import requests
import time

# ----------------------
# Configuration from environment
# ----------------------
PAGE_ID = os.getenv("FB_PAGE_ID")
PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
POLL_INTERVAL = 5  # seconds between comment fetches

if not PAGE_ID or not PAGE_TOKEN:
    print("Please set environment variables FB_PAGE_ID and FB_PAGE_TOKEN")
    exit(1)

# ----------------------
# Functions
# ----------------------
def get_current_live_video():
    """
    Returns the current live video ID for the Page,
    or None if no live video is active.
    """
    url = f"https://graph.facebook.com/v18.0/{PAGE_ID}/live_videos"
    params = {"status": "LIVE_NOW", "access_token": PAGE_TOKEN}
    resp = requests.get(url, params=params).json()
    
    # Debug output
    print("Live video API response:", resp)
    
    if "data" in resp and resp["data"]:
        return resp["data"][0]["id"]
    return None

def fetch_comments(video_id, seen_ids=set()):
    """
    Fetches comments for a live video and prints new ones.
    """
    url = f"https://graph.facebook.com/v18.0/{video_id}/comments"
    params = {"order": "reverse_chronological", "access_token": PAGE_TOKEN}
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
    seen = set()
    print("Starting Facebook Live chat fetcher...")
    
    while True:
        video_id = get_current_live_video()
        if video_id:
            seen = fetch_comments(video_id, seen)
        else:
            print("No live video currently.")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
