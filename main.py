# -----------------------------
# --- Facebook Section (Render Ready) ---
# -----------------------------
import os
import time
import threading
import requests
from flask import Flask, request, jsonify
from queue import Queue

# -----------------------------
# --- Config / Env Variables ---
# -----------------------------
FB_PAGE_TOKEN = os.getenv("FB_PAGE_TOKEN")
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_VERIFY_TOKEN = os.getenv("FB_VERIFY_TOKEN")  # used for webhook handshake

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "streamchats123")
ntfy_queue = Queue()  # central NTFY queue

GRAPH = "https://graph.facebook.com/v20.0"

# -----------------------------
# --- Flask App for Webhook ---
# -----------------------------
fb_app = Flask(__name__)

# Store active live video IDs
active_live_videos = set()

# -----------------------------
# --- NTFY Sender Worker ---
# -----------------------------
def ntfy_worker():
    import time
    while True:
        msg_obj = ntfy_queue.get()
        if msg_obj is None:
            break
        try:
            body = f"{msg_obj['user']}: {msg_obj['msg']}"
            title = msg_obj.get("title", "Facebook")
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=body.encode("utf-8"),
                headers={"Title": title},
                timeout=5,
            )
        except Exception as e:
            print("⚠️ Failed to send NTFY:", e)
        ntfy_queue.task_done()

# -----------------------------
# --- Webhook Route ---
# -----------------------------
@fb_app.route("/webhook", methods=["GET", "POST"])
def facebook_webhook():
    # Verification handshake
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode == "subscribe" and token == FB_VERIFY_TOKEN:
            print("✅ Facebook webhook verified!")
            return challenge, 200
        return "Verification failed", 403

    # Incoming events
    if request.method == "POST":
        data = request.json
        for entry in data.get("entry", []):
            changes = entry.get("changes", [])
            for change in changes:
                field = change.get("field")
                value = change.get("value", {})
                if field == "live_videos":
                    video_id = value.get("id")
                    desc = value.get("description", "(no description)")
                    if video_id:
                        print(f"🎬 Live video detected: {video_id} | {desc}")
                        active_live_videos.add(video_id)
        return "OK", 200

# -----------------------------
# --- Poll Live Comments ---
# -----------------------------
def poll_fb_comments():
    seen_ids = set()
    while True:
        for video_id in list(active_live_videos):
            try:
                url = f"{GRAPH}/{video_id}/comments"
                params = {
                    "fields": "id,from{{name}},message,created_time",
                    "access_token": FB_PAGE_TOKEN,
                    "order": "chronological",
                    "limit": 25
                }
                res = requests.get(url, params=params).json()
                comments = res.get("data", [])

                if not comments:
                    continue

                for c in comments:
                    cid = c.get("id")
                    if not cid or cid in seen_ids:
                        continue
                    user = c.get("from", {}).get("name", "Unknown")
                    msg = c.get("message", "")
                    print(f"[Facebook] {user}: {msg}")
                    ntfy_queue.put({"title": "Facebook", "user": user, "msg": msg})
                    seen_ids.add(cid)

            except Exception as e:
                print("⚠️ Error fetching Facebook comments:", e)

        time.sleep(2)  # poll every 2 seconds

# -----------------------------
# --- Subscribe Page to Webhook ---
# -----------------------------
def subscribe_facebook_page():
    if not FB_PAGE_TOKEN or not FB_PAGE_ID:
        print("⚠️ Cannot subscribe webhook, missing token or page ID")
        return
    url = f"{GRAPH}/{FB_PAGE_ID}/subscribed_apps"
    params = {
        "access_token": FB_PAGE_TOKEN,
        "subscribed_fields": "live_videos"
    }
    try:
        res = requests.post(url, params=params).json()
        print("📡 Facebook webhook subscription result:", res)
    except Exception as e:
        print("❌ Failed to subscribe Facebook webhook:", e)

# -----------------------------
# --- Start All Facebook Services ---
# -----------------------------
def start_facebook_services():
    # Start NTFY worker
    threading.Thread(target=ntfy_worker, daemon=True).start()
    # Start polling live comments
    threading.Thread(target=poll_fb_comments, daemon=True).start()
    # Subscribe page webhook
    subscribe_facebook_page()
    print("✅ Facebook services started.")

# -----------------------------
# --- Flask Entry Point ---
# -----------------------------
if __name__ == "__main__":
    start_facebook_services()
    port = int(os.environ.get("PORT", 5000))
    fb_app.run(host="0.0.0.0", port=port)
