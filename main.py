import asyncio
from playwright.async_api import async_playwright
import aiohttp
import logging
import time

CHANNEL_NAME = "lastmove"
NTFY_TOPIC = "streamchats123"

logging.basicConfig(level=logging.INFO, format="%(message)s")


async def send_ntfy(message: str):
    async with aiohttp.ClientSession() as session:
        await session.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=message.encode("utf-8"))
    await asyncio.sleep(5)  # 5s delay to prevent spam


async def fetch_chat():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        url = f"https://kick.com/{CHANNEL_NAME}"
        await page.goto(url)
        logging.info(f"🚀 Opened Kick channel: {CHANNEL_NAME}")

        # Wait for chat container to appear
        await page.wait_for_selector('div[data-test-id="chat-message"]')

        logging.info("✅ Chat detected, listening for messages...")

        # Listen for new messages
        async def handle_message(message):
            username = await message.query_selector_eval(
                'span[data-test-id="username"]', 'el => el.textContent'
            )
            text = await message.query_selector_eval(
                'div[data-test-id="message-content"]', 'el => el.textContent'
            )
            formatted = f"{username}: {text}"
            logging.info(f"💬 {formatted}")
            await send_ntfy(formatted)

        # Poll chat messages periodically
        seen_messages = set()
        while True:
            messages = await page.query_selector_all('div[data-test-id="chat-message"]')
            for msg in messages:
                msg_id = await msg.get_attribute("id")
                if msg_id not in seen_messages:
                    seen_messages.add(msg_id)
                    await handle_message(msg)
            await asyncio.sleep(2)  # check every 2s

        await browser.close()


if __name__ == "__main__":
    asyncio.run(fetch_chat())
