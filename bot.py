import os
import asyncio
from pyrogram import Client, filters
from yt_dlp import YoutubeDL

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
SESSION_STRING = os.getenv("SESSION_STRING")

bot = Client("bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
assistant = Client(name="assistant", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

ydl_opts = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'extractaudio': True,
    'audioformat': "mp3",
    'outtmpl': 'downloads/%(id)s.%(ext)s',
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'restrictfilenames': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0'
}

os.makedirs("downloads", exist_ok=True)

async def download_song(query):
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(query, download=False)
        if 'entries' in info:
            info = info['entries'][0]
        id_ = info.get('id', "unknown_id")
        file_path = f"downloads/{id_}.mp3"
        if not os.path.exists(file_path):
            ydl.download([query])
        return file_path

@bot.on_message(filters.command("start"))
async def start(_, message):
    await message.reply_text(
        "🎧 ʟᴀᴍɪʏᴀ x ᴍᴜꜱɪᴄ এ স্বাগতম!\n"
        "✅ /play [song name] লিখে গান চালাও\n"
        "Enjoy your music! 💙"
    )

@bot.on_message(filters.command("play") & (filters.private | filters.group))
async def play(_, message):
    if len(message.command) < 2:
        await message.reply_text("Please provide a song name or URL.")
        return
    query = " ".join(message.command[1:])
    await message.reply_text(f"🔍 Searching for: {query}")
    file_path = await download_song(query)
    await message.reply_audio(audio=file_path)

async def main():
    await bot.start()
    await assistant.start()
    print("Bot and assistant started.")
    await bot.idle()

if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
    except RuntimeError as e:
        if str(e) == "This event loop is already running":
            print("Event loop already running. Using alternative method.")
            import nest_asyncio
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())
        else:
            raise
