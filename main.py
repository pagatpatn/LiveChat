import os
import time
import requests
from datetime import datetime, timedelta
from kickapi import KickAPI
import re

# --- Config ---
KICK_CHANNEL = os.getenv("KICK_CHANNEL", "default_channel")  # Set default channel if not provided
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat-notifications")  # Set default NTFY topic
POLL_INTERVAL = 0.1  # Polling interval in seconds
TIME_WINDOW_MINUTES = 0.05  # Time window for fetching messages (e.g., last 5 minutes)

if not KICK_CHANNEL:
    raise ValueError("Please set KICK_CHANNEL environment variable")

kick_api = KickAPI()

# --- Emoji Mapping ---
# Replace the emote codes with real emojis, add more mappings as needed
EMOJI_MAP = {
    "GiftedYAY": "🎉",
    "ErectDance": "💃",
    # Add more emojis if needed
}

emoji_pattern = r"\[emote:(\d+):([^\]]+)\]"

def extract_emoji(text):
    """Extract and replace emoji codes with real emojis."""
    matches = re.findall(emoji_pattern, text)
    for match in matches:
        emote_id, emote_name = match
        emoji = EMOJI_MAP.get(emote_name, f"[{emote_name}]")  # Default to text if no match found
        text = text.replace(f"[emote:{emote_id}:{emote_name}]", emoji)
    return text

def send_ntfy(user, msg):
    """Send chat message notifications to NTFY."""
    try:
        # Format message before sending to NTFY
        formatted_msg = f"{user}: {msg}"
        
        # Send the notification with the Title Kick
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", 
                      data=formatted_msg.encode("utf-8"), 
                      headers={ "Title": "Kick"})
    except Exception as e:
        print("⚠️ Failed to send NTFY:", e)

def get_live_chat():
    """Fetch live chat messages for the given channel."""
    try:
        # Fetching chat for the specified channel
        channel = kick_api.channel(KICK_CHANNEL)

        if not channel:
            return None
        
        # Fetch messages within the last TIME_WINDOW_MINUTES
        past_time = datetime.utcnow() - timedelta(minutes=TIME_WINDOW_MINUTES)
        formatted_time = past_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')

        chat = kick_api.chat(channel.id, formatted_time)
        messages = []
        
        if chat and hasattr(chat, 'messages') and chat.messages:
            for msg in chat.messages:
                # Extract and replace emoji
                message_text = msg.text if hasattr(msg, 'text') else 'No text'
                message_text = extract_emoji(message_text)  # Ensure emojis are parsed correctly
                messages.append({
                    'username': msg.sender.username if hasattr(msg, 'sender') else 'Unknown',
                    'text': message_text,
                    'timestamp': datetime.now().strftime('%H:%M:%S'),
                    'channel': channel.username
                })
        
        return messages
    except Exception as e:
        return None

def listen_live_chat():
    """Fetch and listen to live chat for the channel."""
    last_fetched_messages = set()  # Track messages we've already sent
    last_sent_time = time.time()  # Store the time of the last message sent to NTFY

    while True:
        messages = get_live_chat()
        
        if not messages:
            time.sleep(10)  # No new messages, retry
            continue

        for msg in messages:
            msg_id = f"{msg['username']}:{msg['text']}"  # Unique message identifier
            
            # Prevent message from being captured again
            if msg_id not in last_fetched_messages:
                # Check if we should send to NTFY
                if time.time() - last_sent_time >= 5:
                    # Log only the messages we are sending
                    print(f"[{msg['timestamp']}] {msg['username']}: {msg['text']}")
                    send_ntfy(msg['username'], msg['text'])  # Send message to NTFY
                    last_fetched_messages.add(msg_id)  # Add message to set to prevent re-sending
                    last_sent_time = time.time()  # Update last sent time
        
        time.sleep(POLL_INTERVAL)  # Poll every few seconds

if __name__ == "__main__":
    listen_live_chat()



