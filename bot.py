import os
import telebot
import yt_dlp
from telebot import types
from telebot import apihelper
from dotenv import load_dotenv

load_dotenv()

apihelper.READ_TIMEOUT = 120
apihelper.CONNECTION_TIMEOUT = 120
BOT_TOKEN = os.environ.get('BOT_TOKEN')
bot = telebot.TeleBot(BOT_TOKEN)

main_kbd = types.ReplyKeyboardMarkup(resize_keyboard=True)
main_kbd.add(types.KeyboardButton("Create Playlist"))
main_kbd.add(types.KeyboardButton("Download Song"))

TOPIC_FILE = "topics.txt"
downloaded_files = {}  # user_id -> filepath


def save_topic(user_id, chat_id, topic_name, thread_id):
    with open(TOPIC_FILE, "a", encoding="utf-8") as f:
        # store all info separated by ::
        f.write(f"{user_id}::{chat_id}::{topic_name}::{thread_id}\n")

def read_user_topics(user_id, chat_id):
    if not os.path.exists(TOPIC_FILE):
        return []
    topics = []
    with open(TOPIC_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("::")
            if len(parts) != 4:
                continue
            u_id, c_id, name, thread_id = parts
            if u_id == str(user_id) and c_id == str(chat_id):
                topics.append({
                    "name": name,
                    "thread_id": int(thread_id)
                })
    return topics

def topic_exists(user_id, chat_id, topic_name):
    # Check if user already created this topic in this chat
    topics = read_user_topics(user_id, chat_id)
    return any(t["name"].lower() == topic_name.lower() for t in topics)


@bot.message_handler(commands=["start"])
def start_cmd(msg):
    bot.send_message(
        msg.chat.id,
        "Welcome! Tap Create Playlist to add a new topic in the music group.",
        reply_markup=main_kbd
    )

@bot.message_handler(func=lambda m: m.text == "Create Playlist")
def ask_name(msg):
    sent = bot.reply_to(msg, "Great! Send me the playlist name:")
    bot.register_next_step_handler(sent, create_topic)

@bot.message_handler(func=lambda m: m.text == "Download Song")
def ask_url(msg):
    sent = bot.reply_to(msg, "Send me the song's YouTube link:")
    bot.register_next_step_handler(sent, download_song)

@bot.callback_query_handler(func=lambda call: call.data.startswith("send:"))
def send_to_playlist(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    selected_name = call.data.split(":", 1)[1]

    filename = downloaded_files.pop(user_id, None)
    if not filename or not os.path.exists(filename):
        bot.send_message(chat_id, "❌ File not found or expired, please try downloading again.")
        return

    # Get the saved topic's thread_id for this user/chat
    topics = read_user_topics(user_id, chat_id)
    topic = next((t for t in topics if t["name"].lower() == selected_name.lower()), None)
    if not topic:
        bot.send_message(chat_id, "❌ Playlist not found. Please create it first.")
        os.remove(filename)
        return

    try:
        with open(filename, 'rb') as audio:
            bot.send_audio(
                chat_id,
                audio,
                title=os.path.basename(filename),
                message_thread_id=topic["thread_id"]
            )
        bot.send_message(chat_id, f"✅ Song sent to playlist: {selected_name}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to send song: {str(e)}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

def create_topic(msg):
    playlist_name = msg.text.strip()
    chat_id = msg.chat.id
    user_id = msg.from_user.id

    if topic_exists(user_id, chat_id, playlist_name):
        bot.send_message(chat_id, f"You already created the playlist '{playlist_name}'")
        return

    try:
        # Create forum topic - this returns the created topic object with thread_id
        topic_obj = bot.create_forum_topic(chat_id=chat_id, name=playlist_name)
        thread_id = topic_obj.message_thread_id

        save_topic(user_id, chat_id, playlist_name, thread_id)
        bot.send_message(chat_id, f"✅ Playlist created: {playlist_name}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to create playlist: {str(e)}")

def download_song(msg):
    url = msg.text.strip()
    chat_id = msg.chat.id
    user_id = msg.from_user.id

    bot.send_message(chat_id, "🎶 Downloading song, please wait...")

    try:
        output_dir = "downloads"
        os.makedirs(output_dir, exist_ok=True)
        output_template = os.path.join(output_dir, "%(title)s.%(ext)s")

        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }],
            'quiet': True,
            'socket_timeout': 120,
            'retries': 10,
            'max_filesize': 49 * 1024 * 1024,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            if not filename.endswith('.mp3'):
                filename = os.path.splitext(filename)[0] + '.mp3'

        file_size_mb = os.path.getsize(filename) / (1024 * 1024)
        print(f"Downloaded file: {filename} ({file_size_mb:.2f} MB)")

        if file_size_mb > 49:
            bot.send_message(chat_id, "❌ Song is too large to send on Telegram (limit 50MB).")
            os.remove(filename)
            return

        # Save the downloaded file path temporarily for the user
        downloaded_files[user_id] = filename

        # Get user's playlists for this chat
        topics = read_user_topics(user_id, chat_id)
        if not topics:
            bot.send_message(chat_id, "❌ You have no playlists. Create one first with 'Create Playlist'.")
            os.remove(filename)
            downloaded_files.pop(user_id, None)
            return

        kb = types.InlineKeyboardMarkup()
        for t in topics:
            kb.add(types.InlineKeyboardButton(t["name"], callback_data=f"send:{t['name']}"))

        bot.send_message(chat_id, "✅ Song downloaded! Choose which playlist to send it to:", reply_markup=kb)

    except Exception as e:
        bot.send_message(chat_id, f"❌ Failed to download song: {str(e)}")

bot.infinity_polling()
