import aiosqlite

DB_NAME = "users.db"

async def init_db():
    """Создаёт таблицу пользователей, если её нет."""
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
    """Добавляет пользователя в базу данных."""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users (id, name, username) VALUES (?, ?, ?)", (user_id, name, username))
        await db.commit()

async def get_users():
    """Получает список всех пользователей."""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM users")
        users = await cursor.fetchall()
        return users
