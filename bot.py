import os
import asyncio
from pyrogram import Client, filters
from pytgcalls import PyTgCalls, idle
from pytgcalls.types import Update
from pytgcalls.types.input_stream import InputStream, AudioPiped
from pytgcalls.exceptions import GroupCallNotFoundError
from yt_dlp import YoutubeDL

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING")

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
assistant = Client("assistant", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
pytgcalls = PyTgCalls(assistant)

ydl_opts = {
    'format': 'bestaudio/best',
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'quiet': True
}

os.makedirs("downloads", exist_ok=True)

async def download_song(query):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        id_ = info.get('id', "unknown_id")
        file_path = f"downloads/{id_}.webm"
        if not os.path.exists(file_path):
            ydl.download([query])
        return file_path

@bot.on_message(filters.command("start"))
async def start(_, message):
    await message.reply_text(
        "🎧 ʟᴀᴍɪʏᴀ x ᴍᴜꜱɪᴄ এ স্বাগতম!\n"
        "✅ /play [song name or YouTube link] দিয়ে voice chat এ গান চালাও!\n"
        "🎤 Voice chat আগে manually start করতে হবে।\n"
        "Enjoy your music! 💙"
    )

@bot.on_message(filters.command("play") & filters.group)
async def play(_, message):
    if len(message.command) < 2:
        await message.reply_text("Please provide a song name or URL.")
        return

    query = " ".join(message.command[1:])
    msg = await message.reply_text(f"🔍 Downloading: {query}")
    file_path = await download_song(query)
    await msg.edit_text("🎧 Checking voice chat...")

    chat_id = message.chat.id
    try:
        await pytgcalls.join_group_call(
            chat_id,
            InputStream(
                AudioPiped(file_path)
            ),
            stream_type="local_stream"
        )
        await msg.edit_text("✅ Now playing in voice chat!")
    except GroupCallNotFoundError:
        await msg.edit_text("❌ Please start a voice chat first, then use /play again.")
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")

async def main():
    await bot.start()
    await assistant.start()
    await pytgcalls.start()
    print("Bot and assistant started.")
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
