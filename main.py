import os
import time
import threading
import re
from datetime import datetime, timedelta
from kickapi import KickAPI
import requests

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")  # Default channel, set from env variable
POLL_INTERVAL = 0.5  # Polling every 0.5 second for real-time chat capture
TIME_WINDOW_MINUTES = 0.3  # Time window for fetching messages (2 minutes)
NTFY_API_URL = "https://ntfy.sh/streamchats123"  # Replace with your NTFY topic URL

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# Emoji mappings for the emote codes (you can add more here)
EMOJI_MAP = {
    "GiftedYAY": "🎉",  # Example emoji mapping
    # Add more emotes as needed here
}

# Emoji regex pattern
emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text):
    """Extract and replace emojis from the text."""
    matches = re.findall(emoji_pattern, text)
    if matches:
        # Replace emote with actual emoji text
        for match in matches:
            emote_id, emote_name = match
            emoji = EMOJI_MAP.get(emote_name, f"[{emote_name}]")  # Default to text if not found
            text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji)
    return text

def send_ntfy_notification(message):
    """Send chat message to NTFY with a 5 second delay."""
    time.sleep(5)  # Delay for 5 seconds before sending notification
    
    # Prepare the payload to send to NTFY
    payload = {
        'title': f"New message from {message['username']}",
        'message': message['text'],  # Ensure the message is in proper text format
    }
    
    try:
        # Send message to NTFY
        response = requests.post(NTFY_API_URL, json=payload)
        if response.status_code == 200:
            pass  # No log for success
        else:
            print(f"❌ Failed to send to NTFY. Status Code: {response.status_code}")
    except Exception as e:
        print(f"❌ Error sending to NTFY: {e}")

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
            # Print the message to console immediately (real-time)
            print(f"[{latest_message['timestamp']}] {latest_message['username']}: {latest_message['text']}")
            
            # Send the message to NTFY with 5 seconds delay in a separate thread
            threading.Thread(target=send_ntfy_notification, args=(latest_message,)).start()
            
            last_fetched_message_id = message_id  # Update the last fetched message ID
        
        time.sleep(POLL_INTERVAL)  # Poll every 0.5 second for new messages

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
