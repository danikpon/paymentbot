import asyncio
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from aiogram.dispatcher.router import Router

# Фильтры для /start и других команд (Aiogram 3.x)
from aiogram.filters import CommandStart, Command

BOT_TOKEN = os.getenv("BOT_TOKEN") or "ВАШ_ТОКЕН"   # <-- вставьте реальный токен
PAYMENT_URL = "https://example.com/payment_link"    # <-- ваша ссылка на оплату
COST_PER_MONTH = 50

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

scheduler = AsyncIOScheduler()

# "База" в памяти
# user_data[user_id] = { "waiting_for_amount": bool, "amount": int, "period": int }
user_data = {}


@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обработка команды /start. Предлагаем оплату 50 руб или ввод своей суммы.
    """
    # Создаём Inline-клавиатуру как список списков кнопок
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Оплатить 50 рублей", callback_data="pay_50"),
                InlineKeyboardButton(text="Своя сумма", callback_data="custom_amount")
            ]
        ]
    )
    await message.answer(
        "Привет! Я помогу отслеживать оплату. Выберите сумму для оплаты:",
        reply_markup=keyboard
    )

    user_data[message.from_user.id] = {
        "waiting_for_amount": False,
        "amount": 0,
        "period": 0
    }


@router.callback_query(lambda c: c.data == "pay_50")
async def callback_pay_50(callback: CallbackQuery):
    """
    Когда пользователь нажал «Оплатить 50 рублей».
    """
    user_id = callback.from_user.id
    user_data[user_id] = {
        "waiting_for_amount": False,
        "amount": 50,
        "period": 1
    }

    await callback.message.answer("Выбрано 50 рублей. Напоминание будет раз в месяц.")
    await callback.answer()  # Убираем "часики" в интерфейсе Telegram

    schedule_reminder(user_id)


@router.callback_query(lambda c: c.data == "custom_amount")
async def callback_custom_amount(callback: CallbackQuery):
    """
    Когда пользователь нажал «Своя сумма».
    Просим ввести сумму сообщением.
    """
    user_id = callback.from_user.id
    user_data[user_id] = {
        "waiting_for_amount": True,
        "amount": 0,
        "period": 0
    }

    await callback.message.answer("Пожалуйста, введите сумму (например, 100, 500р, 1к).")
    await callback.answer()


@router.message(F.text)
async def handle_custom_amount_message(message: Message):
    """
    Обрабатываем обычные сообщения. Если бот «ждёт сумму», пытаемся её распарсить.
    """
    user_id = message.from_user.id

    # Проверяем, действительно ли мы ждали сумму
    if user_id not in user_data or not user_data[user_id]["waiting_for_amount"]:
        return

    input_text = message.text.lower().replace(" ", "").replace("руб", "").replace("р", "")
    # Преобразование вида "1к" → "1000"
    if "к" in input_text:
        input_text = input_text.replace("к", "000")

    if not input_text.isdigit():
        await message.answer("Пожалуйста, введите корректную сумму (например, 1000, 1к, 500руб).")
        return

    amount = int(input_text)
    period = amount // COST_PER_MONTH

    if period < 1:
        await message.answer(
            f"Сумма {amount} рублей недостаточна для оплаты хотя бы одного месяца.\n"
            f"Стоимость месяца: {COST_PER_MONTH} руб."
        )
        return

    user_data[user_id] = {
        "waiting_for_amount": False,
        "amount": amount,
        "period": period
    }

    await message.answer(
        f"Вы оплатили {amount} рублей, чего хватит на {period} месяц(ев). "
        f"Напоминания будут приходить раз в {period} месяц(ев)."
    )
    schedule_reminder(user_id)


def schedule_reminder(user_id: int):
    """
    Планируем отправку напоминания через period «месяцев».
    Условно month = 4 недели.
    """
    user_info = user_data.get(user_id)
    if not user_info:
        return

    amount = user_info["amount"]
    period = user_info["period"]

    async def send_reminder():
        await bot.send_message(
            user_id,
            f"Напоминание: пора оплатить {amount} рублей. Нажмите кнопку, чтобы оплатить.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)]
                ]
            )
        )

    # Примерно: 1 месяц = 4 недели
    scheduler.add_job(send_reminder, "interval", weeks=period * 4)


async def main():
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
