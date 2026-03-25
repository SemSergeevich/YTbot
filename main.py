import asyncio
import logging
import os
import shutil
import yt_dlp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from fastapi import FastAPI
import uvicorn

# --- КОНФИГУРАЦИЯ ---
# Берем токен из переменных окружения Render для безопасности
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "6570377786:AAEeoQ4PDNhbaoFU-2RJ8J4N64X7qHixE-Q")
PORT = int(os.environ.get("PORT", 8000))
DOWNLOAD_DIR = "downloads"

# --- ИНИЦИАЛИЗАЦИЯ ---
logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
app = FastAPI()

# --- ВЕБ-СЕРВЕР (Для Render) ---
@app.get("/")
async def health_check():
    return {"status": "Бот работает", "info": "YouTube Downloader Service"}

# --- ЛОГИКА ЗАГРУЗКИ ---
def cleanup_downloads():
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

user_data = {}

def download_media(url, mode):
    cleanup_downloads() # Чистим перед каждой загрузкой для экономии места
    
    if "Аудио" in mode:
        # m4a формат не требует ffmpeg на сервере
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.m4a',
        }
    else:
        # Ограничиваем 480p, чтобы файл точно влез в 50МБ лимит Телеграм
        ydl_opts = {
            'format': 'best[height<=480][ext=mp4]/best[ext=mp4]/best', 
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.mp4',
        }
    
ydl_opts.update({
        'noplaylist': True,
        'nocheckcertificate': True,
        'quiet': True,
        'no_warnings': True,
        # Добавляем использование OAuth
        'username': 'oauth2',
        'password': '',
    })

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info), info

# --- КЛАВИАТУРЫ ---
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🆘 Помощь"), KeyboardButton(text="🔄 Сброс")]],
        resize_keyboard=True
    )

def get_format_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎵 Скачать Аудио"), KeyboardButton(text="🎬 Скачать Видео")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

# --- ХЕНДЛЕРЫ ---
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(f"<b>👋 Привет, {message.from_user.first_name}!</b>\nПришли ссылку на YouTube.", 
                         parse_mode="HTML", reply_markup=get_main_menu())

@dp.message(F.text == "🆘 Помощь")
async def help_handler(message: types.Message):
    await message.answer("📖 Просто отправь ссылку. Лимит файла: 50 МБ.", parse_mode="HTML")

@dp.message(F.text.in_(["🔄 Сброс", "❌ Отмена"]))
async def reset_handler(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data: del user_data[user_id]
    await message.answer("♻️ Отменено.", reply_markup=get_main_menu())

@dp.message(F.text.contains("youtu"))
async def handle_link(message: types.Message):
    user_data[message.from_user.id] = message.text.strip()
    await message.answer("📥 Ссылка принята! Выберите формат:", reply_markup=get_format_kb())

@dp.message(F.text.in_(["🎵 Скачать Аудио", "🎬 Скачать Видео"]))
async def handle_format(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        await message.answer("❌ Сначала отправьте ссылку!", reply_markup=get_main_menu())
        return

    url = user_data[user_id]
    mode = message.text
    file_path = None
    
    status_msg = await message.answer("⚙️ Загрузка началась... Пожалуйста, подождите.")
    
    loop = asyncio.get_event_loop()
    try:
        file_path, info = await loop.run_in_executor(None, download_media, url, mode)
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        
        if file_size > 49.9:
            await message.answer(f"⚠️ Файл слишком большой ({file_size:.1f} МБ). Лимит 50 МБ.")
            return

        input_file = FSInputFile(file_path)
        caption = f"🎬 {info.get('title')}\n📦 {file_size:.1f} MB"
        
        if "Аудио" in mode:
            await message.answer_audio(audio=input_file, caption=caption)
        else:
            await message.answer_video(video=input_file, caption=caption)

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("❌ Произошла ошибка при загрузке.")
    finally:
        await status_msg.delete()
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if user_id in user_data: del user_data[user_id]

# --- ЗАПУСК ---
async def run_bot():
    cleanup_downloads()
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(run_bot())

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
