import os
import time
import re
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import threading

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")
POLL_INTERVAL = 3  # Polling every 5 seconds
TIME_WINDOW_MINUTES = 5  # Time window for fetching messages

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# Emoji regex pattern
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def send_ntfy(user, msg):
    """Send chat message notifications."""
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=f"{user}: {msg}".encode("utf-8"))
        time.sleep(POLL_INTERVAL)
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def extract_emoji(text):
    """Extract and replace emojis from the text."""
    matches = re.findall(emoji_pattern, text)
    if matches:
        # Replace emote with actual emoji text
        for match in matches:
            emote_id, emote_name = match
            text = text.replace(f"[emote:{emote_id}:{emote_name}]", f"🎉 {emote_name}")  # Example of emoji handling
    return text

def get_latest_message():
    """Get the latest live chat message for a channel."""
    try:
        channel = kick_api.channel(KICK_CHANNEL)
        
        if not channel:
            print(f"❌ Channel {KICK_CHANNEL} not found.")
            return None
        
        # Fetch messages within the last TIME_WINDOW_MINUTES
        past_time = datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)
        formatted_time = past_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        chat = kick_api.chat(channel.id, formatted_time)
        
        if chat and hasattr(chat, 'messages') and chat.messages:
            # Only return the latest message
            latest_message = chat.messages[-1]
            return {
                'username': latest_message.sender.username if hasattr(latest_message, 'sender') else 'Unknown',
                'text': extract_emoji(latest_message.text) if hasattr(latest_message, 'text') else 'No text',
                'timestamp': datetime.now().strftime('%H:%M:%S'),
                'channel': channel.username
            }
        
        return None
    except Exception as e:
        print(f"❌ Error fetching live chat: {e}")
        return None

def listen_live_chat():
    """Fetch and listen to live chat for a Kick video."""
    last_fetched_message_id = None  # Track the last message ID to avoid duplicates

    while True:
        latest_message = get_latest_message()
        
        if latest_message is None:
            time.sleep(POLL_INTERVAL)  # No new messages, retrying after the interval
            continue

        # Check if the message is new (based on message content and timestamp)
        message_id = f"{latest_message['username']}:{latest_message['text']}"
        
        if message_id != last_fetched_message_id:
            print(f"{latest_message['username']}: {latest_message['text']}")
            send_ntfy(latest_message['username'], latest_message['text'])
            last_fetched_message_id = message_id  # Update the last fetched message ID
        
        time.sleep(POLL_INTERVAL)  # Poll every 5 seconds

def start_listener():
    """Start the live chat listener in a background thread."""
    listener_thread = threading.Thread(target=listen_live_chat)
    listener_thread.daemon = True  # Allows thread to exit when the main program exits
    listener_thread.start()

if __name__ == "__main__":
    start_listener()
    print("Listener started. Running in the background...")
    
    # Keep the main process alive, allowing the background thread to continue running.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting due to user interrupt.")
