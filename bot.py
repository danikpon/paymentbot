import sqlite3
import re
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Инициализация бота
BOT_TOKEN = "ВАШ_ТОКЕН"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)
scheduler = AsyncIOScheduler()

# Константы
COST_PER_MONTH = 50  # Стоимость одного месяца (в рублях)

# Настройка базы данных
conn = sqlite3.connect("payments.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    amount INTEGER,
    period INTEGER,
    next_reminder TEXT
)
""")
conn.commit()

# Обработчик команды /start
@dp.message_handler(commands=["start"])
async def start_command(message: types.Message):
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("Оплатить 50 рублей", callback_data="pay_50"),
        InlineKeyboardButton("Своя сумма", callback_data="custom_amount")
    )
    await message.answer(
        "Привет! Я помогу отслеживать оплату. Выберите сумму для оплаты:",
        reply_markup=keyboard
    )

# Обработчик кнопок оплаты
@dp.callback_query_handler(lambda call: call.data.startswith("pay"))
async def handle_payment(call: types.CallbackQuery):
    if call.data == "pay_50":
        amount = 50
        await call.message.answer("Вот ссылка для оплаты: ВАША_ССЫЛКА")
        await set_payment_period(call.from_user.id, amount)
    elif call.data == "custom_amount":
        await call.message.answer(
            "Введите сумму для оплаты (например: 1000, 1 000, 1000р, 1к, 1000 рублей):"
        )

# Обработка пользовательского ввода суммы
@dp.message_handler()
async def handle_custom_amount(message: types.Message):
    user_input = message.text
    amount = parse_amount(user_input)

    if amount is None:
        await message.answer(
            "Не удалось распознать сумму. Укажите число, например: 1000, 1 000, 1к, 1000 рублей."
        )
        return

    # Рассчитываем количество месяцев
    period = amount // COST_PER_MONTH
    if period < 1:
        await message.answer(
            f"Сумма {amount} рублей слишком мала для оплаты хотя бы одного месяца (минимум {COST_PER_MONTH} рублей)."
        )
        return

    await message.answer(
        f"Вы оплатили {amount} рублей, чего хватит на {period} месяцев. Напоминание будет приходить раз в {period} месяцев."
    )
    await set_payment_period(message.from_user.id, amount, period)

# Установка периода оплаты
async def set_payment_period(user_id, amount, period):
    # Сохраняем данные пользователя
    cursor.execute("""
        INSERT OR REPLACE INTO users (user_id, amount, period, next_reminder)
        VALUES (?, ?, ?, datetime('now', ? || ' months'))
    """, (user_id, amount, period, period))
    conn.commit()

    # Планируем напоминание
    schedule_reminder(user_id, period)

# Планирование напоминания
def schedule_reminder(user_id, period):
    def send_reminder():
        cursor.execute("SELECT amount FROM users WHERE user_id = ?", (user_id,))
        amount = cursor.fetchone()[0]
        bot.send_message(
            user_id,
            f"Напоминание: пора оплатить {amount} рублей. Нажмите кнопку, чтобы оплатить.",
            reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("Оплатить", url="ВАША_ССЫЛКА")
            )
        )
        # Обновляем дату следующего напоминания
        cursor.execute("UPDATE users SET next_reminder = datetime('now', ? || ' months') WHERE user_id = ?",
                       (period, user_id))
        conn.commit()
    scheduler.add_job(send_reminder, "date", run_date=f"datetime('now', {period} || ' months')")

# Функция для обработки суммы
def parse_amount(input_text):
    # Убираем пробелы и символы валют
    text = input_text.lower().replace(" ", "").replace("руб", "").replace("р", "")

    # Если пользователь использует "1к" или "2к", преобразуем в тысячи
    if "к" in text:
        text = text.replace("к", "000")
# Проверяем, является ли текст числом
    if text.isdigit():
        return int(text)

    return None

# Запуск планировщика
scheduler.start()

# Запуск бота
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
