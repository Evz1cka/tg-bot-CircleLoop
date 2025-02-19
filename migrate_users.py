import asyncio
import json
import os
import aiosqlite

DB_NAME = "users.db"
USERS_FILE = "users.json"

async def init_db():
    """Создаёт таблицу пользователей, если её нет"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                name TEXT,
                username TEXT
            )
        """)
        await db.commit()

async def add_user(user_id: int, name: str, username: str):
    """Добавляет пользователя в базу, избегая дублирования"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (id, name, username) VALUES (?, ?, ?)
        """, (user_id, name, username))
        await db.commit()

async def migrate_users():
    """Перенос пользователей из users.json в базу данных"""
    if not os.path.exists(USERS_FILE):
        print("⚠️ Файл users.json не найден!")
        return

    with open(USERS_FILE, "r", encoding="utf-8") as f:
        try:
            users = json.load(f)
        except json.JSONDecodeError:
            print("❌ Ошибка: Некорректный формат JSON!")
            return

    if not isinstance(users, list):
        print("❌ Ошибка: users.json должен содержать список пользователей!")
        return

    await init_db()  # Убеждаемся, что таблица есть

    count = 0
    for user in users:
        if isinstance(user, dict) and "id" in user and "name" in user and "username" in user:
            await add_user(user["id"], user["name"], user["username"])
            count += 1
        else:
            print(f"⚠️ Пропущена некорректная запись: {user}")

    print(f"✅ Успешно перенесено {count} пользователей в базу!")

# Запускаем миграцию
asyncio.run(migrate_users())
