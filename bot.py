from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped
from yt_dlp import YoutubeDL
import asyncio

API_ID = 123456  # তোমার API_ID
API_HASH = "your_api_hash"  # তোমার API_HASH
BOT_TOKEN = "your_bot_token"  # তোমার বট টোকেন

app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
pytgcalls = PyTgCalls(app)

ydl_opts = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

async def start():
    await app.start()
    await pytgcalls.start()
    print("Bot started")

@app.on_message(filters.command("play") & filters.private)
async def play(_, message):
    url = message.text.split(None, 1)[1]
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        url2 = info['url']

    await pytgcalls.join_group_call(
        message.chat.id,
        AudioPiped(url2),
    )
    await message.reply_text("Playing now!")

@app.on_message(filters.command("stop") & filters.private)
async def stop(_, message):
    await pytgcalls.leave_group_call(message.chat.id)
    await message.reply_text("Stopped!")

if __name__ == "__main__":
    asyncio.run(start())
    app.run()
