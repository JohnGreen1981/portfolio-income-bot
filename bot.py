import asyncio
import logging
from datetime import date, timedelta
from functools import wraps

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from config import settings
from currency import format_amount_with_rub, to_rub
from expense_parser import chat_analytics, normalize_shop, parse_expense_text, parse_receipt_image
from parser import parse_income, transcribe_voice
from sheets import SheetsClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

bot = Bot(token=settings.telegram_token)
dp = Dispatcher(storage=MemoryStorage())
sheets = SheetsClient()

# Временное хранилище распознанных чеков до подтверждения пользователем
pending_receipts: dict[int, list[dict]] = {}

# Хранилище строк для коррекции категории (user_id → row в Sheets)
correction_targets: dict[int, int] = {}

# Индекс строки чека, которую редактирует пользователь (user_id → item index)
pending_receipt_edit_idx: dict[int, int] = {}

# Временное хранилище голосовых расходов до подтверждения
pending_voice_expenses: dict[int, list[dict]] = {}

EXPENSE_CATEGORIES = [
    "Продукты", "Овощи и фрукты", "Мясо и рыба",
    "Бытовая химия", "Аптека", "Медицина",
    "Алкоголь", "Табак", "Напитки",
    "Кафе/рестораны", "Транспорт", "Одежда и обувь",
    "Электроника", "Товары для дома", "Дом/ЖКХ",
    "Связь/интернет", "Подписки",
    "Развлечения", "Красота/уход", "Образование",
    "Семья/дети", "Долги", "Налоги", "Прочее",
]


class Mode(StatesGroup):
    income = State()
    expense = State()
    analytics = State()


# --- Keyboards ---

def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💰 Доходы", callback_data="mode:income"),
        InlineKeyboardButton(text="💸 Расходы", callback_data="mode:expense"),
        InlineKeyboardButton(text="📊 Аналитика", callback_data="mode:analytics"),
    ]])


def analytics_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сегодня", callback_data="analytics:today"),
            InlineKeyboardButton(text="7 дней", callback_data="analytics:week"),
        ],
        [
            InlineKeyboardButton(text="Месяц", callback_data="analytics:month"),
            InlineKeyboardButton(text="Год", callback_data="analytics:year"),
        ],
    ])


def back_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🏠 Главное меню")]],
        resize_keyboard=True,
    )


def receipt_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Записать", callback_data="receipt:confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="receipt:cancel"),
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить категорию", callback_data="receipt:edit"),
        ],
    ])


def receipt_items_kb(records: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, r in enumerate(records):
        desc = r["description"][:25] if r["description"] else "—"
        label = f"{r['category']} ({desc})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"receipt_item:{i}")])
    rows.append([InlineKeyboardButton(text="↩️ Назад к чеку", callback_data="receipt:back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def receipt_category_picker_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(EXPENSE_CATEGORIES), 2):
        row = [
            InlineKeyboardButton(text=cat, callback_data=f"rcat:{cat}")
            for cat in EXPENSE_CATEGORIES[i:i + 2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def voice_expense_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Записать", callback_data="vexp:confirm"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="vexp:cancel"),
    ]])


def expense_recorded_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✏️ Изменить категорию", callback_data="correct:pick"),
    ]])


def category_picker_kb() -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(EXPENSE_CATEGORIES), 2):
        row = [
            InlineKeyboardButton(text=cat, callback_data=f"cat:{cat}")
            for cat in EXPENSE_CATEGORIES[i:i + 2]
        ]
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --- Auth decorator ---

def only_allowed(func):
    @wraps(func)
    async def wrapper(event, *args, **kwargs):
        user_id = event.from_user.id if hasattr(event, "from_user") else None
        if user_id != settings.allowed_user_id:
            if hasattr(event, "answer"):
                await event.answer("Доступ запрещён.")
            return
        return await func(event, *args, **kwargs)
    return wrapper


# --- /start и /menu ---

@dp.message(Command("start"))
@only_allowed
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я помогаю вести учёт финансов.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer("Выбери режим работы:", reply_markup=main_menu_kb())


@dp.message(Command("menu"))
@only_allowed
async def cmd_menu(message: Message, state: FSMContext):
    await state.clear()
    temp = await message.answer(".", reply_markup=ReplyKeyboardRemove())
    await temp.delete()
    await message.answer("Выбери режим работы:", reply_markup=main_menu_kb())


@dp.message(F.text == "🏠 Главное меню")
@only_allowed
async def handle_back_button(message: Message, state: FSMContext):
    await state.clear()
    temp = await message.answer(".", reply_markup=ReplyKeyboardRemove())
    await temp.delete()
    await message.answer("Выбери режим работы:", reply_markup=main_menu_kb())


# --- Выбор режима ---

@dp.callback_query(F.data.startswith("mode:"))
@only_allowed
async def cb_mode(callback: CallbackQuery, state: FSMContext):
    mode = callback.data.split(":")[1]

    if mode == "income":
        await state.set_state(Mode.income)
        await callback.message.answer(
            "Режим: *Доходы* 💰\n\nНапиши или надиктуй поступление, например:\n"
            "«Получил 15000 от Иванова за разработку»",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
    elif mode == "expense":
        await state.set_state(Mode.expense)
        await callback.message.answer(
            "Режим: *Расходы* 💸\n\nНапиши, надиктуй или отправь фото чека, например:\n"
            "«Потратил 2500 в Пятёрочке на продукты»",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
    elif mode == "analytics":
        await state.set_state(Mode.analytics)
        await state.update_data(
            analytics_history=[],
            analytics_income=[],
            analytics_expenses=[],
            analytics_period="",
        )
        await callback.message.answer(
            "📊 *Аналитика*\n\nВыбери период — и я дам отчёт. Потом можно задавать любые вопросы по финансам.",
            parse_mode="Markdown",
            reply_markup=back_kb(),
        )
        await callback.message.answer("Быстрый отчёт:", reply_markup=analytics_kb())

    await callback.answer()


# --- Аналитика ---

@dp.callback_query(F.data.startswith("analytics:"))
@only_allowed
async def cb_analytics(callback: CallbackQuery, state: FSMContext):
    period = callback.data.split(":")[1]
    today = date.today()

    if period == "today":
        start, label = today, "Сегодня"
    elif period == "week":
        start, label = today - timedelta(days=6), "7 дней"
    elif period == "month":
        start, label = today.replace(day=1), "Текущий месяц"
    else:
        start, label = today.replace(month=1, day=1), "Текущий год"

    processing_msg = await callback.message.answer("⏳ Загружаю данные...")

    income = sheets.get_records_by_period(start, today)
    expenses = sheets.get_expenses_by_period(start, today)

    initial_msg = f"Сделай краткий финансовый отчёт за период: {label}"
    history = [{"role": "user", "content": initial_msg}]
    report = await chat_analytics(history, income, expenses, label)
    history.append({"role": "assistant", "content": report})

    await state.set_state(Mode.analytics)
    await state.update_data(
        analytics_history=history,
        analytics_income=income,
        analytics_expenses=expenses,
        analytics_period=label,
    )

    await processing_msg.delete()
    await callback.message.answer(report, parse_mode="Markdown")
    await callback.answer()


# --- Подтверждение чека ---

@dp.callback_query(F.data.in_({"receipt:confirm", "receipt:cancel"}))
@only_allowed
async def cb_receipt(callback: CallbackQuery):
    action = callback.data.split(":")[1]
    user_id = callback.from_user.id
    records = pending_receipts.pop(user_id, None)

    if action == "confirm" and records:
        for record in records:
            sheets.add_expense_record(record)
        await callback.message.edit_text(
            callback.message.text + f"\n\n✅ Записано {len(records)} позиций."
        )
    else:
        await callback.message.edit_text(
            callback.message.text + "\n\n❌ Отменено."
        )

    await callback.answer()


# --- Команды сводки доходов ---

@dp.message(Command("today"))
@only_allowed
async def cmd_today(message: Message):
    today = date.today()
    await _send_income_summary(message, today, today, "Сегодня")


@dp.message(Command("week"))
@only_allowed
async def cmd_week(message: Message):
    today = date.today()
    await _send_income_summary(message, today - timedelta(days=6), today, "За 7 дней")


@dp.message(Command("month"))
@only_allowed
async def cmd_month(message: Message):
    today = date.today()
    await _send_income_summary(message, today.replace(day=1), today, "За текущий месяц")


async def _send_income_summary(message: Message, start: date, end: date, label: str):
    records = sheets.get_records_by_period(start, end)
    if not records:
        await message.answer(f"*{label}:* поступлений нет.", parse_mode="Markdown")
        return

    total = sum(r["amount"] for r in records)
    lines = [f"*{label}* — итого: *{total:,.0f} ₽*\n"]
    for r in records:
        lines.append(
            f"• `{r['date']}` | {r['client']} | *{r['amount']:,.0f} ₽*"
            + (f"\n  _{r['description']}_" if r["description"] else "")
        )
    await message.answer("\n".join(lines), parse_mode="Markdown")


# --- Голосовые сообщения ---

@dp.message(F.voice)
@only_allowed
async def handle_voice(message: Message, state: FSMContext):
    processing_msg = await message.answer("🎙 Распознаю голос...")

    file = await bot.get_file(message.voice.file_id)
    audio_bytes = await bot.download_file(file.file_path)
    text = await transcribe_voice(audio_bytes.read())

    await processing_msg.delete()

    if not text:
        await message.answer("Не удалось распознать голосовое сообщение. Попробуй ещё раз.")
        return

    await message.answer(f"🗣 Распознано: _{text}_", parse_mode="Markdown")

    current_state = await state.get_state()
    if current_state == Mode.expense.state:
        await _process_voice_expense(message, text)
    elif current_state == Mode.income.state:
        await _process_income_text(message, text)
    elif current_state == Mode.analytics.state:
        await _process_analytics_chat(message, text, state)
    else:
        await message.answer(
            "Выбери режим — куда записать?",
            reply_markup=main_menu_kb(),
        )


# --- Фото чеков ---

@dp.message(F.photo)
@only_allowed
async def handle_photo(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state != Mode.expense.state:
        await message.answer(
            "Фото чеков принимаю только в режиме *Расходы* 💸",
            parse_mode="Markdown",
            reply_markup=main_menu_kb(),
        )
        return

    processing_msg = await message.answer("🧾 Распознаю чек...")

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    image_bytes = await bot.download_file(file.file_path)
    result = await parse_receipt_image(image_bytes.read())

    await processing_msg.delete()

    if not result or not result.get("categories"):
        await message.answer("Не удалось распознать чек. Попробуй сфотографировать чётче.")
        return

    shop = normalize_shop(result.get("shop", ""))
    receipt_date = result.get("date", date.today().isoformat())
    total_on_receipt = result.get("total_on_receipt", 0)

    currency = result.get("currency", "RUB").upper()
    records = []
    for cat in result["categories"]:
        amount_orig = round(float(cat["amount"]))
        amount_rub, rate = await to_rub(amount_orig, currency)
        records.append({
            "date": receipt_date,
            "category": cat["category"],
            "amount": amount_orig,
            "amount_rub": amount_rub,
            "currency": currency,
            "rate": rate,
            "shop": shop,
            "description": ", ".join(cat.get("items", [])),
            "raw": f"Чек {shop} {receipt_date}".strip(),
        })

    pending_receipts[message.from_user.id] = records
    await _send_receipt_preview(message, records, total_on_receipt)


# --- Хелпер: превью чека ---

async def _send_receipt_preview(
    message: Message,
    records: list[dict],
    total_on_receipt: float = 0,
):
    shop = records[0].get("shop", "") if records else ""
    receipt_date = records[0].get("date", date.today().isoformat()) if records else ""
    currency = records[0]["currency"] if records else "RUB"

    shop_label = f" {shop}" if shop else ""
    lines = [f"📷 *Чек{shop_label}* от {receipt_date}\n"]
    for r in records:
        desc = f" ({r['description']})" if r["description"] else ""
        amount_str = format_amount_with_rub(r["amount"], r["currency"], r["amount_rub"])
        lines.append(f"• {r['category']}{desc} — *{amount_str}*")

    calc_total_rub = sum(r["amount_rub"] for r in records)
    calc_total_orig = sum(r["amount"] for r in records)
    lines.append(f"\n*Итого: {format_amount_with_rub(calc_total_orig, currency, calc_total_rub)}*")
    if total_on_receipt and abs(calc_total_orig - total_on_receipt) > 1:
        lines.append(
            f"⚠️ В чеке: {total_on_receipt:,.0f} (расхождение {abs(calc_total_orig - total_on_receipt):,.0f})"
        )
    lines.append("\nЗаписать?")

    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=receipt_confirm_kb(),
    )


# --- Редактирование чека ---

@dp.callback_query(F.data == "receipt:edit")
@only_allowed
async def cb_receipt_edit(callback: CallbackQuery):
    user_id = callback.from_user.id
    records = pending_receipts.get(user_id)
    if not records:
        await callback.answer("Нет активного чека.", show_alert=True)
        return
    await callback.message.answer(
        "Выбери строку для изменения категории:",
        reply_markup=receipt_items_kb(records),
    )
    await callback.answer()


@dp.callback_query(F.data == "receipt:back")
@only_allowed
async def cb_receipt_back(callback: CallbackQuery):
    user_id = callback.from_user.id
    records = pending_receipts.get(user_id)
    if not records:
        await callback.answer("Нет активного чека.", show_alert=True)
        return
    await _send_receipt_preview(callback.message, records)
    await callback.answer()


@dp.callback_query(F.data.startswith("receipt_item:"))
@only_allowed
async def cb_receipt_item(callback: CallbackQuery):
    user_id = callback.from_user.id
    idx = int(callback.data.split(":")[1])
    records = pending_receipts.get(user_id)
    if not records or idx >= len(records):
        await callback.answer("Ошибка: строка не найдена.", show_alert=True)
        return
    pending_receipt_edit_idx[user_id] = idx
    item = records[idx]
    await callback.message.answer(
        f"Сейчас: *{item['category']}*\nВыбери новую категорию:",
        parse_mode="Markdown",
        reply_markup=receipt_category_picker_kb(),
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("rcat:"))
@only_allowed
async def cb_receipt_category(callback: CallbackQuery):
    user_id = callback.from_user.id
    category = callback.data[len("rcat:"):]
    idx = pending_receipt_edit_idx.pop(user_id, None)
    records = pending_receipts.get(user_id)

    if idx is None or not records or idx >= len(records):
        await callback.answer("Ошибка обновления.", show_alert=True)
        return

    old_cat = records[idx]["category"]
    records[idx]["category"] = category
    await callback.message.edit_text(
        f"✅ Изменено: *{old_cat}* → *{category}*", parse_mode="Markdown"
    )
    await _send_receipt_preview(callback.message, records)
    await callback.answer()


# --- Голосовые расходы: превью и подтверждение ---

async def _process_voice_expense(message: Message, text: str):
    processing_msg = await message.answer("⏳ Обрабатываю...")
    records = await parse_expense_text(text)
    await processing_msg.delete()

    if not records:
        await message.answer(
            "Не удалось распознать сумму. Попробуй сказать иначе, например:\n"
            "«Потратил 1500 в Магните на продукты»"
        )
        return

    for record in records:
        amount_rub, rate = await to_rub(record["amount"], record["currency"])
        record["amount_rub"] = amount_rub
        record["rate"] = rate

    pending_voice_expenses[message.from_user.id] = records

    lines = ["🎙 *Распознанный расход:*\n"]
    for r in records:
        shop_label = f" ({r['shop']})" if r["shop"] else ""
        amount_str = format_amount_with_rub(r["amount"], r["currency"], r["amount_rub"])
        lines.append(f"• {r['category']}{shop_label} — *{amount_str}*")
        if r.get("description"):
            lines.append(f"  _{r['description']}_")
        lines.append(f"  📅 {r['date']}")

    lines.append("\nЗаписать?")
    await message.answer("\n".join(lines), parse_mode="Markdown", reply_markup=voice_expense_confirm_kb())


@dp.callback_query(F.data.in_({"vexp:confirm", "vexp:cancel"}))
@only_allowed
async def cb_voice_expense(callback: CallbackQuery):
    user_id = callback.from_user.id
    records = pending_voice_expenses.pop(user_id, None)

    if callback.data == "vexp:confirm" and records:
        last_row = -1
        for record in records:
            last_row = sheets.add_expense_record(record)

        if len(records) == 1:
            r = records[0]
            shop_label = f" ({r['shop']})" if r["shop"] else ""
            amount_str = format_amount_with_rub(r["amount"], r["currency"], r["amount_rub"])
            if last_row > 0:
                correction_targets[user_id] = last_row
            await callback.message.edit_text(
                f"✅ Записано!\n\n"
                f"🏷 Категория: {r['category']}{shop_label}\n"
                f"💸 Сумма: {amount_str}\n"
                f"📝 Описание: {r['description']}\n"
                f"📅 Дата: {r['date']}",
            )
            if last_row > 0:
                await callback.message.answer("Категория верна?", reply_markup=expense_recorded_kb())
        else:
            total_rub = sum(r["amount_rub"] for r in records)
            lines = [f"✅ Записано {len(records)} расхода, итого *{total_rub:,.0f} ₽*\n"]
            for r in records:
                shop_label = f" ({r['shop']})" if r["shop"] else ""
                amount_str = format_amount_with_rub(r["amount"], r["currency"], r["amount_rub"])
                lines.append(f"• {r['category']}{shop_label} — {amount_str}")
            await callback.message.edit_text("\n".join(lines), parse_mode="Markdown")
    else:
        await callback.message.edit_text("❌ Отменено.")

    await callback.answer()


# --- Текстовые хендлеры ---

@dp.message(Mode.expense)
@only_allowed
async def handle_expense_text(message: Message):
    if not message.text:
        return
    await _process_expense_text(message, message.text)


@dp.message(Mode.analytics)
@only_allowed
async def handle_analytics_chat(message: Message, state: FSMContext):
    if not message.text:
        return
    await _process_analytics_chat(message, message.text, state)


@dp.message()
@only_allowed
async def handle_income(message: Message, state: FSMContext):
    if not message.text:
        return
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Выбери режим работы:", reply_markup=main_menu_kb())
        return
    await _process_income_text(message, message.text)


# --- Обработка доходов ---

async def _process_income_text(message: Message, text: str):
    processing_msg = await message.answer("⏳ Обрабатываю...")
    parsed = await parse_income(text)
    await processing_msg.delete()

    if not parsed:
        await message.answer(
            "Не удалось распознать сумму. Попробуй написать иначе, например:\n"
            "«Получил 10 000 от Петрова за консультацию»"
        )
        return

    sheets.add_record(parsed)
    await message.answer(
        f"✅ Доход записан!\n\n"
        f"👤 Клиент: {parsed['client']}\n"
        f"💰 Сумма: {parsed['amount']:,.0f} ₽\n"
        f"📝 Описание: {parsed['description']}\n"
        f"📅 Дата: {parsed['date']}"
    )


# --- Обработка расходов ---

async def _process_expense_text(message: Message, text: str):
    processing_msg = await message.answer("⏳ Обрабатываю...")
    records = await parse_expense_text(text)
    await processing_msg.delete()

    if not records:
        await message.answer(
            "Не удалось распознать сумму. Попробуй написать иначе, например:\n"
            "«Потратил 1500 в Магните на продукты»"
        )
        return

    last_row = -1
    for record in records:
        amount_rub, rate = await to_rub(record["amount"], record["currency"])
        record["amount_rub"] = amount_rub
        record["rate"] = rate
        last_row = sheets.add_expense_record(record)

    if len(records) == 1:
        r = records[0]
        shop_label = f" ({r['shop']})" if r["shop"] else ""
        amount_str = format_amount_with_rub(r["amount"], r["currency"], r["amount_rub"])
        if last_row > 0:
            correction_targets[message.from_user.id] = last_row
        await message.answer(
            f"✅ Расход записан!\n\n"
            f"🏷 Категория: {r['category']}{shop_label}\n"
            f"💸 Сумма: {amount_str}\n"
            f"📝 Описание: {r['description']}\n"
            f"📅 Дата: {r['date']}",
            reply_markup=expense_recorded_kb() if last_row > 0 else None,
        )
    else:
        total_rub = sum(r["amount_rub"] for r in records)
        lines = [f"✅ Записано {len(records)} расхода, итого *{total_rub:,.0f} ₽*\n"]
        for r in records:
            shop_label = f" ({r['shop']})" if r["shop"] else ""
            amount_str = format_amount_with_rub(r["amount"], r["currency"], r["amount_rub"])
            lines.append(f"• {r['category']}{shop_label} — {amount_str}")
        await message.answer("\n".join(lines), parse_mode="Markdown")


# --- Коррекция категории ---

@dp.callback_query(F.data == "correct:pick")
@only_allowed
async def cb_correct_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in correction_targets:
        await callback.answer("Нет активного расхода для коррекции.", show_alert=True)
        return
    await callback.message.answer("Выбери правильную категорию:", reply_markup=category_picker_kb())
    await callback.answer()


@dp.callback_query(F.data.startswith("cat:"))
@only_allowed
async def cb_category_pick(callback: CallbackQuery):
    user_id = callback.from_user.id
    category = callback.data.split("cat:")[1]
    row = correction_targets.pop(user_id, None)
    if row and row > 0:
        sheets.update_expense_category(row, category)
        await callback.message.edit_text(f"✅ Категория изменена на: *{category}*", parse_mode="Markdown")
    else:
        await callback.answer("Не удалось обновить — запись не найдена.", show_alert=True)
    await callback.answer()


# --- Аналитический чат ---

async def _process_analytics_chat(message: Message, text: str, state: FSMContext):
    data = await state.get_data()
    history: list[dict] = data.get("analytics_history", [])
    income = data.get("analytics_income", [])
    expenses = data.get("analytics_expenses", [])
    period = data.get("analytics_period", "")

    if not income and not expenses:
        await message.answer(
            "Сначала выбери период для анализа:",
            reply_markup=analytics_kb(),
        )
        return

    history.append({"role": "user", "content": text})
    processing_msg = await message.answer("⏳ Думаю...")

    response = await chat_analytics(history, income, expenses, period)
    history.append({"role": "assistant", "content": response})

    await state.update_data(analytics_history=history)
    await processing_msg.delete()
    await message.answer(response, parse_mode="Markdown")


async def main():
    logging.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
