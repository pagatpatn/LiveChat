from fastapi import FastAPI
import httpx
import asyncio
import os
from datetime import datetime

app = FastAPI()

# Config
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "kick-chat")
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"
CHANNEL = os.getenv("KICK_CHANNEL", "LastMove")

async def send_to_ntfy(client, message: str):
    """Send logs/messages to ntfy + console"""
    print(message)  # Always log to Railway too
    try:
        await client.post(NTFY_URL, data=message.encode("utf-8"))
    except Exception as e:
        print("❌ Failed to send to ntfy:", e)

async def poll_and_forward_chat(channel: str):
    last_message_id = None
    was_live = False

    async with httpx.AsyncClient() as client:
        # Get chatroom id once
        channel_info = await client.get(f"https://kick.com/api/v2/channels/{channel}")
        if channel_info.status_code != 200:
            await send_to_ntfy(client, f"❌ Could not fetch channel info for {channel}")
            return

        chatroom_id = channel_info.json().get("chatroom", {}).get("id")
        if not chatroom_id:
            await send_to_ntfy(client, f"❌ No chatroom found for {channel}")
            return

        await send_to_ntfy(client, f"🎯 Using chatroom ID {chatroom_id} for {channel}")

        while True:
            try:
                # 1. Check if live
                live_resp = await client.get(f"https://kick.com/api/v2/channels/{channel}/livestream")
                is_live = (live_resp.status_code == 200 and live_resp.json())

                if is_live and not was_live:
                    msg = f"✅ {channel} is now LIVE! ({datetime.now().strftime('%H:%M:%S')})"
                    await send_to_ntfy(client, msg)
                    was_live = True
                elif not is_live and was_live:
                    msg = f"🛑 {channel} went OFFLINE. ({datetime.now().strftime('%H:%M:%S')})"
                    await send_to_ntfy(client, msg)
                    was_live = False

                if not is_live:
                    await send_to_ntfy(client, f"{channel} is offline, retrying in 10s...")
                    await asyncio.sleep(10)
                    continue

                # 2. Fetch chat messages
                chat_resp = await client.get(f"https://kick.com/api/v2/chatrooms/{chatroom_id}/messages")
                if chat_resp.status_code == 200:
                    data = chat_resp.json()
                    messages = data.get("messages", [])

                    for msg in messages:
                        if last_message_id is None or msg["id"] > last_message_id:
                            username = msg["sender"]["username"]
                            text = msg["content"]
                            payload = f"{username}: {text}"

                            await send_to_ntfy(client, "💬 " + payload)

                            last_message_id = msg["id"]

                            await asyncio.sleep(5)  # spam delay

            except Exception as e:
                await send_to_ntfy(client, f"⚠️ Error fetching: {e}")

            await asyncio.sleep(5)


@app.on_event("startup")
async def startup_event():
    boot_msg = f"🚀 Starting Kick chat fetcher for channel: {CHANNEL}"
    print(boot_msg)
    async with httpx.AsyncClient() as client:
        await send_to_ntfy(client, boot_msg)
    asyncio.create_task(poll_and_forward_chat(CHANNEL))


@app.get("/healthz")
async def healthz():
    return {"ok": True}
