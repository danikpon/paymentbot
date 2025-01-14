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
    InlineKeyboardMarkup,
    BotCommand
)
from aiogram.dispatcher.router import Router
from aiogram.filters import CommandStart, Command

BOT_TOKEN = os.getenv("BOT_TOKEN") or "ВАШ_ТОКЕН"  # <-- Вставьте сюда реальный токен
PAYMENT_URL = "https://example.com/payment_link"   # <-- Ваша ссылка на оплату
COST_PER_MONTH = 50

# Планировщик с часовым поясом (например, Moscow). Замените при необходимости.
scheduler = AsyncIOScheduler(timezone=pytz.timezone("Europe/Moscow"))
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

"""
user_data[user_id] = {
  "waiting_for_amount": bool,        # Ждём ли «свою сумму»
  "waiting_for_people_count": bool,  # Ждём ли «кол-во человек»
  "waiting_for_total_sum": bool,     # Ждём ли «общую сумму» (split)
  "people_count": int,               # Сколько человек
  "amount": int,                     # Сумма (на 1 человека, если split)
  "period": int,                     # кол-во минут для теста
  "expire_date": datetime,           # время, когда заканчивается период
  "job_id": str|None                 # id задачи в APScheduler
}
"""

user_data = {}


@router.message(CommandStart())
async def cmd_start(message: Message):
    """
    Обработка команды /start. Предлагаем 3 варианта:
      - Оплатить 50
      - Своя сумма
      - Оплата на нескольких человек
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
        "Привет! Я помогу отслеживать оплату.\n"
        "Выберите подходящий вариант (или введите /check для проверки подписки):",
        reply_markup=keyboard
    )

    user_data[message.from_user.id] = {
        "waiting_for_amount": False,
        "waiting_for_people_count": False,
        "waiting_for_total_sum": False,
        "people_count": 0,
        "amount": 0,
        "period": 0,
        "expire_date": None,
        "job_id": None
    }


@router.message(Command("check"))
async def cmd_check(message: Message):
    """
    Команда /check — проверяет, сколько минут осталось до окончания текущего периода.
    """
    user_id = message.from_user.id
    data = user_data.get(user_id)
    if not data:
        await message.answer("Вы ещё не начали подписку. Введите /start.")
        return

    expire_date = data.get("expire_date")
    if not expire_date:
        await message.answer("У вас нет активной подписки.")
        return

    now = datetime.now()
    if now >= expire_date:
        await message.answer("Срок вашей подписки уже истёк.")
        return

    # Сколько осталось в минутах (для тестового примера)
    delta = expire_date - now
    minutes_left = int(delta.total_seconds() // 60)
    await message.answer(f"До окончания подписки осталось ~ {minutes_left} мин(ут).")


@router.callback_query(lambda c: c.data == "pay_50")
async def callback_pay_50(callback: CallbackQuery):
    """
    Нажатие «Оплатить 50 рублей».
    Создаём одноразовую задачу через 1 минуту (50/50=1), указываем expire_date.
    """
    user_id = callback.from_user.id
    period = 1  # минута

    expire_date = datetime.now() + timedelta(minutes=period)
    user_data[user_id] = {
        "waiting_for_amount": False,
        "waiting_for_people_count": False,
        "waiting_for_total_sum": False,
        "people_count": 0,
        "amount": 50,
        "period": period,
        "expire_date": expire_date,
        "job_id": None
    }

    await callback.message.answer(
        "Выбрано 50 рублей. Можно оплатить по кнопке.\n"
        "Через 1 минуту я пришлю напоминание (для теста).",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)]
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
        "expire_date": None,
        "job_id": None
    }

    await callback.message.answer("Пожалуйста, введите сумму (например, 100, 500р, 1к).")
    await callback.answer()


@router.callback_query(lambda c: c.data == "split_payment")
async def callback_split_payment(callback: CallbackQuery):
    """
    Нажатие «Оплата на нескольких человек». Сначала спрашиваем кол-во человек.
    """
    user_id = callback.from_user.id
    user_data[user_id] = {
        "waiting_for_amount": False,
        "waiting_for_people_count": True,
        "waiting_for_total_sum": False,
        "people_count": 0,
        "amount": 0,
        "period": 0,
        "expire_date": None,
        "job_id": None
    }

    await callback.message.answer("На скольких человек будет оплата? (Введите число)")
    await callback.answer()


@router.message(F.text)
async def handle_user_text(message: Message):
    """
    Обрабатываем текст пользователя. Смотрим, что мы ждём:
    - waiting_for_amount (своя сумма)
    - waiting_for_people_count (кол-во человек)
    - waiting_for_total_sum (общая сумма для split)
    """
    user_id = message.from_user.id
    data = user_data.get(user_id, {})

    if data.get("waiting_for_amount"):
        await process_custom_amount(message)
        return

    if data.get("waiting_for_people_count"):
        # Просили кол-во человек
        if not message.text.isdigit():
            await message.answer("Пожалуйста, введите число (количество человек).")
            return

        people = int(message.text)
        if people < 1:
            await message.answer("Количество человек должно быть > 0.")
            return

        data["waiting_for_people_count"] = False
        data["people_count"] = people
        data["waiting_for_total_sum"] = True
        await message.answer(f"Хорошо, {people} человек.\nТеперь введите общую сумму (например, 300, 1500р).")
        return

    if data.get("waiting_for_total_sum"):
        await process_split_total_sum(message)
        return


async def process_custom_amount(message: Message):
    """
    Логика «Своя сумма». Вычисляем период = amount // COST_PER_MONTH.
    Если >=1, запоминаем expire_date и планируем.
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
            f"Стоимость периода: {COST_PER_MONTH} руб."
        )
        return

    expire_date = datetime.now() + timedelta(minutes=period)
    data.update({
        "waiting_for_amount": False,
        "amount": amount,
        "period": period,
        "expire_date": expire_date
    })

    await message.answer(
        f"Сумма {amount} руб. Это {period} минут(ы) 'подписки'.\n"
        "Нажмите кнопку, чтобы оплатить. После этого через заданный срок придёт напоминание.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)]
            ]
        )
    )
    schedule_one_time_reminder(user_id)


async def process_split_total_sum(message: Message):
    """
    Логика «Оплата на нескольких человек»:
    - user_data[user_id]["people_count"] = N
    - Вводим общую сумму, делим на N => sum_per_person
    - period = sum_per_person // COST_PER_MONTH
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
    sum_per_person = total_sum // people if people > 0 else 0
    period = sum_per_person // COST_PER_MONTH

    if period < 1:
        await message.answer(
            f"Сумма {total_sum} руб. на {people} человек = {sum_per_person} руб. на человека.\n"
            f"Недостаточно для оплаты хотя бы одного периода (>= {COST_PER_MONTH} руб. на человека).\n"
            "Попробуйте увеличить сумму."
        )
        return

    expire_date = datetime.now() + timedelta(minutes=period)
    data.update({
        "waiting_for_total_sum": False,
        "amount": sum_per_person,
        "period": period,
        "expire_date": expire_date
    })

    await message.answer(
        f"Итого на одного человека: {sum_per_person} руб.\n"
        f"Это {period} минут подписки.\n"
        "Нажмите кнопку, чтобы оплатить.\n"
        "Через этот срок придёт напоминание.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)]
            ]
        )
    )
    schedule_one_time_reminder(user_id)


def schedule_one_time_reminder(user_id: int):
    """
    Создаём ОДНОРАЗОВОЕ напоминание (trigger='date'):
      run_date = now + period (в минутах)
    Когда наступит время, отправляем сообщение с 4 кнопками:
    - Оплатить 50
    - Своя сумма
    - Оплата на нескольких человек
    - Прекратить подписку
    """
    data = user_data.get(user_id)
    if not data:
        return

    period = data["period"]
    expire_date = data["expire_date"]
    if not expire_date or period < 1:
        return

    # Генерируем ID задачи (не обязательно)
    run_date = expire_date
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
            "Напоминание! Время продлить подписку. Выберите вариант или введите /check чтобы узнать детали:",
            reply_markup=keyboard
        )
        # Если пользователь не нажал ничего — подписка не продлевается.

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
    Обработка нажатия кнопок после напоминания:
      - pay_50_again
      - custom_amount_again
      - split_payment_again
      - stop_subscription
    """
    user_id = call.from_user.id
    action = call.data

    if action == "stop_subscription":
        # Прекратить подписку
        await call.message.answer("Подписка прекращена. Напоминаний больше не будет.")
        user_data[user_id] = {
            "waiting_for_amount": False,
            "waiting_for_people_count": False,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 0,
            "period": 0,
            "expire_date": None,
            "job_id": None
        }
        await call.answer()
        return

    if action == "pay_50_again":
        period = 1
        expire_date = datetime.now() + timedelta(minutes=period)
        user_data[user_id] = {
            "waiting_for_amount": False,
            "waiting_for_people_count": False,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 50,
            "period": period,
            "expire_date": expire_date,
            "job_id": None
        }
        await call.message.answer(
            "Снова выбрано 50 рублей. Нажмите кнопку, чтобы оплатить.\n"
            "Через 1 минуту я пришлю новое напоминание.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="Оплатить", url=PAYMENT_URL)
                    ]
                ]
            )
        )
        schedule_one_time_reminder(user_id)
        await call.answer()

    elif action == "custom_amount_again":
        user_data[user_id] = {
            "waiting_for_amount": True,
            "waiting_for_people_count": False,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 0,
            "period": 0,
            "expire_date": None,
            "job_id": None
        }
        await call.message.answer("Введите новую сумму (например, 100, 500р, 1к).")
        await call.answer()

    elif action == "split_payment_again":
        user_data[user_id] = {
            "waiting_for_amount": False,
            "waiting_for_people_count": True,
            "waiting_for_total_sum": False,
            "people_count": 0,
            "amount": 0,
            "period": 0,
            "expire_date": None,
            "job_id": None
        }
        await call.message.answer("На скольких человек будет оплата? (Введите число)")
        await call.answer()


async def main():
    # Настраиваем команды, чтобы в меню бота были /start и /check
    commands = [
        BotCommand(command="start", description="Начать работу"),
        BotCommand(command="check", description="Проверить подписку")
    ]
    await bot.set_my_commands(commands)

    scheduler.start()
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
