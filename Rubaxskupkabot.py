import os
import random
import string
import logging
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== Конфигурация ==========
BOT_TOKEN =  os.getenv("BOT_TOKEN")
ADMIN_ID =   os.getenv("ADMIN_ID")

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("Не заданы переменные окружения BOT_TOKEN или ADMIN_ID")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise ValueError("ADMIN_ID должен быть числом")

# ========== Хранилище времени последней заявки ==========
# (в реальном проекте лучше использовать БД, но для демо хватит памяти)
user_last_request = {}

def can_send_request(user_id: int) -> tuple[bool, str]:
    """Проверяет, можно ли отправить заявку (не чаще 1 раза в 6 часов)"""
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
    """Обновляет время последней заявки"""
    user_last_request[user_id] = datetime.now()

def generate_lot_number() -> str:
    """Генерирует номер лота: # + 6 символов (заглавные буквы+цифры)"""
    return '#' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ========== Клавиатура ==========
reply_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📢 ПРОДАТЬ РОБУКСЫ")]],
    resize_keyboard=True
)

# ========== Состояния FSM ==========
class SellRobux(StatesGroup):
    waiting_for_amount = State()

# ========== Роутер и обработчики ==========
router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message):
    """Приветственное сообщение с информацией и кнопкой"""
    text = (
        "👋 Привет! Меня зовут Kotonaft15.\n"
        "Я продавец на FunPay и готов помочь вам обналичить игровую валюту в реальные деньги.\n\n"
        "💰 Курс: 1 Robux = 0.3 руб\n"
        "📦 Минимум: от 10 Robux\n"
        "⚖️ Комиссия игры (30%) лежит на вас.\n"
        "🛡 Гарант: FunPay (предпочтительно) или без гаранта (напрямую с вами, но первый не иду).\n"
        "⏳ Передача: через Game Pass (5 дней ожидания).\n\n"
        "Если хотите продать Robux, нажмите кнопку ниже 👇"
    )
    await message.answer(text, reply_markup=reply_keyboard)

@router.message(F.text == "📢 ПРОДАТЬ РОБУКСЫ")
async def sell_button(message: Message, state: FSMContext):
    """Нажатие кнопки — начало процесса продажи"""
    await message.answer("Введите количество Robux, которое вы готовы продать (минимум 10):")
    await state.set_state(SellRobux.waiting_for_amount)

@router.message(SellRobux.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    """Обработка введённого количества"""
    user_id = message.from_user.id

    # Проверка на число
    try:
        amount = int(message.text)
    except ValueError:
        await message.answer("❌ Пожалуйста, введите целое число.")
        return

    # Проверка минимальной суммы
    if amount < 10:
        await message.answer("❌ Минимальная сумма — 10 Robux. Попробуйте ещё раз.")
        return

    # Проверка временного ограничения
    can_send, limit_msg = can_send_request(user_id)
    if not can_send:
        await message.answer(limit_msg)
        await state.clear()
        return

    # Генерация номера лота
    lot = generate_lot_number()

    # Расчёты
    after_commission = int(amount * 0.7)               # за вычетом 30% комиссии игры
    price_fp = after_commission * 0.37                  # через FunPay
    price_direct = after_commission * 0.30               # напрямую

    # Сообщение пользователю
    await message.answer(
        f"✅ Лот {lot} создан и отправлен администратору.\n"
        f"Ожидайте, скоро с вами свяжутся.",
        parse_mode="Markdown"
    )

    # Сообщение администратору
    user = message.from_user
    user_link = f"@{user.username}" if user.username else f"<a href='tg://user?id={user.id}'>пользователь</a>"

    admin_text = (
        f"📦 Лот: {lot}\n"
        f"Количество: {amount} Robux\n"
        f"С вычетом комиссии (30%): {after_commission} Robux\n"
        f"Сумма оплаты:\n"
        f"💰 Цена с учётом комиссии FP: {price_fp:.2f} руб\n"
        f"💸 Цена напрямую: {price_direct:.2f} руб\n"
        f"👤 Связь с пользователем: {user_link}"
    )

    await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")

    # Обновляем время последней заявки
    update_last_request(user_id)

    # Завершаем состояние
    await state.clear()

# ========== Точка входа ==========
async def main():
    # Настройка логирования
    logging.basicConfig(level=logging.INFO)

    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Подключаем роутер
    dp.include_router(router)

    # Запуск поллинга
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
