import os
import random
import string
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# ========== Конфигурация ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8206605553 #os.getenv("ADMIN_ID")

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("Не заданы переменные окружения BOT_TOKEN или ADMIN_ID")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise ValueError("ADMIN_ID должен быть числом")

# ========== Хранилище времени последней заявки ==========
user_last_request = {}

def can_send_request(user_id: int) -> tuple[bool, str]:
    if user_id not in user_last_request:
        return True, ""
    last_time = user_last_request[user_id]
    delta = datetime.now() - last_time
    if delta >= timedelta(hours=6):
        return True, ""
    else:
        remaining = timedelta(hours=6) - delta
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return False, f"⏳ Вы уже отправляли заявку. Попробуйте снова через {hours} ч. {minutes} мин."

def update_last_request(user_id: int):
    user_last_request[user_id] = datetime.now()

def generate_lot_number() -> str:
    return '#' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ========== Клавиатура ==========
reply_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
reply_keyboard.add(KeyboardButton("📢 ПРОДАТЬ РОБУКСЫ"))

# ========== Состояния FSM ==========
class SellRobux(StatesGroup):
    waiting_for_amount = State()

# ========== Инициализация бота ==========
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ========== Обработчики ==========
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    text = (
        "👋 Привет! Меня зовут Kotonaft15.\n"
        "Я продавец на FunPay и готов помочь вам обналичить игровую валюту в реальные деньги.\n\n"
        "💰 **Курс:** 1 Robux = 0.3 руб\n"
        "📦 **Минимум:** от 10 Robux\n"
        "⚖️ **Комиссия игры (30%)** лежит на вас.\n"
        "🛡 **Гарант:** FunPay (предпочтительно) или без гаранта (но первый не иду).\n"
        "⏳ **Передача:** через Game Pass (5 дней ожидания).\n\n"
        "Если хотите продать Robux, нажмите кнопку ниже 👇"
    )
    await message.reply(text, reply_markup=reply_keyboard, parse_mode="Markdown")

@dp.message_handler(lambda message: message.text == "📢 ПРОДАТЬ РОБУКСЫ", state=None)
async def sell_button(message: types.Message):
    await SellRobux.waiting_for_amount.set()
    await message.reply("Введите количество Robux, которое вы готовы продать (минимум 10):")

@dp.message_handler(state=SellRobux.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    try:
        amount = int(message.text)
    except ValueError:
        await message.reply("❌ Пожалуйста, введите целое число.")
        return

    if amount < 10:
        await message.reply("❌ Минимальная сумма — 10 Robux. Попробуйте ещё раз.")
        return

    can_send, limit_msg = can_send_request(user_id)
    if not can_send:
        await message.reply(limit_msg)
        await state.finish()
        return

    lot = generate_lot_number()
    after_commission = int(amount * 0.7)
    price_fp = after_commission * 0.37
    price_direct = after_commission * 0.30

    await message.reply(
        f"✅ **Лот {lot} создан и отправлен администратору.**\n"
        f"Ожидайте, скоро с вами свяжутся.",
        parse_mode="Markdown"
    )

    user = message.from_user
    user_link = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>пользователь</a>"

    admin_text = (
        f"📦 **Лот:** {lot}\n"
        f"**Количество:** {amount} Robux\n"
        f"**С вычетом комиссии (30%):** {after_commission} Robux\n"
        f"**Сумма оплаты:**\n"
        f"💰 **Цена с учётом комиссии FP:** {price_fp:.2f} руб\n"
        f"💸 **Цена напрямую:** {price_direct:.2f} руб\n"
        f"👤 **Связь с пользователем:** {user_link}"
    )

    await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")

    update_last_request(user_id)
    await state.finish()

# ========== Запуск ==========
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    executor.start_polling(dp, skip_updates=True)
