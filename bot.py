from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types import Update
from pytgcalls.types.input_stream import AudioPiped
from pytgcalls.types.stream import StreamAudioEnded
from yt_dlp import YoutubeDL

import asyncio

API_ID = 123456  # তোমার API_ID
API_HASH = "your_api_hash"
SESSION_STRING = "your_session_string"

app = Client(SESSION_STRING, api_id=API_ID, api_hash=API_HASH)
pytgcalls = PyTgCalls(app)

ydl_opts = {
    "format": "bestaudio",
    "outtmpl": "downloads/%(id)s.%(ext)s",
}

@pytgcalls.on_stream_end()
async def on_stream_end(client: PyTgCalls, update: Update):
    if isinstance(update, StreamAudioEnded):
        await pytgcalls.leave_group_call(update.chat_id)

@app.on_message(filters.command("play") & filters.group)
async def play(_, message):
    if len(message.command) < 2:
        await message.reply("Usage: /play <YouTube URL or query>")
        return

    query = message.text.split(None, 1)[1]
    m = await message.reply("🔎 Downloading audio...")

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=True)
        file_path = ydl.prepare_filename(info)

    await pytgcalls.join_group_call(
        message.chat.id,
        AudioPiped(file_path),
    )

    await m.edit(f"▶️ Playing: {info['title']}")

@app.on_message(filters.command("stop") & filters.group)
async def stop(_, message):
    await pytgcalls.leave_group_call(message.chat.id)
    await message.reply("⏹️ Stopped playback.")

async def main():
    await app.start()
    await pytgcalls.start()
    print("Bot is running...")
    await idle()

if __name__ == "__main__":
    from pytgcalls import idle
    asyncio.get_event_loop().run_until_complete(main())
