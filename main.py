import asyncio
import logging
import os
import shutil
import yt_dlp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from config import TOKEN

# --- НОВОЕ ДЛЯ RENDER (FastAPI) ---
from fastapi import FastAPI
import uvicorn

app = FastAPI()
PORT = int(os.environ.get("PORT", 8000))

@app.get("/")
async def health_check():
    return {"status": "Бот активен", "service": "YouTube Downloader"}
# ----------------------------------

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()

DOWNLOAD_DIR = "downloads"

def cleanup_downloads():
    if os.path.exists(DOWNLOAD_DIR):
        shutil.rmtree(DOWNLOAD_DIR)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    print("--- Папка downloads очищена ---")

user_data = {}

# --- МЕХАНИКА ЗАГРУЗКИ ---
def download_media(url, mode):
    if "Аудио" in mode:
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.m4a',
        }
    else:
        ydl_opts = {
            'format': 'best[height<=480][ext=mp4]/best[ext=mp4]/best', 
            'outtmpl': f'{DOWNLOAD_DIR}/%(title)s.mp4',
        }
    
    ydl_opts.update({
        'noplaylist': True,
        'nocheckcertificate': True,
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
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
    await message.answer(f"<b>👋 Привет, {message.from_user.first_name}!</b>\nЯ — быстрый загрузчик YouTube.", parse_mode="HTML", reply_markup=get_main_menu())

@dp.message(F.text == "🆘 Помощь")
async def help_handler(message: types.Message):
    await message.answer("📖 Просто пришли ссылку, выбери формат. Лимит 50МБ.", parse_mode="HTML")

@dp.message(F.text == "🔄 Сброс")
@dp.message(F.text == "❌ Отмена")
async def reset_handler(message: types.Message):
    user_id = message.from_user.id
    if user_id in user_data: del user_data[user_id]
    await message.answer("♻️ Отменено.", parse_mode="HTML", reply_markup=get_main_menu())

@dp.message(F.text.contains("youtu"))
async def handle_link(message: types.Message):
    user_data[message.from_user.id] = message.text.strip()
    await message.answer("📥 Ссылка принята! Что качаем?", reply_markup=get_format_kb(), parse_mode="HTML")

@dp.message(F.text.in_(["🎵 Скачать Аудио", "🎬 Скачать Видео"]))
async def handle_format(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_data:
        await message.answer("❌ Сначала ссылку!", reply_markup=get_main_menu(), parse_mode="HTML")
        return

    url = user_data[user_id]
    mode = message.text
    file_path = None
    
    await message.answer("⚙️ Подготовка файла...", reply_markup=get_main_menu(), parse_mode="HTML")
    
    loop = asyncio.get_event_loop()
    try:
        file_path, info = await loop.run_in_executor(None, download_media, url, mode)
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        
        if file_size > 49.9:
            await message.answer(f"⚠️ Слишком большой ({file_size:.1f} МБ). Лимит 50.", parse_mode="HTML")
            return

        input_file = FSInputFile(file_path)
        if "Аудио" in mode:
            await message.answer_audio(audio=input_file, caption=f"🎵 {info.get('title')}", parse_mode="HTML")
        else:
            await message.answer_video(video=input_file, caption=f"🎬 {info.get('title')}", parse_mode="HTML")

    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка загрузки!")
    finally:
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
    # Запускаем бота фоновой задачей
    asyncio.create_task(run_bot())

if __name__ == "__main__":
    # Запуск веб-сервера (Render требует, чтобы порт был занят)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
