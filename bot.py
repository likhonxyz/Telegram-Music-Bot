from pyrogram import Client, filters
from pytgcalls import PyTgCalls
from pytgcalls.types.input_stream import AudioPiped
from pytgcalls.types.stream import StreamAudioEnded
from pytgcalls.types import Update
import yt_dlp

api_id = 1234567  # তোমার API ID
api_hash = "YOUR_API_HASH"
bot_token = "YOUR_BOT_TOKEN"

app = Client("music_bot", api_id=api_id, api_hash=api_hash, bot_token=bot_token)
pytgcalls = PyTgCalls(app)

@app.on_message(filters.command("play") & filters.group)
async def play(_, message):
    if len(message.command) < 2:
        return await message.reply_text("দয়া করে একটি ইউটিউব লিংক বা সার্চ টার্ম দিন!")

    query = message.text.split(None, 1)[1]

    # ইউটিউব থেকে ডাউনলোড
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "extract_flat": "in_playlist",
        "outtmpl": "downloads/%(id)s.%(ext)s",
        "nocheckcertificate": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        url = info["url"]

    audio = AudioPiped(url)

    await pytgcalls.join_group_call(
        message.chat.id,
        audio,
    )
    await message.reply_text("✅ গান বাজানো শুরু হয়েছে!")

@pytgcalls.on_stream_end()
async def on_stream_end(_, update: Update):
    await pytgcalls.leave_group_call(update.chat_id)

@app.on_message(filters.command("stop") & filters.group)
async def stop(_, message):
    await pytgcalls.leave_group_call(message.chat.id)
    await message.reply_text("⛔ গান বন্ধ করা হয়েছে।")

pytgcalls.start()
app.run()
