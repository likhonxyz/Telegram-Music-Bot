from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped
from pytgcalls.types.stream import StreamAudioEnded
from yt_dlp import YoutubeDL

import asyncio

api_id = 123456      # 👉 তোমার API ID
api_hash = "your_api_hash_here"
bot_token = "your_bot_token_here"

app = Client("my_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)
pytgcalls = PyTgCalls(app)

ydl_opts = {"format": "bestaudio"}

@app.on_message(filters.command("play") & filters.chat_type.groups)
async def play(_, message):
    if len(message.command) < 2:
        await message.reply("Give a YouTube URL or search query!")
        return

    query = message.text.split(None, 1)[1]
    msg = await message.reply("Downloading audio...")

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        url = info["url"]

    await pytgcalls.join_group_call(
        message.chat.id,
        AudioPiped(url)
    )
    await msg.edit("✅ Playing audio!")

@pytgcalls.on_stream_end()
async def on_stream_end(client, update: StreamAudioEnded):
    await pytgcalls.leave_group_call(update.chat_id)

pytgcalls.start()
app.run()
