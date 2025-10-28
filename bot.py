# bot.py
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from decouple import config
import csv
import os

# --- Читаем настройки из .env ---
BOT_TOKEN = config("BOT_TOKEN")
ADMIN_ID = config("ADMIN_ID", default=None, cast=int)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# --- Определяем состояния анкеты ---
class RepairRequest(StatesGroup):
    name = State()
    phone = State()
    device_type = State()
    problem_description = State()
    preferred_time = State()
    confirm = State()

# --- Инициализация файла CSV ---
CSV_FILE = "repair_requests.csv"
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Имя", "Телефон", "Тип устройства", "Описание проблемы", "Предпочитаемое время"])

# --- Клавиатура с встроенными кнопками для /start ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Заявка на ремонт"), KeyboardButton(text="Контакты")]
    ],
    resize_keyboard=True,  # Адаптирует размер под экран
    one_time_keyboard=True  # Клавиатура исчезает после нажатия
)

# --- Клавиатура для подтверждения анкеты ---
confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="✅ Да"), KeyboardButton(text="❌ Нет")]
    ],
    resize_keyboard=True,
    one_time_keyboard=True
)

# --- Обработчик команды /start (с кнопками) ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Это бот сервисного центра по ремонту девайсов. Выберите опцию:",
        reply_markup=main_keyboard
    )

# --- Обработка нажатий на кнопки (текстовые сообщения) ---
@router.message(F.text == "Заявка на ремонт")
async def start_request_button(message: Message, state: FSMContext):
    await message.answer("Как вас зовут?")
    await state.set_state(RepairRequest.name)

@router.message(F.text == "Контакты")
async def show_contacts(message: Message):
    await message.answer("Наш адрес: ул. Техническая, 10. Тел: +7 (123) 456-78-90")

# --- Начало анкеты: /request или кнопка ---
@router.message(Command("request"))
async def start_request(message: Message, state: FSMContext):
    await message.answer("Как вас зовут?")
    await state.set_state(RepairRequest.name)

# --- Получение имени ---
@router.message(RepairRequest.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите ваш номер телефона (например: +7XXXXXXXXXX)")
    await state.set_state(RepairRequest.phone)

# --- Получение телефона ---
@router.message(RepairRequest.phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not (phone.startswith('+') and phone[1:].isdigit()) and not phone.isdigit():
        await message.answer("Пожалуйста, введите номер телефона в формате цифр.")
        return
    await state.update_data(phone=phone)
    await message.answer("Какой тип устройства нужно отремонтировать? (Например: смартфон, ноутбук, планшет)")
    await state.set_state(RepairRequest.device_type)

# --- Получение типа устройства ---
@router.message(RepairRequest.device_type)
async def get_device_type(message: Message, state: FSMContext):
    await state.update_data(device_type=message.text)
    await message.answer("Опишите проблему (например: не включается, разбит экран)")
    await state.set_state(RepairRequest.problem_description)

# --- Получение описания проблемы ---
@router.message(RepairRequest.problem_description)
async def get_problem_description(message: Message, state: FSMContext):
    await state.update_data(problem_description=message.text)
    await message.answer("Укажите предпочитаемое время для звонка или визита (например: завтра после 14:00, или 'любое')")
    await state.set_state(RepairRequest.preferred_time)

# --- Получение времени и показ кнопок подтверждения ---
@router.message(RepairRequest.preferred_time)
async def get_preferred_time(message: Message, state: FSMContext):
    await state.update_data(preferred_time=message.text)
    data = await state.get_data()
    text = (
        f"Проверьте данные заявки:\n\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Тип устройства: {data['device_type']}\n"
        f"Проблема: {data['problem_description']}\n"
        f"Время: {data['preferred_time']}\n\n"
        f"Всё верно?"
    )
    await message.answer(text, reply_markup=confirm_keyboard)
    await state.set_state(RepairRequest.confirm)

# --- Обработка подтверждения "Да" ---
@router.message(RepairRequest.confirm, F.text == "✅ Да")
async def confirm_yes(message: Message, state: FSMContext):
    data = await state.get_data()
    with open(CSV_FILE, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([data['name'], data['phone'], data['device_type'], data['problem_description'], data['preferred_time']])
    await message.answer("✅ Заявка сохранена! Мы свяжемся с вами скоро.")
    if ADMIN_ID:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=f"🆕 Новая заявка на ремонт!\n\nИмя: {data['name']}\nТелефон: {data['phone']}\nУстройство: {data['device_type']}\nПроблема: {data['problem_description']}\nВремя: {data['preferred_time']}"
        )
    await state.clear()

# --- Обработка "Нет" ---
@router.message(RepairRequest.confirm, F.text == "❌ Нет")
async def confirm_no(message: Message, state: FSMContext):
    await message.answer("Хорошо, давай заполним заново!\nКак вас зовут?")
    await state.set_state(RepairRequest.name)

# --- Эхо-обработчик для всех сообщений вне анкеты ---
@router.message()
async def echo_message(message: Message, state: FSMContext):
    if not await state.get_state():
        await message.answer(f"Вы написали: {message.text}")

# --- Запуск бота ---
async def main():
    dp.include_router(router)
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())