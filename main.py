import os
import asyncio
import httpx
from fastapi import FastAPI

app = FastAPI()

# Hardcode channel
CHANNEL = "LastMove"  

# Ntfy config
NTFY_URL = "https://ntfy.sh/kick-chat"  # change if needed

async def send_to_ntfy(client, message: str):
    """Send message to ntfy and also print to console"""
    print(message)
    try:
        await client.post(NTFY_URL, data=message.encode("utf-8"))
    except Exception as e:
        print("❌ Failed to send to ntfy:", e)

async def poll_and_forward_chat(channel: str):
    """Poll Kick API for channel livestream + chats"""
    async with httpx.AsyncClient() as client:
        await send_to_ntfy(client, f"🚀 Kick chat fetcher started for channel: {channel}")

        last_message_ids = set()

        while True:
            try:
                # Fetch channel info
                resp = await client.get(f"https://kick.com/api/v2/channels/{channel}")
                if resp.status_code != 200:
                    await send_to_ntfy(client, f"❌ Channel fetch failed [{resp.status_code}]: {resp.text[:200]}")
                    await asyncio.sleep(10)
                    continue

                info = resp.json()

                # Check livestream
                if not info.get("livestream"):
                    await send_to_ntfy(client, f"📡 {channel} is offline, retrying in 10s...")
                    await asyncio.sleep(10)
                    continue

                livestream = info["livestream"]
                chatroom_id = livestream["chatroom"]["id"]

                # Poll chat messages
                chat_resp = await client.get(
                    f"https://kick.com/api/v2/chatrooms/{chatroom_id}/messages"
                )
                if chat_resp.status_code != 200:
                    await send_to_ntfy(client, f"❌ Chat fetch failed [{chat_resp.status_code}]: {chat_resp.text[:200]}")
                    await asyncio.sleep(5)
                    continue

                chats = chat_resp.json().get("messages", [])
                for chat in chats:
                    msg_id = chat.get("id")
                    if msg_id in last_message_ids:
                        continue
                    last_message_ids.add(msg_id)

                    username = chat.get("sender", {}).get("username", "Unknown")
                    text = chat.get("content", "")
                    formatted = f"{username}: {text}"
                    await send_to_ntfy(client, formatted)

                    await asyncio.sleep(5)  # spam-proof delay

            except Exception as e:
                await send_to_ntfy(client, f"❌ Error: {e}")
                await asyncio.sleep(10)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(poll_and_forward_chat(CHANNEL))

@app.get("/healthz")
async def healthz():
    return {"ok": True}
