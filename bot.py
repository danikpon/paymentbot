import asyncio
import os
from datetime import datetime, timedelta

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from aiogram.dispatcher.router import Router
from aiogram.filters import CommandStart

BOT_TOKEN = os.getenv("BOT_TOKEN") or "ВАШ_ТОКЕН"    # <-- Вставьте сюда реальный токен
PAYMENT_URL = "https://example.com/payment_link"     # <-- Ваша ссылка на оплату
COST_PER_MONTH = 50

scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Moscow"))
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# user_data[user_id] = {
#   "waiting_for_amount": bool,       # Ждём ли мы обычную сумму?
#   "waiting_for_people_count": bool, # Ждём ли мы число людей?
#   "waiting_for_total_sum": bool,    # Ждём ли мы сумму для нескольких человек?
#   "people_count": int,             # Сколько человек?
#   "amount": int,                   # Общая сумма (для обычной логики) или рассчитанная сумма на 1 человека
#   "period": int,
#   "job_id": str|None
# }
user_data = {}


@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обработка команды /start. Предлагаем:
    1) Оплатить 50
    2) Своя сумма
    3) Оплата на нескольких человек
    """
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Оплатить 50 рублей", callback_data="pay_50"),
                InlineKeyboardButton(text="Своя сумма", callback_data="custom_amount"),
            ],
            [
                InlineKeyboardButton(text="Оплата на нескольких человек", callback_data="split_payment")
            ]
        ]
    )
    await message.answer(
        "Привет! Я помогу отслеживать оплату. Выберите подходящий вариант:",
        reply_markup=keyboard
    )
    user_data[message.from_user.id] = {
        "waiting_for_amount": False,
        "waiting_for_people_count": False,
        "waiting_for_total_sum": False,
        "people_count": 0,
        "amount": 0,
        "period": 0,
        "job_id": None
    }


@router.callback_query(lambda c: c.data == "pay_50")
async def callback_pay_50(callback: CallbackQuery):
    """
    Нажатие «Оплатить 50 рублей».
    Создаём одноразовую задачу, которая через 1 минуту пришлёт напоминание.
    """
    user_id = callback.from_user.id
    user_data[user_id] = {
        "waiting_for_amount": False,
        "waiting_for_people_count": False,
        "waiting_for_total_sum": False,
        "people_count": 0,
        "amount": 50,
        "period": 1,   # 1 минута (поскольку 50//50 = 1)
        "job_id": None
    }

    await callback.message.answer(
        "Выбрано 50 рублей. Можно оплатить по кнопке.\n"
        "Через 1 минуту я пришлю напоминание (для теста).",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)
                ]
            ]
        )
    )
    await callback.answer()
    schedule_one_time_reminder(user_id)


@router.callback_query(lambda c: c.data == "custom_amount")
async def callback_custom_amount(callback: CallbackQuery):
    """
    Нажатие «Своя сумма». Просим ввести сумму сообщением.
    """
    user_id = callback.from_user.id
    user_data[user_id] = {
        "waiting_for_amount": True,
        "waiting_for_people_count": False,
        "waiting_for_total_sum": False,
        "people_count": 0,
        "amount": 0,
        "period": 0,
        "job_id": None
    }
    await callback.message.answer("Пожалуйста, введите сумму (например, 100, 500р, 1к).")
    await callback.answer()


@router.callback_query(lambda c: c.data == "split_payment")
async def callback_split_payment(callback: CallbackQuery):
    """
    Нажатие «Оплата на нескольких человек».
    Сначала просим ввести, на скольких человек.
    """
    user_id = callback.from_user.id
    user_data[user_id] = {
        "waiting_for_amount": False,
        "waiting_for_people_count": True,   # <-- ждём кол-во человек
        "waiting_for_total_sum": False,
        "people_count": 0,
        "amount": 0,
        "period": 0,
        "job_id": None
    }
    await callback.message.answer("На скольких человек будет оплата? (Введите число)")
    await callback.answer()


@router.message(F.text)
async def handle_user_text(message: Message):
    """
    Этот хендлер обрабатывает ВСЕ простые сообщения.
    Проверяем, чего мы ждём: 
    - waiting_for_amount (обычная сумма)
    - waiting_for_people_count (сколько человек?)
    - waiting_for_total_sum (какова общая сумма, чтобы поделить?)
    """
    user_id = message.from_user.id
    if user_id not in user_data:
        return  # пользователь не проходил /start

    data = user_data[user_id]

    # 1) Обычная логика "Своя сумма"
    if data["waiting_for_amount"]:
        await process_custom_amount(message)
        return

    # 2) Если ждём кол-во человек
    if data["waiting_for_people_count"]:
        # Пытаемся считать кол-во человек
        text = message.text.strip()
        if not text.isdigit():
            await message.answer("Пожалуйста, введите число (количество человек).")
            return

        people = int(text)
        if people < 1:
            await message.answer("Количество человек должно быть больше 0.")
            return

        # Сохраняем
        data["waiting_for_people_count"] = False
        data["people_count"] = people
        data["waiting_for_total_sum"] = True  # теперь ждём общую сумму
        await message.answer(
            f"Хорошо, {people} человек.\nТеперь введите общую сумму (например, 300, 1500р)."
        )
        return

    # 3) Если ждём общую сумму для split_payment
    if data["waiting_for_total_sum"]:
        await process_split_total_sum(message)
        return

    # Если ничего не ждём — игнорируем (или ответим что-то)
    # await message.answer("Я не жду никаких ответов в данный момент.")


async def process_custom_amount(message: Message):
    """
    Логика обработки «Своя сумма» (ожидаем одно число).
    """
    user_id = message.from_user.id
    data = user_data[user_id]

    input_text = message.text.lower().replace(" ", "").replace("руб", "").replace("р", "")
    if "к" in input_text:
        input_text = input_text.replace("к", "000")

    if not input_text.isdigit():
        await message.answer("Пожалуйста, введите корректную сумму (например, 1000, 1к, 500руб).")
        return

    amount = int(input_text)
    period = amount // COST_PER_MONTH
    if period < 1:
        await message.answer(
            f"Сумма {amount} рублей недостаточна для оплаты хотя бы одного периода.\n"
            f"Стоимость 'периода': {COST_PER_MONTH} руб."
        )
        return

    # Сохраняем
    data["waiting_for_amount"] = False
    data["amount"] = amount
    data["period"] = period
    data["people_count"] = 0
    data["waiting_for_people_count"] = False
    data["waiting_for_total_sum"] = False

    # Ответ и планирование
    await message.answer(
        f"Сумма {amount} руб. Это {period} минут(ы) 'подписки' (для теста).\n"
        "Нажмите кнопку, чтобы оплатить. Через указанный срок я пришлю напоминание.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)]
            ]
        )
    )
    schedule_one_time_reminder(user_id)


async def process_split_total_sum(message: Message):
    """
    Логика обработки «общей суммы», если выбрали "Оплата на нескольких человек".
    Мы делим введённую сумму на data["people_count"] и считаем период.
    """
    user_id = message.from_user.id
    data = user_data[user_id]

    input_text = message.text.lower().replace(" ", "").replace("руб", "").replace("р", "")
    if "к" in input_text:
        input_text = input_text.replace("к", "000")

    if not input_text.isdigit():
        await message.answer("Пожалуйста, введите корректную сумму (например, 1500, 1к, 500руб).")
        return

    total_sum = int(input_text)
    people = data["people_count"]
    if people < 1:
        await message.answer("Количество человек должно быть >=1. Попробуйте заново.")
        return

    # Считаем сумму на 1 человека
    sum_per_person = total_sum // people
    period = sum_per_person // COST_PER_MONTH

    if period < 1:
        await message.answer(
            f"Сумма {total_sum} руб. на {people} человек = {sum_per_person} руб. на человека.\n"
            f"Недостаточно для оплаты хотя бы одного периода (нужно >= {COST_PER_MONTH} руб. на человека).\n"
            "Попробуйте увеличить сумму."
        )
        return

    # Сохраняем
    data["waiting_for_total_sum"] = False
    data["people_count"] = people
    data["amount"] = sum_per_person
    data["period"] = period
    data["waiting_for_amount"] = False
    data["waiting_for_people_count"] = False

    await message.answer(
        f"Итого на одного человека: {sum_per_person} руб.\n"
        f"Это {period} минут(ы) 'подписки' (для теста).\n"
        "Нажмите кнопку, чтобы оплатить.\n"
        "Через указанный срок я пришлю напоминание.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)]
            ]
        )
    )
    schedule_one_time_reminder(user_id)


def schedule_one_time_reminder(user_id: int):
    """
    Создаём одноразовое напоминание через period минут (для теста).
    Когда наступит время, бот пришлёт сообщение с кнопками:
    - «Оплатить 50 рублей»
    - «Своя сумма»
    - «Оплата на нескольких человек»
    - «Прекратить подписку»
    
    Если пользователь не нажал ничего — подписка не продлевается.
    """
    data = user_data.get(user_id)
    if not data:
        return

    period = data["period"]
    if period < 1:
        return

    run_date = datetime.now() + timedelta(minutes=period)
    job_id = f"reminder_{user_id}_{run_date.timestamp()}"
    data["job_id"] = job_id

    async def send_reminder():
        # Клавиатура с 4 кнопками
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="Оплатить 50 рублей", callback_data="pay_50_again"),
                    InlineKeyboardButton(text="Своя сумма", callback_data="custom_amount_again")
                ],
                [
                    InlineKeyboardButton(text="Оплата на нескольких человек", callback_data="split_payment_again")
                ],
                [
                    InlineKeyboardButton(text="Прекратить подписку", callback_data="stop_subscription")
                ]
            ]
        )
        await bot.send_message(
            user_id,
            "Напоминание! Время продлить подписку. Выберите вариант:",
            reply_markup=keyboard
        )

    scheduler.add_job(
        send_reminder,
        trigger="date",
        run_date=run_date,
        id=job_id,
        misfire_grace_time=3600
    )


@router.callback_query(lambda c: c.data in [
    "pay_50_again",
    "custom_amount_again",
    "split_payment_again",
    "stop_subscription"
])
async def callback_after_reminder(call: CallbackQuery):
    """
    Обработка кнопок после напоминания:
      - pay_50_again        (Оплатить 50 руб заново)
      - custom_amount_again (Своя сумма заново)
      - split_payment_again (Оплата на нескольких человек)
      - stop_subscription   (Прекратить подписку)
    """
    user_id = call.from_user.id
    action = call.data

    if action == "stop_subscription":
        # Пользователь прекратил подписку
        await call.message.answer("Вы прекратили подписку. Напоминаний больше не будет.")
        user_data[user_id] = {
            "waiting_for_amount": False,
            "waiting_for_people_count": False,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 0,
            "period": 0,
            "job_id": None
        }
        await call.answer()
        return

    if action == "pay_50_again":
        user_data[user_id] = {
            "waiting_for_amount": False,
            "waiting_for_people_count": False,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 50,
            "period": 1,
            "job_id": None
        }
        await call.message.answer(
            "Снова выбрано 50 рублей. Нажмите кнопку, чтобы оплатить.\n"
            "Через 1 минуту я пришлю напоминание.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)
                    ]
                ]
            )
        )
        await call.answer()
        schedule_one_time_reminder(user_id)

    elif action == "custom_amount_again":
        user_data[user_id] = {
            "waiting_for_amount": True,
            "waiting_for_people_count": False,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 0,
            "period": 0,
            "job_id": None
        }
        await call.message.answer("Введите новую сумму (например, 100, 500р, 1к).")
        await call.answer()

    elif action == "split_payment_again":
        # Аналогична логика «Оплата на нескольких человек»
        user_data[user_id] = {
            "waiting_for_amount": False,
            "waiting_for_people_count": True,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 0,
            "period": 0,
            "job_id": None
        }
        await call.message.answer("На скольких человек будет оплата? (Введите число)")
        await call.answer()


async def main():
    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
