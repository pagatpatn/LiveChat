import os
import time
import json
import requests
import websocket
import threading
import ssl

# --- Config from Railway environment variables ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL")  # e.g., LastMove
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chats")
NTFY_DELAY = 5  # seconds between messages

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

# --- NTFY sender ---
def send_ntfy(user: str, message: str):
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"{user}: {message}".encode("utf-8")
        )
        time.sleep(NTFY_DELAY)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

# --- WebSocket handlers ---
def on_message(ws, message):
    try:
        data = json.loads(message)
        # Kick chat messages usually contain 'text' and 'username'
        if "text" in data and "username" in data:
            user = data["username"]
            text = data["text"]
            print(f"{user}: {text}")
            send_ntfy(user, text)
    except Exception as e:
        print("❌ Failed to parse message:", e)

def on_error(ws, error):
    print("❌ WebSocket error:", error)

def on_close(ws, close_status_code, close_msg):
    print("⚠️ WebSocket closed. Reconnecting in 5s...")
    time.sleep(5)
    start_listener()  # auto-reconnect

def on_open(ws):
    print(f"✅ Connected to Kick chatroom: {KICK_CHANNEL}")

# --- Start the listener ---
def start_listener():
    url = f"wss://kick.com/api/v2/channels/{KICK_CHANNEL}/chatroom"
    ws = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open,
    )
    ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

# --- Run ---
if __name__ == "__main__":
    threading.Thread(target=start_listener, daemon=True).start()
    print(f"🚀 Starting Kick chat listener for channel: {KICK_CHANNEL}")
    while True:
        time.sleep(1)
