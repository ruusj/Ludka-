"""
🎰 Telegram Casino Slot Bot
Оплата через Telegram Stars | send_dice 🎰 | Уведомления админам | Рассылка
"""

import logging
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import random
from datetime import datetime
import re

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = "8772816865:AAHIRFMh3NrujtIMKw8sdHGxdRZQv7pwAjk"   # <-- вставь токен сюда

ADMINS = [1171339982, 1677293342]   # ID двух администраторов

SPIN_COST = 18          # Стоимость одного прокрута в Stars
MIN_GIFT_VALUE = 230    # Минимальная ценность подарка в Stars
MAX_GIFT_VALUE = 260    # Максимальная ценность подарка в Stars

# ===================== КАК РАБОТАЕТ ПОБЕДА =====================
# Telegram send_dice с emoji 🎰 возвращает значение от 1 до 64.
# Значение 64 = три семёрки (777) — это настоящая анимация Telegram!
# Telegram сам решает что выпадет, мы только читаем результат.
# ================================================================

# ===================== ИНИЦИАЛИЗАЦИЯ =====================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# База данных пользователей (в памяти)
users_db: dict = {}

# Временное хранилище данных рассылки (per admin)
broadcast_data: dict = {}


# ===================== FSM СОСТОЯНИЯ =====================

class BroadcastStates(StatesGroup):
    waiting_text = State()
    waiting_media = State()
    waiting_time = State()
    confirm = State()


# ===================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =====================

def get_user(user_id: int, username: str = "Unknown") -> dict:
    if user_id not in users_db:
        users_db[user_id] = {
            "spins": 0,
            "wins": 0,
            "total_spent": 0,
            "username": username,
            "history": []
        }
    else:
        users_db[user_id]["username"] = username
    return users_db[user_id]


def calc_profitability(total_spent: int, gift_value: int) -> tuple[bool, int]:
    profit = total_spent - gift_value
    return profit >= 0, profit


def parse_broadcast_time(time_str: str):
    """Парсит строку времени. Возвращает datetime или None."""
    time_str = time_str.strip()
    # Формат ЧЧ:ММ сегодня
    match = re.match(r'^(\d{1,2}):(\d{2})$', time_str)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        now = datetime.now()
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if target <= now:
            # Если время уже прошло — ставим на завтра
            from datetime import timedelta
            target += timedelta(days=1)
        return target
    # Формат ДД.ММ ЧЧ:ММ
    match = re.match(r'^(\d{1,2})\.(\d{1,2})\s+(\d{1,2}):(\d{2})$', time_str)
    if match:
        day, mon, h, m = int(match.group(1)), int(match.group(2)), int(match.group(3)), int(match.group(4))
        now = datetime.now()
        target = now.replace(month=mon, day=day, hour=h, minute=m, second=0, microsecond=0)
        return target
    return None


# ===================== КЛАВИАТУРЫ =====================

def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Крутить (18 ⭐)", callback_data="buy_spin")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🏆 Как выиграть?", callback_data="how_to_win")],
    ])

def main_keyboard_admin() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎰 Крутить (18 ⭐)", callback_data="buy_spin")],
        [InlineKeyboardButton(text="📊 Моя статистика", callback_data="stats")],
        [InlineKeyboardButton(text="🏆 Как выиграть?", callback_data="how_to_win")],
        [InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel")],
    ])

def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Создать рассылку", callback_data="broadcast_create")],
        [InlineKeyboardButton(text="👥 Список игроков", callback_data="admin_players")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")],
    ])

def broadcast_skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить (без медиа)", callback_data="broadcast_skip_media")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")],
    ])

def broadcast_time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Отправить сейчас", callback_data="broadcast_now")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")],
    ])

def broadcast_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить и отправить", callback_data="broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")],
    ])


# ===================== ФУНКЦИЯ ПОКАЗА АДМИН-ПАНЕЛИ =====================

async def show_admin_panel(target: Message):
    total_users = len(users_db)
    total_spins = sum(u["spins"] for u in users_db.values())
    total_wins = sum(u["wins"] for u in users_db.values())
    total_revenue = sum(u["total_spent"] for u in users_db.values())
    estimated_gifts_cost = total_wins * int((MIN_GIFT_VALUE + MAX_GIFT_VALUE) / 2)
    estimated_profit = total_revenue - estimated_gifts_cost

    text = (
        "⚙️ <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{total_users}</b>\n"
        f"🎰 Всего прокрутов: <b>{total_spins}</b>\n"
        f"🏆 Всего побед: <b>{total_wins}</b>\n"
        f"⭐ Общий доход (Stars): <b>{total_revenue}</b>\n\n"
        f"💸 Расход на призы (примерно): <b>{estimated_gifts_cost} Stars</b>\n"
        f"{'📈 Прибыль' if estimated_profit >= 0 else '📉 Убыток'}: "
        f"<b>{estimated_profit} Stars</b>"
    )
    await target.answer(text, reply_markup=admin_keyboard(), parse_mode="HTML")


# ===================== ФУНКЦИЯ РАССЫЛКИ =====================

async def send_broadcast(admin_id: int):
    """Выполняет рассылку всем пользователям."""
    data = broadcast_data.get(admin_id, {})
    text = data.get("text", "")
    media_type = data.get("media_type")   # "photo", "sticker", "animation", "video", None
    media_file_id = data.get("media_file_id")

    all_user_ids = list(users_db.keys())
    sent = 0
    failed = 0

    for uid in all_user_ids:
        try:
            if media_type == "photo":
                await bot.send_photo(uid, photo=media_file_id, caption=text, parse_mode="HTML")
            elif media_type == "sticker":
                if text:
                    await bot.send_message(uid, text, parse_mode="HTML")
                await bot.send_sticker(uid, sticker=media_file_id)
            elif media_type == "animation":
                await bot.send_animation(uid, animation=media_file_id, caption=text, parse_mode="HTML")
            elif media_type == "video":
                await bot.send_video(uid, video=media_file_id, caption=text, parse_mode="HTML")
            else:
                await bot.send_message(uid, text, parse_mode="HTML")
            sent += 1
            await asyncio.sleep(0.05)  # Защита от флуда
        except Exception as e:
            logger.error(f"Ошибка рассылки для {uid}: {e}")
            failed += 1

    # Отчёт админу
    report = (
        f"📢 <b>Рассылка завершена!</b>\n\n"
        f"✅ Успешно: <b>{sent}</b>\n"
        f"❌ Ошибок: <b>{failed}</b>\n"
        f"👥 Всего: <b>{len(all_user_ids)}</b>"
    )
    try:
        await bot.send_message(admin_id, report, parse_mode="HTML")
    except Exception:
        pass

    # Очищаем временные данные
    broadcast_data.pop(admin_id, None)


async def schedule_broadcast(admin_id: int, target_time: datetime):
    """Планирует отложенную рассылку."""
    now = datetime.now()
    delay = (target_time - now).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)
    await send_broadcast(admin_id)


# ===================== ХЭНДЛЕРЫ =====================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    uname = message.from_user.username or message.from_user.first_name
    get_user(message.from_user.id, uname)

    is_admin = message.from_user.id in ADMINS

    text = (
        "🎰 <b>Добро пожаловать в Казино-Бот!</b>\n\n"
        "Испытай удачу! Крути рулетку и выигрывай призы!\n\n"
        "💫 <b>Как играть:</b>\n"
        "1️⃣ Нажми кнопку «Крутить»\n"
        "2️⃣ Оплати <b>18 ⭐ Stars</b>\n"
        "3️⃣ Смотри анимацию рулетки\n"
        "4️⃣ Выпало <b>777</b> = ты выиграл подарок!\n\n"
        "🎁 <b>Призы:</b> крутые подарки победителям!\n"
    )

    if is_admin:
        text += "\n\n⚙️ <i>Ты администратор этого бота</i>"
        await message.answer(text, reply_markup=main_keyboard_admin(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=main_keyboard(), parse_mode="HTML")


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMINS:
        await message.answer("❌ У тебя нет доступа к этой команде.")
        return
    await show_admin_panel(message)


@dp.callback_query(F.data == "buy_spin")
async def cb_buy_spin(callback: CallbackQuery):
    await callback.answer()
    prices = [LabeledPrice(label="Прокрут рулетки 🎰", amount=SPIN_COST)]
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="🎰 Прокрут рулетки",
        description="Один прокрут казино-рулетки. Выпадет 777 — выиграешь крутой подарок!",
        payload=f"spin_{callback.from_user.id}",
        currency="XTR",
        prices=prices,
    )


@dp.callback_query(F.data == "stats")
async def cb_stats(callback: CallbackQuery):
    await callback.answer()
    uname = callback.from_user.username or callback.from_user.first_name
    user = get_user(callback.from_user.id, uname)

    spins = user["spins"]
    wins = user["wins"]
    spent = user["total_spent"]
    win_rate = (wins / spins * 100) if spins > 0 else 0

    text = (
        f"📊 <b>Твоя статистика</b>\n\n"
        f"🎰 Всего прокрутов: <b>{spins}</b>\n"
        f"🏆 Побед: <b>{wins}</b>\n"
        f"⭐ Потрачено Stars: <b>{spent}</b>\n"
        f"📈 Процент побед: <b>{win_rate:.1f}%</b>\n\n"
        "💡 Продолжай крутить — удача не за горами!"
    )

    kb = main_keyboard_admin() if callback.from_user.id in ADMINS else main_keyboard()
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "how_to_win")
async def cb_how_to_win(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🏆 <b>Как выиграть?</b>\n\n"
        f"🎰 Крути рулетку за <b>18 ⭐ Stars</b>\n\n"
        "Telegram сам анимирует рулетку!\n"
        "Если выпадает <b>777</b> — ты выигрываешь подарок!\n\n"
        "🎁 <b>Подарок:</b> крутой сюрприз для победителя!\n\n"
        "🍀 Удачи!"
    )
    kb = main_keyboard_admin() if callback.from_user.id in ADMINS else main_keyboard()
    await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()
    await show_admin_panel(callback.message)


@dp.callback_query(F.data == "admin_players")
async def cb_admin_players(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()

    if not users_db:
        await callback.message.answer("👥 Игроков пока нет.")
        return

    text = "👥 <b>Список игроков (топ 20):</b>\n\n"
    sorted_users = sorted(users_db.items(), key=lambda x: x[1]["total_spent"], reverse=True)
    for uid, u in sorted_users[:20]:
        uname = f"@{u['username']}" if u['username'] != "Unknown" else f"ID:{uid}"
        text += (
            f"• {uname} — {u['spins']} прок., "
            f"{u['wins']} побед, {u['total_spent']}⭐\n"
        )

    await callback.message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "admin_back")
async def cb_admin_back(callback: CallbackQuery):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()
    uname = callback.from_user.username or callback.from_user.first_name
    get_user(callback.from_user.id, uname)
    text = (
        "🎰 <b>Главное меню</b>\n\n"
        "⚙️ <i>Ты администратор этого бота</i>"
    )
    await callback.message.answer(text, reply_markup=main_keyboard_admin(), parse_mode="HTML")


# ===================== РАССЫЛКА — FSM =====================

@dp.callback_query(F.data == "broadcast_create")
async def cb_broadcast_create(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()

    broadcast_data[callback.from_user.id] = {}
    await state.set_state(BroadcastStates.waiting_text)

    await callback.message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "Шаг 1/3 — Введи текст сообщения для рассылки.\n\n"
        "<i>Поддерживается HTML-форматирование: "
        "<b>жирный</b>, <i>курсив</i>, <code>код</code>, ссылки.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")]
        ])
    )


@dp.message(BroadcastStates.waiting_text)
async def broadcast_get_text(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    broadcast_data[message.from_user.id]["text"] = message.text or message.caption or ""
    await state.set_state(BroadcastStates.waiting_media)

    await message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "Шаг 2/3 — Прикрепи медиа к посту.\n\n"
        "Можно отправить:\n"
        "🖼 <b>Фото</b>\n"
        "🎞 <b>GIF / анимацию</b>\n"
        "🎬 <b>Видео</b>\n"
        "🎭 <b>Стикер</b>\n\n"
        "<i>Или нажми «Пропустить», чтобы отправить только текст.</i>",
        parse_mode="HTML",
        reply_markup=broadcast_skip_keyboard()
    )


@dp.message(BroadcastStates.waiting_media)
async def broadcast_get_media(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    admin_id = message.from_user.id

    if message.photo:
        broadcast_data[admin_id]["media_type"] = "photo"
        broadcast_data[admin_id]["media_file_id"] = message.photo[-1].file_id
    elif message.sticker:
        broadcast_data[admin_id]["media_type"] = "sticker"
        broadcast_data[admin_id]["media_file_id"] = message.sticker.file_id
    elif message.animation:
        broadcast_data[admin_id]["media_type"] = "animation"
        broadcast_data[admin_id]["media_file_id"] = message.animation.file_id
    elif message.video:
        broadcast_data[admin_id]["media_type"] = "video"
        broadcast_data[admin_id]["media_file_id"] = message.video.file_id
    else:
        await message.answer(
            "❌ Неподдерживаемый тип медиа.\n"
            "Отправь фото, GIF, видео или стикер, либо нажми «Пропустить».",
            reply_markup=broadcast_skip_keyboard()
        )
        return

    await state.set_state(BroadcastStates.waiting_time)
    await message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "Шаг 3/3 — Когда отправить?\n\n"
        "Введи время в формате:\n"
        "• <code>15:30</code> — сегодня в 15:30\n"
        "• <code>25.06 10:00</code> — 25 июня в 10:00\n\n"
        "Или нажми <b>«Отправить сейчас»</b>.",
        parse_mode="HTML",
        reply_markup=broadcast_time_keyboard()
    )


@dp.callback_query(F.data == "broadcast_skip_media")
async def cb_broadcast_skip_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()

    broadcast_data[callback.from_user.id]["media_type"] = None
    broadcast_data[callback.from_user.id]["media_file_id"] = None

    await state.set_state(BroadcastStates.waiting_time)
    await callback.message.answer(
        "📢 <b>Создание рассылки</b>\n\n"
        "Шаг 3/3 — Когда отправить?\n\n"
        "Введи время в формате:\n"
        "• <code>15:30</code> — сегодня в 15:30\n"
        "• <code>25.06 10:00</code> — 25 июня в 10:00\n\n"
        "Или нажми <b>«Отправить сейчас»</b>.",
        parse_mode="HTML",
        reply_markup=broadcast_time_keyboard()
    )


@dp.callback_query(F.data == "broadcast_now")
async def cb_broadcast_now(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()

    broadcast_data[callback.from_user.id]["scheduled_time"] = None
    await state.set_state(BroadcastStates.confirm)
    await show_broadcast_preview(callback.message, callback.from_user.id)


@dp.message(BroadcastStates.waiting_time)
async def broadcast_get_time(message: Message, state: FSMContext):
    if message.from_user.id not in ADMINS:
        return

    target_time = parse_broadcast_time(message.text or "")
    if not target_time:
        await message.answer(
            "❌ Неверный формат времени.\n\n"
            "Используй:\n"
            "• <code>15:30</code>\n"
            "• <code>25.06 10:00</code>",
            parse_mode="HTML",
            reply_markup=broadcast_time_keyboard()
        )
        return

    broadcast_data[message.from_user.id]["scheduled_time"] = target_time
    await state.set_state(BroadcastStates.confirm)
    await show_broadcast_preview(message, message.from_user.id)


async def show_broadcast_preview(target: Message, admin_id: int):
    """Показывает превью рассылки перед отправкой."""
    data = broadcast_data.get(admin_id, {})
    text = data.get("text", "(без текста)")
    media_type = data.get("media_type")
    scheduled = data.get("scheduled_time")

    media_label = {
        "photo": "🖼 Фото",
        "sticker": "🎭 Стикер",
        "animation": "🎞 GIF/анимация",
        "video": "🎬 Видео",
        None: "Нет"
    }.get(media_type, "Нет")

    time_label = scheduled.strftime("%d.%m.%Y %H:%M") if scheduled else "Сейчас"
    total_users = len(users_db)

    preview = (
        "📢 <b>Предпросмотр рассылки</b>\n\n"
        f"📝 <b>Текст:</b>\n{text}\n\n"
        f"🖼 <b>Медиа:</b> {media_label}\n"
        f"🕐 <b>Время отправки:</b> {time_label}\n"
        f"👥 <b>Получателей:</b> {total_users}\n\n"
        "Подтвердить отправку?"
    )

    await target.answer(preview, parse_mode="HTML", reply_markup=broadcast_confirm_keyboard())


@dp.callback_query(F.data == "broadcast_confirm")
async def cb_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()
    await state.clear()

    admin_id = callback.from_user.id
    data = broadcast_data.get(admin_id, {})
    scheduled = data.get("scheduled_time")

    if scheduled:
        delay_sec = (scheduled - datetime.now()).total_seconds()
        minutes = int(delay_sec // 60)
        await callback.message.answer(
            f"✅ <b>Рассылка запланирована!</b>\n\n"
            f"🕐 Время: <b>{scheduled.strftime('%d.%m.%Y %H:%M')}</b>\n"
            f"⏳ Примерно через <b>{minutes} мин.</b>",
            parse_mode="HTML"
        )
        # Запускаем отложенную задачу
        asyncio.create_task(schedule_broadcast(admin_id, scheduled))
    else:
        await callback.message.answer("📤 <b>Рассылка запущена...</b>", parse_mode="HTML")
        asyncio.create_task(send_broadcast(admin_id))


@dp.callback_query(F.data == "broadcast_cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMINS:
        await callback.answer("❌ Нет доступа", show_alert=True)
        return
    await callback.answer()
    await state.clear()
    broadcast_data.pop(callback.from_user.id, None)

    await callback.message.answer(
        "❌ <b>Рассылка отменена.</b>",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


# ===================== ОПЛАТА =====================

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    await query.answer(ok=True)


@dp.message(F.successful_payment)
async def successful_payment(message: Message):
    user_id = message.from_user.id
    uname = message.from_user.username or message.from_user.first_name

    user = get_user(user_id, uname)
    user["spins"] += 1
    user["total_spent"] += SPIN_COST

    dice_msg = await bot.send_dice(chat_id=user_id, emoji="🎰")
    dice_value = dice_msg.dice.value

    await asyncio.sleep(3)

    is_win = (dice_value == 64)

    if is_win:
        user["wins"] += 1
        gift_value = random.randint(MIN_GIFT_VALUE, MAX_GIFT_VALUE)
        profitable, profit_diff = calc_profitability(user["total_spent"], gift_value)

        win_text = (
            "🎉 <b>УРА! ВЫ ВЫИГРАЛИ!</b> 🎉\n\n"
            "7️⃣7️⃣7️⃣ <b>ДЖЕКПОТ 777!</b>\n\n"
            "🎁 Ваш приз — крутой подарок!\n"
            "📨 Администратор свяжется с вами для вручения приза.\n\n"
            f"🎰 Прокрутов сделано: <b>{user['spins']}</b>\n"
            f"⭐ Потрачено Stars: <b>{user['total_spent']}</b>"
        )

        kb = main_keyboard_admin() if user_id in ADMINS else main_keyboard()
        await message.answer(win_text, parse_mode="HTML", reply_markup=kb)

        win_record = {
            "time": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "spins": user["spins"],
            "gift_value": gift_value,
            "total_spent": user["total_spent"],
            "profitable": profitable,
            "profit_diff": profit_diff,
        }
        user["history"].append(win_record)

        admin_text = (
            "🏆 <b>НОВЫЙ ПОБЕДИТЕЛЬ!</b>\n\n"
            f"👤 Пользователь: @{uname} (ID: <code>{user_id}</code>)\n"
            f"🎰 Прокрутов сделано: <b>{user['spins']}</b>\n"
            f"⭐ Потрачено Stars: <b>{user['total_spent']}</b>\n"
            f"🎁 Приз: подарок на <b>{gift_value} Stars</b>\n\n"
            f"{'✅ МЫ ОКУПИЛИСЬ с этого игрока' if profitable else '❌ Мы НЕ окупились с этого игрока'}\n"
            f"{'📈 Прибыль' if profitable else '📉 Убыток'}: "
            f"<b>{abs(profit_diff)} Stars</b>\n\n"
            f"🕐 Время: {win_record['time']}"
        )

        for admin_id in ADMINS:
            try:
                await bot.send_message(admin_id, admin_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")

    else:
        lose_text = (
            "😔 <b>Не повезло в этот раз...</b>\n\n"
            "🍀 Попробуй ещё — удача уже близко!\n\n"
            f"🎰 Прокрутов: <b>{user['spins']}</b>"
        )
        kb = main_keyboard_admin() if user_id in ADMINS else main_keyboard()
        await message.answer(lose_text, parse_mode="HTML", reply_markup=kb)


# ===================== ЗАПУСК =====================

async def main():
    logger.info("🎰 Казино-бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())