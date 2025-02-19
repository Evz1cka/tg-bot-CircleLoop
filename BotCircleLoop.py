import re
import os
import json
import shutil
import subprocess
import logging
import asyncio
import aiogram.exceptions
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.enums import ParseMode
from PIL import Image, ImageDraw
import aiofiles
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from database import init_db, add_user, get_users

FFMPEG_PATH = "ffmpeg"  # или укажи полный путь

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 📌 Путь к файлу users.json внутри папки с ботом
USERS_FILE = os.path.join(BASE_DIR, "users.json")

# ✅ Функция для загрузки списка пользователей
def load_users():
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ✅ Функция для сохранения списка пользователей
def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

class ChangeEmojiState(StatesGroup):
    waiting_for_sticker = State()
    waiting_for_new_emoji = State()

user_video_files = {}  # {user_id: file_id} - Видеофайл обычного видео
user_video_notes = {}  # {user_id: file_id} - Видеокружок

# Глобальные переменные
ast_video_file_id = None  # Для хранения последнего видео
last_received_file_id = None  # Для хранения последнего видеокружка
last_video_file_id = None  # Для хранения file_id последнего видео
last_video_sender_id = None  # Глобальная переменная для хранения ID отправителя видео

# Регулярное выражение для проверки эмодзи
EMOJI_REGEX = re.compile("[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F700-\U0001F77F"
                         "\U0001F780-\U0001F7FF\U0001F800-\U0001F8FF\U0001F900-\U0001F9FF\U0001FA00-\U0001FA6F"
                         "\U0001FA70-\U0001FAFF\U00002702-\U000027B0\U000024C2-\U0001F251]+", re.UNICODE)

# Установи свой Telegram API-токен
TOKEN = "2073282100:AAGnrJMzfUcIelhlfNRH7ZRO9S005Nd0nvU"

# Инициализация бота и диспетчера
from aiogram.client.default import DefaultBotProperties
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class ChangeEmojiState(StatesGroup):
    waiting_for_sticker = State()
    waiting_for_new_emoji = State()

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# Папка для временных файлов
TEMP_FOLDER = "temp"
os.makedirs(TEMP_FOLDER, exist_ok=True)

def create_circle_mask(mask_path):
    """Создает PNG-маску с прозрачным кругом."""
    size = (512, 512)
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, size[0], size[1]), fill=255)
    mask.save(mask_path)

@dp.message(Command("start"))
async def handle_start_command(message: types.Message):
    """Добавляет пользователя в базу (тихо) и показывает меню"""
    user_id = message.from_user.id
    user_name = message.from_user.full_name
    user_username = f"@{message.from_user.username}" if message.from_user.username else "—"

    await init_db()  # Создаём таблицу, если её нет
    users = await get_users()  # Загружаем всех пользователей

    # ✅ Добавляем пользователя, если его нет, без сообщений
    if not any(user[0] == user_id for user in users):
        await add_user(user_id, user_name, user_username)
        users = await get_users()  # Обновляем список после добавления

    logging.info(f"В базе уже {len(users)} пользователей")

    """Отправляет меню выбора пользователю при старте бота."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎥 Преобразовать видео в видеокружок", callback_data="convert_to_video_note")],
        [InlineKeyboardButton(text="🏷️ Преобразовать видеокружок в стикер", callback_data="convert_to_sticker")]
    ])
    await message.answer(
    "Привет! 🎉\n"
    "Я бот, который умеет преобразовывать видео в видеокружок!\n"
    "(Видеокружок ≤60 секунд)\n"
    "А ещё, я умею делать из ваших кружков стикеры!\n"
    "(Стикер ≤3 секунд)\n\n"
    "Выберите, что хотите сделать:", reply_markup=keyboard
)

@dp.callback_query(F.data == "convert_to_video_note")
async def handle_convert_to_video_note(call: CallbackQuery):
    """Обрабатывает выбор 'Преобразовать видео в видеокружок 🎥'"""
    await call.message.edit_text(
        "📌 Отправьте мне обычное видео, и я преобразую его в видеокружок! (до 20мб)",
        reply_markup=None
    )

@dp.callback_query(F.data == "convert_to_sticker")
async def handle_convert_to_sticker(call: CallbackQuery):
    """Обрабатывает выбор 'Преобразовать видеокружок в видеостикер 🏷️'"""
    await call.message.edit_text(
        "📌 Отправьте мне видеокружок, и я преобразую его в видеостикер!",
        reply_markup=None
    )

@dp.callback_query(F.data == "convert_video")
async def handle_convert_video_to_sticker(call: CallbackQuery):
    """Обрабатывает нажатие на кнопку 'Сделать из него стикер'."""
    user_id = call.from_user.id  # Получаем ID пользователя

    # Проверяем, есть ли у пользователя сохраненный file_id
    if user_id not in user_video_notes:
        await call.message.answer("❌ Ошибка: Видеокружок не найден. Отправьте его снова.")
        return

    file_id = user_video_notes[user_id]  # Достаем file_id конкретного пользователя

    input_path = os.path.join(TEMP_FOLDER, f"input_{file_id}.mp4")
    output_path = os.path.join(TEMP_FOLDER, f"output_{file_id}.webm")

    file_info = await bot.get_file(file_id)
    await bot.download_file(file_info.file_path, input_path)

    mask_path = os.path.join(TEMP_FOLDER, "circle_mask.png")
    if not os.path.exists(mask_path):
        create_circle_mask(mask_path)

    # Конвертация видеокружка в стикер с наложением маски
    convert_command = [
        FFMPEG_PATH, "-y", "-i", input_path, "-i", mask_path,
        "-filter_complex", "[0:v]scale=512:512,format=rgba[vid];[1:v]format=rgba[mask];[vid][mask]alphamerge",
        "-c:v", "libvpx-vp9", "-crf", "18", "-b:v", "500K", "-r", "30", "-an",
        output_path
    ]
    subprocess.run(convert_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not os.path.exists(output_path):
        await call.message.answer("❌ Ошибка при обработке видео в стикер.")
        return

    bot_info = await bot.me()
    pack_name = f"sticker_pack_{user_id}_by_{bot_info.username}"

    send_sticker = False
    pack_exists = False

    try:
        await bot.get_sticker_set(name=pack_name)
        pack_exists = True
        logging.info(f"✅ Найден стикерпак: {pack_name}")
    except aiogram.exceptions.TelegramBadRequest:
        logging.info(f"⚠️ Стикерпак {pack_name} не найден, будет создан новый.")

    sticker_file = FSInputFile(output_path)

    if not pack_exists:
        logging.info("🆕 Создание нового стикер-пака...")
        pack_url = await create_sticker_pack(user_id=user_id, sticker_file=output_path)
        if pack_url:
            text = f"✅ Ваш стикер добавлен в новый стикер-пак! 🎉\n\n[Добавить набор]({pack_url})"
        else:
            text = "❌ Ошибка при создании стикер-пака."
    else:
        logging.info("➕ Добавление стикера в существующий пак...")
        response = await add_sticker_to_pack(user_id, output_path)
        if response:
            text = "✅ Стикер добавлен в ваш набор!"
            send_sticker = True
        else:
            text = "❌ Ошибка при добавлении стикера в существующий пак."

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Сменить эмодзи", callback_data=f"change_emoji_{file_id[:50]}")],
        [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
    ])

    await call.message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

    if send_sticker:
        await bot.send_sticker(user_id, sticker_file)

    os.remove(input_path)
    os.remove(output_path)

@dp.callback_query(F.data == "back_to_menu")
async def handle_back_to_menu(call: CallbackQuery):
    """Обрабатывает нажатие на кнопку 'Вернуться в меню'."""
    await handle_start_command(call.message)

@dp.message(F.video)
async def handle_video_to_video_note(message: types.Message):
    """Конвертирует обычное видео в видеокружок."""
    global last_video_file_id, last_video_sender_id

    logging.info(f"Получено видео от {message.from_user.full_name} (ID: {message.from_user.id})")
    await message.answer("Обработка видео началась... ⏳ Пожалуйста, подождите.")

    file_id = message.video.file_id
    last_video_file_id = file_id  
    last_video_sender_id = message.from_user.id  

    # Проверяем размер файла
    file_size = message.video.file_size  
    max_size = 20 * 1024 * 1024  # 20MB
    
    if file_size > max_size:
        await message.answer("❌ Ошибка: Файл слишком большой! 📁\nОтправьте видео размером **не более 20 MB**.")
        return

    file_info = await bot.get_file(file_id)
    input_path = os.path.join(TEMP_FOLDER, f"input_{file_id}.mp4")
    output_path = os.path.join(TEMP_FOLDER, f"output_{file_id}.mp4")

    await bot.download_file(file_info.file_path, input_path)

    convert_command = [
        FFMPEG_PATH, "-y", "-i", input_path,
        "-vf", "crop=min(in_w\\,in_h):min(in_w\\,in_h),scale=512:512",
        "-c:v", "libx264", "-preset", "veryslow", "-crf", "15", "-b:v", "800K",
        "-r", "30", "-c:a", "aac", "-b:a", "192k",
        output_path
    ]


    subprocess.run(convert_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Отправляем видеокружок и сохраняем file_id в user_video_notes
    sent_video = await message.answer_video_note(FSInputFile(output_path))
    user_video_notes[message.from_user.id] = sent_video.video_note.file_id  # <-- Важно!

    video_duration = message.video.duration  
    if video_duration > 3:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✂️ Укоротить и сделать стикер", callback_data="trim_and_convert_video")],
            [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
        ])
        await message.answer("⚠️ Ваше видео длиннее 3 секунд. Я могу укоротить его и сделать стикер.", reply_markup=keyboard)
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏷️ Сделать из него стикер", callback_data="convert_video")],
            [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
        ])
        await message.answer("✅ Видеокружок готов! Хотите сделать из него стикер?", reply_markup=keyboard)

    os.remove(input_path)
    os.remove(output_path)

@dp.message(F.video_note)
async def handle_video_note_to_sticker(message: types.Message):
    """Конвертирует видеокружок в стикер, проверяя длину перед обработкой."""
    logging.info(f"Получен видеокружок от {message.from_user.full_name} (ID: {message.from_user.id})")
    await message.answer("Обработка видеокружка началась... ⏳ Пожалуйста, подождите.")

    user_id = message.from_user.id  # Получаем user_id
    file_id = message.video_note.file_id

    # Сохраняем file_id видеокружка для конкретного пользователя
    user_video_notes[user_id] = file_id  # <-- Исправлено!

    if message.video_note.duration > 3:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Укоротить", callback_data="trim_video")],
            [InlineKeyboardButton(text="Отправлю ещё раз", callback_data="trim_video_cancel")]
        ])
        await message.answer("⚠️ Ваш видеокружок длиннее 3 секунд. Укоротить его или загрузить новый?", reply_markup=keyboard)
        return

    await process_video_note(message, file_id=file_id, user_id=user_id)

@dp.callback_query(F.data == "trim_and_convert_video")
async def handle_trim_and_convert_callback(call: CallbackQuery):
    """Обрезает видеокружок до 3 секунд и сразу делает из него стикер."""
    user_id = call.from_user.id  # Получаем ID пользователя

    # Проверяем, есть ли у пользователя сохраненный file_id
    if user_id not in user_video_notes:
        await call.message.answer("❌ Ошибка: Не найден видеокружок для обработки. Отправьте его снова.")
        return

    file_id = user_video_notes[user_id]  # Достаем file_id конкретного пользователя

    input_path = os.path.join(TEMP_FOLDER, f"input_{file_id}.mp4")
    trimmed_path = os.path.join(TEMP_FOLDER, f"trimmed_{file_id}.mp4")

    file_info = await bot.get_file(file_id)
    await bot.download_file(file_info.file_path, input_path)

    # Обрезаем видео до 3 секунд
    trim_command = [
        "ffmpeg", "-y", "-i", input_path, "-t", "3",
        "-c:v", "libx264", "-preset", "ultrafast", "-an", trimmed_path
    ]
    subprocess.run(trim_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    shutil.move(trimmed_path, input_path)

    # Отправляем укороченное видео и обновляем file_id
    trimmed_video = FSInputFile(input_path)
    sent_video = await bot.send_video_note(call.message.chat.id, trimmed_video)

    # Сохраняем обновленный file_id для пользователя
    user_video_notes[user_id] = sent_video.video_note.file_id

    # Теперь запускаем обработку уже обрезанного видео в стикер
    await process_video_note(call.message, file_id=user_video_notes[user_id], user_id=user_id)

@dp.callback_query(F.data == "trim_video")
async def handle_trim_callback(call: CallbackQuery):
    """Обрезает видеокружок до 3 секунд и запускает обработку в стикер."""
    user_id = call.from_user.id  # Получаем ID пользователя

    # Проверяем, есть ли у пользователя сохраненный file_id
    if user_id not in user_video_notes:
        await call.message.answer("❌ Ошибка: Не найден видеокружок для обрезки. Отправьте его снова.")
        return

    file_id = user_video_notes[user_id]  # Достаем file_id конкретного пользователя

    input_path = os.path.join(TEMP_FOLDER, f"input_{file_id}.mp4")
    trimmed_path = os.path.join(TEMP_FOLDER, f"trimmed_{file_id}.mp4")

    file_info = await bot.get_file(file_id)
    await bot.download_file(file_info.file_path, input_path)

    # Обрезаем видео до 3 секунд
    trim_command = [
        "ffmpeg", "-y", "-i", input_path, "-t", "3",
        "-c:v", "libx264", "-preset", "ultrafast", "-an", trimmed_path
    ]
    subprocess.run(trim_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    shutil.move(trimmed_path, input_path)

    # Отправляем укороченное видео и обновляем file_id
    trimmed_video = FSInputFile(input_path)
    sent_video = await bot.send_video_note(call.message.chat.id, trimmed_video)

    # Сохраняем обновленный file_id для пользователя
    user_video_notes[user_id] = sent_video.video_note.file_id

    # Теперь запускаем обработку уже обрезанного видео
    await process_video_note(call.message, file_id=user_video_notes[user_id], user_id=user_id)

@dp.callback_query(F.data.startswith("change_emoji_"))
async def handle_change_emoji_button(call: CallbackQuery, state: FSMContext):
    """Запускает процесс смены эмодзи после добавления стикера."""
    user_id = int(call.data.replace("change_emoji_", ""))  # Получаем user_id из callback_data

    # Проверяем, есть ли `file_id` у пользователя
    if user_id not in user_video_notes:
        await call.message.answer("❌ Ошибка: Не найден стикер для смены эмодзи. Попробуйте снова.")
        return

    sticker_file_id = user_video_notes[user_id]  # Берём `file_id` из user_video_notes

    # Логируем для проверки
    logging.info(f"Смена эмодзи: user_id={user_id}, file_id={sticker_file_id}")

    # Сохраняем `file_id` в state
    await state.update_data(sticker_file_id=sticker_file_id)
    await state.set_state(ChangeEmojiState.waiting_for_new_emoji)

    await call.message.answer("🔤 Отправьте новый эмодзи для этого стикера.")

async def create_sticker_pack(user_id: int, sticker_file: str):
    """Создаёт новый стикер-пак для пользователя"""
    bot_info = await bot.me()

    if user_id == bot_info.id:
        print("❌ Ошибка: user_id совпадает с bot.id! Отмена создания.")
        return None  # Не создаём стикерпак, если ID бота
    
    pack_name = f"sticker_pack_{user_id}_by_{bot_info.username}"
    pack_title = f"Стикеры от @{bot_info.username}"

    sticker = FSInputFile(sticker_file)  # Загружаем файл

    response = await bot.create_new_sticker_set(
        user_id=user_id,
        name=pack_name,
        title=pack_title,
        sticker_format="video",
        stickers=[
            {
                "sticker": sticker,
                "emoji_list": ["🎥"],
                "format": "video"  # ОБЯЗАТЕЛЬНО ДОБАВЛЯЕМ format
            }
        ]
    )

    if response:
        return f"https://t.me/addstickers/{pack_name}"
    
    return None

async def add_sticker_to_pack(user_id: int, sticker_file: str):
    """Добавляет новый стикер в уже существующий стикер-пак"""
    bot_info = await bot.me()
    pack_name = f"sticker_pack_{user_id}_by_{bot_info.username}"

    # Получаем список стикеров из набора
    try:
        sticker_set = await bot.get_sticker_set(name=pack_name)
        sticker_file_ids = [sticker.file_id for sticker in sticker_set.stickers]

        # Если стикер уже в наборе, не добавляем его
        if sticker_file in sticker_file_ids:
            logging.info(f"⚠️ Стикер уже есть в наборе {pack_name}. Пропускаем добавление.")
            return "⚠️ Стикер уже есть в вашем наборе!"
    except aiogram.exceptions.TelegramBadRequest:
        pass  # Если набора еще нет, продолжаем создание

    # Загружаем файл
    if not os.path.exists(sticker_file):  
        file_info = await bot.get_file(sticker_file)
        sticker_file_path = os.path.join(TEMP_FOLDER, f"sticker_{user_id}.webm")
        await bot.download_file(file_info.file_path, sticker_file_path)
    else:
        sticker_file_path = sticker_file

    async with aiofiles.open(sticker_file_path, "rb") as f:
        sticker = FSInputFile(sticker_file_path)

    try:
        response = await bot.add_sticker_to_set(
            user_id=user_id,
            name=pack_name,
            sticker={"sticker": sticker, "format": "video", "emoji_list": ["🎥"]}
        )
        return response
    except aiogram.exceptions.TelegramBadRequest as e:
        await bot.send_message(user_id, f"❌ Ошибка при добавлении стикера: {e}")
        return None

async def process_video_note(message: types.Message, file_id: str = None, user_id: int = None):
    """Обрабатывает видеокружок и конвертирует его в видеостикер."""
    
    if user_id is None:
        await message.answer("❌ Ошибка: Не удалось определить пользователя.")
        return

    if file_id is None:
        if user_id in user_video_notes:
            file_id = user_video_notes[user_id]
        else:
            await message.answer("❌ Ошибка: отсутствует видеокружок для обработки. Отправьте его снова.")
            return
    
    input_path = os.path.join(TEMP_FOLDER, f"input_{file_id}.mp4")
    output_path = os.path.join(TEMP_FOLDER, f"output_{file_id}.webm")

    file_info = await bot.get_file(file_id)
    await bot.download_file(file_info.file_path, input_path)

    mask_path = os.path.join(TEMP_FOLDER, "circle_mask.png")
    if not os.path.exists(mask_path):
        create_circle_mask(mask_path)

    convert_command = [
        FFMPEG_PATH, "-y", "-i", input_path, "-i", mask_path,
        "-filter_complex", "[0:v]scale=512:512,format=rgba[vid];[1:v]format=rgba[mask];[vid][mask]alphamerge",
        "-c:v", "libvpx-vp9", "-crf", "18", "-b:v", "500K", "-r", "30", "-an",
        output_path
    ]
    subprocess.run(convert_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if not os.path.exists(output_path):
        await message.answer("❌ Ошибка при обработке видео в стикер.")
        return

    bot_info = await bot.me()
    logging.info(f"🆔 user_id: {user_id}, bot_id: {bot_info.id}")

    if user_id == bot_info.id:
        await message.answer("❌ Ошибка: Бот не может создать стикерпак сам для себя.")
        return

    pack_name = f"sticker_pack_{user_id}_by_{bot_info.username}"

    send_sticker = False
    pack_exists = False

    try:
        await bot.get_sticker_set(name=pack_name)
        pack_exists = True
        logging.info(f"✅ Найден стикерпак: {pack_name}")
    except aiogram.exceptions.TelegramBadRequest:
        logging.info(f"⚠️ Стикерпак {pack_name} не найден, будет создан новый.")

    sticker_file = FSInputFile(output_path)

    if not pack_exists:
        logging.info("🆕 Создание нового стикер-пака...")
        pack_url = await create_sticker_pack(user_id=user_id, sticker_file=output_path)
        if pack_url:
            text = f"✅ Ваш стикер добавлен в новый стикер-пак! 🎉\n\n[Добавить набор]({pack_url})"
        else:
            text = "❌ Ошибка при создании стикер-пака."
    else:
        logging.info("➕ Добавление стикера в существующий пак...")
        response = await add_sticker_to_pack(user_id, output_path)
        if response:
            text = "✅ Стикер добавлен в ваш набор!"
            send_sticker = True
        else:
            text = "❌ Ошибка при добавлении стикера в существующий пак."
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="🔄 Сменить эмодзи", callback_data=f"change_emoji_{user_id}")],  # Передаём user_id, а не file_id
    [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
    ])

    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

    if send_sticker:
    # Отправляем стикер пользователю и получаем его настоящий file_id
        sticker_message = await bot.send_sticker(user_id, sticker_file)
        sticker_real_file_id = sticker_message.sticker.file_id  # Настоящий file_id

    # Логируем, чтобы убедиться, что сохраняем правильный идентификатор
        logging.info(f"Сохранён правильный file_id стикера: {sticker_real_file_id}")

    # Сохраняем правильный file_id в user_video_notes
        user_video_notes[user_id] = sticker_real_file_id

    os.remove(input_path)
    os.remove(output_path)

@dp.callback_query(F.data == "trim_video_cancel")
async def handle_cancel_callback(call: CallbackQuery):
    await call.message.edit_text("Хорошо! Отправьте новый видеокружок до 3 секунд.")

@dp.message(Command("cancel")) 
async def handle_cancel_command(message: types.Message):
    """Отменяет текущее действие и сбрасывает состояние бота."""
    global last_received_file_id
    last_received_file_id = None  # Очищаем сохранённый файл, если был

    await message.answer("✅ Действие отменено. Вы можете выбрать новую команду, отправив /start.")

@dp.message(Command("feedback"))
async def handle_feedback_command(message: types.Message):
    """Отправляет пользователю контактные данные для связи."""
    await message.answer(
        "📩 Обратная связь\n\n"
        "Если у вас есть вопросы или предложения, свяжитесь со мной:\n"
        "📱 Telegram: @evgeniibelov\n"
        "🌍 Канал: https://t.me/Evz1cka\n\n"
        "Буду рад вашим сообщениям! 😊"
    )

@dp.message(Command("mypack"))
async def handle_mypack_command(message: types.Message):
    """Отправляет пользователю список его стикер-паков."""
    bot_info = await bot.me()
    pack_name = f"sticker_pack_{message.from_user.id}_by_{bot_info.username}"

    try:
        sticker_set = await bot.get_sticker_set(name=pack_name)
        text = f"🎨 Ваши стикеры: [{sticker_set.title}](https://t.me/addstickers/{pack_name})"
    except aiogram.exceptions.TelegramBadRequest:
        text = "⚠️ У вас пока нет созданного стикер-пака. Отправьте видеокружок, и я сделаю первый стикер!"

    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("changeemojis"))
async def handle_change_emojis_command(message: types.Message, state: FSMContext):
    """Начинает процесс замены эмодзи у стикера."""
    await state.set_state(ChangeEmojiState.waiting_for_sticker)
    await message.answer("🎭 Отправьте стикер из вашего набора, для которого хотите сменить эмодзи.")

@dp.message(F.sticker, ChangeEmojiState.waiting_for_sticker)
async def receive_sticker(message: types.Message, state: FSMContext):
    """Получает стикер от пользователя и запрашивает новый эмодзи."""
    sticker_file_id = message.sticker.file_id  # Используем `file_id`, а не `file_unique_id`

    await state.update_data(sticker_file_id=sticker_file_id)
    await state.set_state(ChangeEmojiState.waiting_for_new_emoji)

    await message.answer("🔤 Теперь отправьте новый эмодзи, который хотите использовать.")

@dp.message(ChangeEmojiState.waiting_for_new_emoji)
async def receive_new_emoji(message: types.Message, state: FSMContext):
    """Сохраняет новый эмодзи и меняет его у стикера."""
    user_data = await state.get_data()
    user_id = message.from_user.id  # Получаем ID пользователя
    new_emoji = message.text.strip()

    if user_id not in user_video_notes:
        await message.answer("❌ Ошибка: Стикер не найден. Отправьте его снова.")
        return

    # Получаем правильный `file_id` из стикер-пака
    bot_info = await bot.me()
    pack_name = f"sticker_pack_{user_id}_by_{bot_info.username}"

    try:
        sticker_set = await bot.get_sticker_set(name=pack_name)
        sticker_file_id = sticker_set.stickers[-1].file_id  # Берём последний стикер
    except aiogram.exceptions.TelegramBadRequest:
        await message.answer("❌ Ошибка: Не удалось найти стикер в вашем наборе.")
        return

    # Логируем `file_id`, чтобы убедиться, что передаётся правильное значение
    logging.info(f"Передаю правильный file_id в set_sticker_emoji_list: {sticker_file_id}")

    # Проверяем, содержит ли сообщение только валидные эмодзи
    if not EMOJI_REGEX.fullmatch(new_emoji):
        await message.answer("⚠️ Ошибка: Введите **только** корректные эмодзи (не текст, не символы, а эмодзи)!")
        return

    try:
        response = await bot.set_sticker_emoji_list(sticker=sticker_file_id, emoji_list=[new_emoji])
        if response:
            await message.answer(f"✅ Эмодзи успешно изменены на {new_emoji}!")
        else:
            await message.answer("❌ Ошибка при смене эмодзи.")
    except aiogram.exceptions.TelegramBadRequest as e:
        await message.answer(f"❌ Ошибка: {e}")

    await state.clear()

@dp.message(Command("broadcast"))
async def send_broadcast(message: types.Message):
    """Админ отправляет рассылку всем пользователям."""
    admin_id = 987927261  # Заменить на свой user_id
    if message.from_user.id != admin_id:
        await message.answer("❌ У вас нет прав на отправку рассылки.")
        return

    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("⚠️ Введите текст рассылки после команды `/broadcast`.")
        return

    users = load_users()
    success_count = 0
    fail_count = 0

    for user in users:  # Здесь user - это словарь, надо брать user['id']
        try:
            await bot.send_message(user['id'], text)  # ✅ Передаём user['id'], а не весь user
            success_count += 1
        except aiogram.exceptions.TelegramForbiddenError:
            logging.warning(f"Пользователь {user['id']} ({user['name']}) заблокировал бота.")
            fail_count += 1
        except Exception as e:
            logging.error(f"Ошибка при отправке пользователю {user}: {e}")
            fail_count += 1

    await message.answer(f"✅ Сообщение отправлено {success_count} пользователям.\n⚠️ Ошибки у {fail_count} пользователей.")

@dp.message(Command("users"))
async def show_users(message: types.Message):
    """Показывает список пользователей администратору."""
    admin_id = 987927261  # 🔹 Заменить на свой user_id
    if message.from_user.id != admin_id:
        await message.answer("❌ У вас нет доступа к этому списку.")
        return

    users = load_users()
    if not users:
        await message.answer("⚠️ В базе пока нет пользователей.")
        return

    user_list = "\n".join([
        f"🆔 {user['id']} | 👤 {user['name']} | {user['username']}" for user in users
    ])
    await message.answer(f"📋 Список пользователей:\n{user_list}")

@dp.message()
async def handle_unknown_message(message: types.Message):
    """Обрабатывает неизвестные сообщения и отправляет инструкцию."""
    await message.answer(
        "⚠️ Привет, я понимаю только видео и видеокружки!\n\n"
        "📌 Выберите действие из меню или воспользуйтесь командами:\n"
        "🔹 /start – открыть меню\n"
        "🔹 /cancel – отменить действие и начать заново\n"
        "🔹 /mypack – ваши стикер-паки\n"
        "🔹 /changeemojis – сменить эмодзи у стикера (По умолчанию:🎥)\n"
        "🔹 /feedback – контакты автора бота"
    )

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
