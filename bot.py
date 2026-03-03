import os
import asyncio
import aiosqlite

print("BOOT: script started")
print("BOOT VERSION: inbox-v1")

from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    MessageOriginChannel,
)

# === НАСТРОЙКИ ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 289106346
CHANNEL_ID = -1002581517107
DB_PATH = "inbox.db"

# === ИНИЦИАЛИЗАЦИЯ ===
bot = Bot(BOT_TOKEN)
dp = Dispatcher()


# === КНОПКА ОТВЕТА ===
def reply_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="↩️ Ответить",
                    callback_data=f"reply:{ticket_id}",
                )
            ]
        ]
    )


# === БАЗА ДАННЫХ ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DROP TABLE IF EXISTS tickets")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_reply_state (
                admin_id INTEGER PRIMARY KEY,
                ticket_id INTEGER
            )
            """
        )
        await db.commit()


async def create_ticket(user_id: int, username: str, full_name: str, text: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO tickets(user_id, username, full_name, text) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, text),
        )
        await db.commit()
        return cur.lastrowid


async def set_admin_reply_target(ticket_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO admin_reply_state(admin_id, ticket_id)
            VALUES (?, ?)
            ON CONFLICT(admin_id)
            DO UPDATE SET ticket_id=excluded.ticket_id
            """,
            (ADMIN_ID, ticket_id),
        )
        await db.commit()


async def get_admin_reply_target():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT ticket_id FROM admin_reply_state WHERE admin_id=?",
            (ADMIN_ID,),
        )
        row = await cur.fetchone()
        return row[0] if row else None


async def clear_admin_reply_target():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "DELETE FROM admin_reply_state WHERE admin_id=?",
            (ADMIN_ID,),
        )
        await db.commit()


async def get_ticket_user(ticket_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id FROM tickets WHERE id=?",
            (ticket_id,),
        )
        row = await cur.fetchone()
        return row[0] if row else None


# === ПРИЁМ АНОНИМОК ===
@dp.message(F.from_user.id != ADMIN_ID)
async def inbox(message: Message):
    username = message.from_user.username or ""
    full_name = message.from_user.full_name or ""
    text_content = message.text or message.caption or ""

    ticket_id = await create_ticket(message.from_user.id, username, full_name, text_content)

    await message.answer("Принято 🖤 Ответ будет в канале @hexandhush.")

    header = f"📩 Анонимные вопросы #{ticket_id}"

    if message.text:
        await bot.send_message(
            ADMIN_ID,
            f"{header}\n\n{message.text}",
            reply_markup=reply_kb(ticket_id),
        )
        return

    if message.photo:
        file_id = message.photo[-1].file_id
        caption = message.caption or ""
        await bot.send_photo(
            ADMIN_ID,
            file_id,
            caption=f"{header}\n\n{caption}".strip(),
            reply_markup=reply_kb(ticket_id),
        )
        return

    if message.video:
        file_id = message.video.file_id
        caption = message.caption or ""
        await bot.send_video(
            ADMIN_ID,
            file_id,
            caption=f"{header}\n\n{caption}".strip(),
            reply_markup=reply_kb(ticket_id),
        )
        return

    await bot.send_message(
        ADMIN_ID,
        f"{header}\n\n(Неподдерживаемый тип сообщения)",
        reply_markup=reply_kb(ticket_id),
    )


# === КНОПКА "ОТВЕТИТЬ" ===
@dp.callback_query(F.data.startswith("reply:"))
async def on_reply_click(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Не для тебя.", show_alert=True)
        return

    ticket_id = int(call.data.split(":")[1])
    await set_admin_reply_target(ticket_id)

    await call.answer("Режим ответа включён")
    await bot.send_message(
        ADMIN_ID,
        f"✍️ Ответ на анонимку #{ticket_id}\n"
        f"Отправь следующее сообщение.\n"
        f"Отмена: /cancel",
    )


# === ОТМЕНА ОТВЕТА ===
@dp.message(F.from_user.id == ADMIN_ID, F.text == "/cancel")
async def cancel(message: Message):
    await clear_admin_reply_target()
    await message.answer("Режим ответа отменён.")


# === СПИСОК ПОСЛЕДНИХ АНОНИМОК ===
@dp.message(F.from_user.id == ADMIN_ID, F.text == "/inbox")
async def admin_inbox(message: Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT id, created_at, user_id FROM tickets ORDER BY id DESC LIMIT 10"
        )
        rows = await cur.fetchall()

    if not rows:
        await message.answer("Пусто.")
        return

    text = ["📥 Последние сообщения:"]
    for tid, created_at, user_id in rows:
        text.append(f"#{tid} • {created_at} • user_id={user_id}")

    text.append("\nПосмотреть: /show <id>")
    await message.answer("\n".join(text))


# === ПРОСМОТР АНОНИМКИ ===
@dp.message(F.from_user.id == ADMIN_ID, F.text.regexp(r"^/show\s+\d+$"))
async def admin_show(message: Message):
    ticket_id = int(message.text.split()[-1])

    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT user_id, username, full_name, text FROM tickets WHERE id=?",
            (ticket_id,),
        )
        row = await cur.fetchone()

    if not row:
        await message.answer("Не найдено.")
        return

    user_id, username, full_name, text = row
    await message.answer(
        f"user_id: {user_id}\n"
        f"username: @{username if username else '-'}\n"
        f"name: {full_name if full_name else '-'}\n\n"
        f"{text or ''}"
    )


# === ОТПРАВКА ОТВЕТА АВТОРУ (админ / канал) ===
@dp.message(F.from_user.id == ADMIN_ID)
async def admin_send(message: Message):
    is_channel_post = (
        message.forward_origin
        and isinstance(message.forward_origin, MessageOriginChannel)
        and message.forward_origin.chat.id == CHANNEL_ID
    )

    ticket_id = await get_admin_reply_target()
    if not ticket_id:
        return

    user_id = await get_ticket_user(ticket_id)
    if not user_id:
        await clear_admin_reply_target()
        return

    prefix = f"↩️ Ответ на анонимку #{ticket_id}:\n\n"

    try:
        if message.text:
            await bot.send_message(user_id, prefix + message.text)

        elif message.photo:
            await bot.send_photo(
                user_id,
                message.photo[-1].file_id,
                caption=prefix + (message.caption or ""),
            )

        elif message.video:
            await bot.send_video(
                user_id,
                message.video.file_id,
                caption=prefix + (message.caption or ""),
            )

        else:
            return

        if not is_channel_post:
            await message.answer("✅ Ответ отправлен.")

    except Exception as e:
        print("SEND ERROR:", e)
        await message.answer(f"❌ Ошибка отправки: {e}")

    await clear_admin_reply_target()


# === ЗАПУСК ===
async def main():
    await init_db()
    print("BOOT: polling starting")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
