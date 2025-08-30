import asyncio
import json
import websockets
import logging
import aiohttp

# --- Configuration ---
CHANNEL_NAME = "lastmove"       # Kick channel name
KICK_USERNAME = "lastmove"   # Any nickname for IRC connection
NTFY_TOPIC = "streamchats123"       # Your ntfy topic
DELAY = 5                       # Delay between messages for spam proof

logging.basicConfig(level=logging.INFO, format="%(message)s")

# --- Send message to NTFY ---
async def send_ntfy(user: str, message: str):
    async with aiohttp.ClientSession() as session:
        await session.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=f"{user}: {message}".encode("utf-8"))
    await asyncio.sleep(DELAY)

# --- Connect to Kick WebSocket ---
async def connect_kick():
    while True:
        try:
            ws_url = "wss://irc-ws.chat.kick.com/"
            async with websockets.connect(ws_url) as ws:
                logging.info(f"✅ Connected to Kick chat for {CHANNEL_NAME}")

                # IRC-style commands
                await ws.send(f"NICK {KICK_USERNAME}")
                await ws.send(f"JOIN #{CHANNEL_NAME}")

                async for raw_msg in ws:
                    try:
                        lines = raw_msg.split("\r\n")
                        for line in lines:
                            if "PRIVMSG" in line:
                                # IRC message parsing
                                parts = line.split(":", 2)
                                if len(parts) >= 3:
                                    user = parts[1].split("!")[0]
                                    msg = parts[2]
                                    formatted = f"{user}: {msg}"
                                    logging.info(f"💬 {formatted}")
                                    await send_ntfy(user, msg)
                    except Exception as e:
                        logging.error(f"⚠️ Failed to parse message: {e}")

        except Exception as e:
            logging.error(f"❌ Disconnected or error, retrying in 5s... {e}")
            await asyncio.sleep(5)

# --- Main ---
if __name__ == "__main__":
    asyncio.run(connect_kick())
