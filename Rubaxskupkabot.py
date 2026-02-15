import os
import json
import random
import string
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

# ========== Конфигурация ==========
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

if not BOT_TOKEN or not ADMIN_ID:
    raise ValueError("Не заданы переменные окружения BOT_TOKEN или ADMIN_ID")

try:
    ADMIN_ID = int(ADMIN_ID)
except ValueError:
    raise ValueError("ADMIN_ID должен быть числом")

# ========== Работа с пользователями (JSON) ==========
USERS_FILE = "users.json"

def load_users() -> Dict[int, Dict[str, Any]]:
    """Загружает список пользователей из JSON-файла."""
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Преобразуем ключи в int
            return {int(k): v for k, v in data.items()}
    return {}

def save_users(users: Dict[int, Dict[str, Any]]):
    """Сохраняет список пользователей в JSON-файл."""
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def add_user(user_id: int, username: str = None, first_name: str = None):
    """Добавляет или обновляет информацию о пользователе."""
    users = load_users()
    if user_id not in users:
        users[user_id] = {
            "id": user_id,
            "username": username,
            "first_name": first_name,
            "first_seen": datetime.now().isoformat()
        }
    else:
        # Обновляем имя/юзернейм, если они изменились
        if username:
            users[user_id]["username"] = username
        if first_name:
            users[user_id]["first_name"] = first_name
    save_users(users)

def get_user_by_username(username: str) -> Optional[int]:
    """Возвращает ID пользователя по username (без @)."""
    users = load_users()
    username = username.lower().lstrip('@')
    for uid, data in users.items():
        if data.get("username") and data["username"].lower() == username:
            return uid
    return None

def get_all_users() -> list[int]:
    """Возвращает список всех ID пользователей."""
    return list(load_users().keys())

# ========== Хранилище времени последней заявки ==========
user_last_request: Dict[int, datetime] = {}

def can_send_request(user_id: int) -> tuple[bool, str]:
    """Проверяет, можно ли отправить заявку (не чаще 1 раза в 3 часа)"""
    if user_id not in user_last_request:
        return True, ""

    last_time = user_last_request[user_id]
    delta = datetime.now() - last_time
    # ИЗМЕНЕНО: 6 -> 3 часа
    if delta >= timedelta(hours=3):
        return True, ""
    else:
        remaining = timedelta(hours=3) - delta
        hours, remainder = divmod(remaining.seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        return False, f"⏳ Вы уже отправляли заявку. Попробуйте снова через {hours} ч. {minutes} мин."

def update_last_request(user_id: int):
    """Обновляет время последней заявки"""
    user_last_request[user_id] = datetime.now()

def generate_lot_number() -> str:
    """Генерирует номер лота: # + 6 символов (заглавные буквы+цифры)"""
    return '#' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# ========== Клавиатуры ==========
# ИЗМЕНЕНО: создаём две клавиатуры — для обычных пользователей и для админа
user_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📢 ПРОДАТЬ РОБУКСЫ")]],
    resize_keyboard=True
)

admin_keyboard = ReplyKeyboardMarkup(
    keyboard=[[]],  # пустая клавиатура (можно добавить кнопки для команд, если нужно)
    resize_keyboard=True
)

# ========== Состояния FSM ==========
class SellRobux(StatesGroup):
    waiting_for_amount = State()

class AdminStates(StatesGroup):
    waiting_for_broadcast = State()   # ожидание сообщения для рассылки

# ========== Глобальное состояние активного чата админа ==========
# Для одного админа храним ID пользователя, с которым идёт диалог (или None)
active_admin_chat: Optional[int] = None

# ========== Роутер и обработчики ==========
router = Router()

# ----- Вспомогательные функции для проверки админа -----
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ----- Обработчик команды /start -----
@router.message(CommandStart())
async def cmd_start(message: Message):
    """Приветственное сообщение с информацией и кнопкой"""
    user = message.from_user
    add_user(user.id, user.username, user.first_name)

    # ИЗМЕНЕНО: разная клавиатура для админа и пользователя
    keyboard = admin_keyboard if is_admin(user.id) else user_keyboard

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
    await message.answer(text, reply_markup=keyboard)

# ----- Обработчик кнопки "ПРОДАТЬ РОБУКСЫ" -----
@router.message(F.text == "📢 ПРОДАТЬ РОБУКСЫ")
async def sell_button(message: Message, state: FSMContext):
    """Нажатие кнопки — начало процесса продажи"""
    user = message.from_user
    add_user(user.id, user.username, user.first_name)

    # ИЗМЕНЕНО: админ не может продавать
    if is_admin(user.id):
        await message.answer("❌ Эта функция доступна только покупателям.")
        return

    await message.answer("Введите количество Robux, которое вы готовы продать (минимум 10):")
    await state.set_state(SellRobux.waiting_for_amount)

# ----- Обработчик ввода количества Robux -----
@router.message(SellRobux.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    """Обработка введённого количества"""
    user_id = message.from_user.id
    user = message.from_user
    add_user(user.id, user.username, user.first_name)

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

# ----- Обработчик команды /cancel (для выхода из состояний) -----
@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    if await state.get_state() is not None:
        await state.clear()
        await message.answer("❌ Действие отменено.")
    else:
        await message.answer("❌ Нет активного действия для отмены.")

# ----- Обработчик команд администратора -----
@router.message(Command("all"))
async def cmd_broadcast(message: Message, state: FSMContext):
    """Начало рассылки всем пользователям (только для админа)"""
    if not is_admin(message.from_user.id):
        return

    await message.answer(
        "Отправьте сообщение (текст, фото, видео, документ и т.п.) для рассылки всем пользователям.\n"
        "Или отправьте /cancel для отмены."
    )
    await state.set_state(AdminStates.waiting_for_broadcast)

@router.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    """Отправка полученного сообщения всем пользователям"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    # ИЗМЕНЕНО: принимаем любое сообщение, копируем его
    users = get_all_users()
    if not users:
        await message.answer("Список пользователей пуст.")
        await state.clear()
        return

    await message.answer(f"Начинаю рассылку {len(users)} пользователям...")

    success = 0
    failed = 0
    for uid in users:
        try:
            # Копируем сообщение (сохраняет тип, подпись, медиа)
            await message.copy_to(uid)
            success += 1
            await asyncio.sleep(0.05)  # небольшая задержка
        except TelegramForbiddenError:
            failed += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.copy_to(uid)
                success += 1
            except:
                failed += 1
        except Exception:
            failed += 1

    await message.answer(f"✅ Рассылка завершена.\nУспешно: {success}\nНе удалось: {failed}")
    await state.clear()

@router.message(Command("chat"))
async def cmd_chat(message: Message):
    """Начать диалог с пользователем (только для админа)"""
    if not is_admin(message.from_user.id):
        return

    global active_admin_chat

    # Если уже есть активный чат, предложим завершить его сначала
    if active_admin_chat is not None:
        await message.answer("⚠️ У вас уже есть активный чат. Сначала завершите его командой /end.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Укажите пользователя: /chat <username или id>")
        return

    target = args[1].strip()
    user_id = None

    # Пытаемся определить ID
    if target.isdigit():
        user_id = int(target)
        # Проверим, есть ли такой пользователь в нашей БД
        users = load_users()
        if user_id not in users:
            # Всё равно попробуем отправить сообщение, но если бот не может писать первым — не получится
            pass
    else:
        # Поиск по username
        user_id = get_user_by_username(target)
        if user_id is None:
            await message.answer("Пользователь с таким username не найден в базе.")
            return

    if user_id == ADMIN_ID:
        await message.answer("Нельзя начать чат с самим собой.")
        return

    # Проверим, может ли бот отправить сообщение этому пользователю (т.е. есть ли диалог)
    try:
        # Отправляем служебное сообщение, чтобы инициировать диалог
        await message.bot.send_message(
            user_id,
            "👤 Администратор начал с вами диалог. Теперь вы можете общаться через этого бота. Напишите ваше сообщение."
        )
    except Exception as e:
        await message.answer(f"❌ Не удалось отправить сообщение пользователю. Возможно, он не начинал диалог с ботом. Ошибка: {e}")
        return

    # Всё хорошо, устанавливаем активный чат
    active_admin_chat = user_id

    # Получаем информацию о пользователе для красивого ответа админу
    users = load_users()
    user_info = users.get(user_id, {})
    name = user_info.get("first_name") or user_info.get("username") or str(user_id)
    await message.answer(f"✅ Чат с пользователем {name} (ID: {user_id}) начат. Все ваши следующие сообщения будут пересылаться ему. Для завершения используйте /end.")

@router.message(Command("end"))
async def cmd_end(message: Message):
    """Завершить текущий диалог (только для админа)"""
    if not is_admin(message.from_user.id):
        return

    global active_admin_chat
    if active_admin_chat is None:
        await message.answer("Нет активного чата.")
        return

    # Уведомляем пользователя о завершении
    try:
        await message.bot.send_message(
            active_admin_chat,
            "🔚 Администратор завершил диалог. Если у вас остались вопросы, вы можете снова отправить заявку через кнопку."
        )
    except Exception:
        pass  # Если не удалось, ничего страшного

    active_admin_chat = None
    await message.answer("✅ Чат завершён.")

# ----- Основной обработчик сообщений (пересылка, если активен чат) -----
@router.message()
async def handle_all_messages(message: Message, state: FSMContext):
    """Обрабатывает все сообщения, не попавшие в другие хэндлеры."""
    user_id = message.from_user.id
    global active_admin_chat

    # Добавляем пользователя в базу при любом сообщении (на всякий случай)
    add_user(user_id, message.from_user.username, message.from_user.first_name)

    # Сообщения от админа
    if is_admin(user_id):
        # Проверяем, не находится ли админ в состоянии ожидания ввода (например, рассылки)
        current_state = await state.get_state()
        if current_state is not None:
            return  # состояние обработается в соответствующем хэндлере

        # Если админ не в состоянии и есть активный чат, пересылаем сообщение пользователю
        if active_admin_chat is not None:
            try:
                await message.copy_to(active_admin_chat)
            except Exception as e:
                await message.answer(f"❌ Не удалось отправить сообщение пользователю: {e}")
                active_admin_chat = None
                await message.answer("⚠️ Чат завершён из-за ошибки отправки.")
        else:
            # Нет активного чата — игнорируем обычные сообщения от админа
            # (можно ничего не отвечать, чтобы не засорять)
            pass
        return

    # Сообщения от обычного пользователя
    if active_admin_chat == user_id:
        try:
            await message.copy_to(ADMIN_ID)
        except Exception as e:
            logging.error(f"Не удалось переслать сообщение админу: {e}")
    else:
        # Пользователь не в активном чате
        if not message.text or not message.text.startswith('/'):
            await message.answer("Используйте кнопку «📢 ПРОДАТЬ РОБУКСЫ» для создания заявки.")

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
