import os
import asyncio
from pyrogram import Client, filters
from pytgcalls import PyTgCalls, idle
from pytgcalls.types.input_stream import AudioPiped
from yt_dlp import YoutubeDL

API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SESSION_STRING = os.environ.get("SESSION_STRING")

bot = Client("MusicBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
assistant = Client("assistant", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

pytgcalls = PyTgCalls(assistant)

ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'noplaylist': True,
    'quiet': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0'
}

os.makedirs("downloads", exist_ok=True)

async def download_song(query):
    loop = asyncio.get_event_loop()
    file_path = await loop.run_in_executor(None, lambda: _download(query))
    return file_path

def _download(query):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=True)
        if 'entries' in info:
            info = info['entries'][0]
        id_ = info.get("id")
        ext = info.get("ext")
        return f"downloads/{id_}.{ext}"

@bot.on_message(filters.command("start"))
async def start(_, message):
    await message.reply_text(
        "🎧 স্বাগতম Shyx-style Music Bot-এ!\n\n"
        "✅ `/play [song name or url]` দিয়ে গান চালাও\n"
        "✅ Assistant কে group call-এ add করে রাখো\n\n"
        "Enjoy your music! 💙"
    )

@bot.on_message(filters.command("play") & filters.group)
async def play(_, message):
    chat_id = message.chat.id

    if len(message.command) < 2:
        await message.reply_text("🎵 দয়া করে গান এর নাম বা লিংক দাও!")
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(f"🔍 সার্চ করা হচ্ছে: `{query}`")

    try:
        file_path = await download_song(query)
    except Exception as e:
        await status.edit(f"❌ Error: {e}")
        return

    try:
        await pytgcalls.join_group_call(
            chat_id,
            AudioPiped(file_path),
        )
        await status.edit("✅ গান চলছে! 🎶")
    except Exception as e:
        await status.edit(f"❌ VC তে যোগ দিতে ব্যর্থ: {e}")

async def main():
    await bot.start()
    await assistant.start()
    await pytgcalls.start()
    print("✅ Bot & Assistant চালু হয়েছে, প্রস্তুত!")
    await idle()
    await bot.stop()
    await assistant.stop()

if __name__ == "__main__":
    asyncio.run(main())
