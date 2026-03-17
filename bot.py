import asyncio
import time
import aiosqlite
from aiogram.types import FSInputFile
import base64
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from openai import OpenAI

# ================== НАСТРОЙКИ ==================

TELEGRAM_TOKEN = "8289787557:AAHMIJ0bJJC9gBE84tXQFjKixgOk6WAVXmI"
OPENROUTER_API_KEY = "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"

ADMIN_IDS = [5080211871, 7874808674]
DB = "bot.db"

# ================== AI ==================

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()

# ================== FSM ==================

class ActivateState(StatesGroup):
    waiting_token = State()

class AdminState(StatesGroup):
    waiting_token = State()

# ================== БАЗА ==================

async def init_db():
    async with aiosqlite.connect(DB) as db:

        await db.execute("""
        CREATE TABLE IF NOT EXISTS tokens(
            token TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0,
            user_id INTEGER,
            created_at INTEGER
        )
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            activated INTEGER DEFAULT 0,
            expires_at INTEGER
        )
        """)

        await db.commit()

# ================== УТИЛИТЫ ==================

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def has_access(user_id: int) -> bool:
    if is_admin(user_id):
        return True

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT activated, expires_at FROM users WHERE user_id=?",
            (user_id,)
        )
        row = await cursor.fetchone()

    if not row:
        return False

    activated, expires_at = row

    if activated != 1:
        return False

    if not expires_at or expires_at < int(time.time()):
        return False

    return True

# ================== START ==================

@dp.message(CommandStart())
async def start(message: types.Message):

    user_id = message.from_user.id

    if is_admin(user_id):
        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="➕ Добавить токен")],
                [KeyboardButton(text="📋 Посмотреть токены")]
            ],
            resize_keyboard=True
        )

        await message.answer(
            "👑 Добро пожаловать, Администратор.\n"
            "Вы можете управлять токенами.",
            reply_markup=keyboard
        )
        return

    # 👤 Обычный пользователь
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="💳 Купить токен",
            url="https://playerok.com/profile/Ggggg-I/products"
        )],
        [InlineKeyboardButton(
            text="🔑 Активировать токен",
            callback_data="activate_token"
        )]
    ])

    await message.answer(
        "🤖 Привет!\n\n"
        "Я умный AI-бот.\n"
        "Напиши любой вопрос.\n"
        "Для разговора со мной надо купить токен.",
        reply_markup=keyboard
    )

# ================== АДМИН: ДОБАВЛЕНИЕ ТОКЕНА ==================

@dp.message(F.text == "📋 Посмотреть токены")
async def view_tokens(message: types.Message):

    if not is_admin(message.from_user.id):
        return

    async with aiosqlite.connect(DB) as db:
        cursor = await db.execute(
            "SELECT token, used FROM tokens ORDER BY created_at DESC"
        )
        tokens = await cursor.fetchall()

    if not tokens:
        await message.answer("📭 Токенов пока нет.")
        return

    text = "📋 Список токенов:\n\n"

    for token, used in tokens:
        status = "❌ Использован" if used == 1 else "✅ Активен"
        text += f"{token} — {status}\n"

    if len(text) > 4000:
        text = text[:4000] + "\n\n...слишком много токенов"

    await message.answer(text)

@dp.message(F.text == "➕ Добавить токен")
async def admin_add_token(message: types.Message, state: FSMContext):

    if not is_admin(message.from_user.id):
        return

    await state.set_state(AdminState.waiting_token)
    await message.answer("Введите токен:")

@dp.message(AdminState.waiting_token)
async def save_admin_token(message: types.Message, state: FSMContext):

    if not is_admin(message.from_user.id):
        return

    token = message.text

    async with aiosqlite.connect(DB) as db:
        await db.execute(
            "INSERT INTO tokens VALUES (?,?,?,?)",
            (token, 0, None, int(time.time()))
        )
        await db.commit()

    await message.answer("✅ Токен успешно добавлен.")
    await state.clear()

# ================== АКТИВАЦИЯ ТОКЕНА ==================

@dp.callback_query(F.data == "activate_token")
async def activate_token_start(call: types.CallbackQuery, state: FSMContext):

    await state.set_state(ActivateState.waiting_token)
    await call.message.answer("🔑 Введите токен:")
    await call.answer()

@dp.message(ActivateState.waiting_token)
async def process_token(message: types.Message, state: FSMContext):

    token_text = message.text
    user_id = message.from_user.id

    async with aiosqlite.connect(DB) as db:

        cursor = await db.execute(
            "SELECT token, used FROM tokens WHERE token=?",
            (token_text,)
        )
        row = await cursor.fetchone()

        if not row:
            await message.answer("❌ Неверный токен.")
            return

        if row[1] == 1:
            await message.answer("❌ Этот токен уже использован.")
            return

        # помечаем токен как использованный
        await db.execute(
            "UPDATE tokens SET used=1, user_id=? WHERE token=?",
            (user_id, token_text)
        )

        # активируем пользователя на 30 дней
        expires_at = int(time.time()) + 30 * 24 * 60 * 60
        await db.execute(
            "INSERT OR REPLACE INTO users VALUES (?,?,?)",
            (user_id, 1, expires_at)
        )
        await db.commit()

    await message.answer(
        "✅ Спасибо за покупку! Доступ активирован на 30 дней.\n"
        "Рад помочь, обращайтесь!"
    )
    await state.clear()

# ================== AI ==================

@dp.message(F.text)
async def chat(message: types.Message, state: FSMContext):

    # ❗ если пользователь в состоянии (активация токена / админ) → AI не срабатывает
    current_state = await state.get_state()
    if current_state is not None:
        return

    if not await has_access(message.from_user.id):
        await message.answer("❌ Нет активного токена.")
        return

    await bot.send_chat_action(message.chat.id, "typing")

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o",
            messages=[
                {"role": "system", "content": "Ты полезный AI помощник. Отвечай коротко. Бот умеет обрабатывать текст и фотографии, включая математические примеры и задания с изображений."},
                {"role": "user", "content": message.text}
            ],
            max_tokens=500
        )

        await message.answer(response.choices[0].message.content)

    except:
        await message.answer("❌ Ошибка AI")

@dp.message(F.photo)
async def handle_photo(message: types.Message, state: FSMContext):

    if not await has_access(message.from_user.id):
        return

    current_state = await state.get_state()
    if current_state is not None:
        return

    await bot.send_chat_action(message.chat.id, "typing")

    photo = message.photo[-1]

    file = await bot.get_file(photo.file_id)
    file_path = file.file_path
    image_bytes = await bot.download_file(file_path)

    image_data = base64.b64encode(image_bytes.read()).decode()

    try:
        response = client.chat.completions.create(
            model="openai/gpt-4o",  
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Реши задание на изображении и дай четкий,правильный,короткий ответ. Если на изображении текст, то просто прочитай его и дай ответ. Не нужно ничего объяснять, просто дай ответ."},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_data}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=150
        )

        await message.answer(response.choices[0].message.content)

    except Exception as e:
        print(e)
        await message.answer("❌ Ошибка при обработке изображения.")

# ================== ЗАПУСК ==================

async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())