# app.py
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from decouple import config
import csv
import os
import logging
import asyncio

# --- Настройка ---
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = config("BOT_TOKEN")
ADMIN_ID = config("ADMIN_ID", default=None, cast=int)
AMVERA_DOMAIN = config("AMVERA_APP_DOMAIN", default="localhost")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# --- Путь к CSV в /data ---
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
CSV_FILE = os.path.join(DATA_DIR, "repair_requests.csv")

# --- Инициализация CSV ---
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["Имя", "Телефон", "Тип устройства", "Описание проблемы", "Предпочитаемое время"])

# --- Клавиатуры ---
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Заявка на ремонт"), KeyboardButton(text="Контакты")]],
    resize_keyboard=True, one_time_keyboard=True
)
confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
    resize_keyboard=True, one_time_keyboard=True
)

# --- FSM ---
class RepairRequest(StatesGroup):
    name = State()
    phone = State()
    device_type = State()
    problem_description = State()
    preferred_time = State()
    confirm = State()

# --- Хендлеры ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer("Привет! Это бот сервисного центра. Выберите опцию:", reply_markup=main_keyboard)

@router.message(F.text == "Заявка на ремонт")
async def start_request(message: Message, state: FSMContext):
    await message.answer("Как вас зовут?")
    await state.set_state(RepairRequest.name)

@router.message(F.text == "Контакты")
async def show_contacts(message: Message):
    await message.answer("Адрес: ул. Техническая, 10\nТел: +7 (123) 456-78-90")

@router.message(Command("request"))
async def cmd_request(message: Message, state: FSMContext):
    await message.answer("Как вас зовут?")
    await state.set_state(RepairRequest.name)

@router.message(RepairRequest.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите номер телефона (например: +7XXXXXXXXXX)")
    await state.set_state(RepairRequest.phone)

@router.message(RepairRequest.phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not (phone.startswith('+') and phone[1:].isdigit()) and not phone.isdigit():
        await message.answer("Неверный формат. Пример: +79123456789")
        return
    await state.update_data(phone=phone)
    await message.answer("Какой тип устройства? (смартфон, ноутбук и т.д.)")
    await state.set_state(RepairRequest.device_type)

@router.message(RepairRequest.device_type)
async def get_device_type(message: Message, state: FSMContext):
    await state.update_data(device_type=message.text)
    await message.answer("Опишите проблему")
    await state.set_state(RepairRequest.problem_description)

@router.message(RepairRequest.problem_description)
async def get_problem_description(message: Message, state: FSMContext):
    await state.update_data(problem_description=message.text)
    await message.answer("Когда удобно связаться? (например: завтра после 14:00)")
    await state.set_state(RepairRequest.preferred_time)

@router.message(RepairRequest.preferred_time)
async def get_preferred_time(message: Message, state: FSMContext):
    await state.update_data(preferred_time=message.text)
    data = await state.get_data()
    text = (
        f"Проверьте заявку:\n\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {data['phone']}\n"
        f"Устройство: {data['device_type']}\n"
        f"Проблема: {data['problem_description']}\n"
        f"Время: {data['preferred_time']}\n\n"
        f"Всё верно?"
    )
    await message.answer(text, reply_markup=confirm_keyboard)
    await state.set_state(RepairRequest.confirm)

@router.message(RepairRequest.confirm, F.text == "Да")
async def confirm_yes(message: Message, state: FSMContext):
    data = await state.get_data()
    with open(CSV_FILE, mode='a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([data['name'], data['phone'], data['device_type'], data['problem_description'], data['preferred_time']])
    
    await message.answer("Заявка сохранена! Мы свяжемся с вами.", reply_markup=main_keyboard)
    
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"Новая заявка!\n\n" + "\n".join(f"{k}: {v}" for k, v in data.items()))
    
    await state.clear()

@router.message(RepairRequest.confirm, F.text == "Нет")
async def confirm_no(message: Message, state: FSMContext):
    await message.answer("Хорошо, начнём заново. Как вас зовут?")
    await state.set_state(RepairRequest.name)

# --- ПР 5: /export ---
@router.message(Command("export"))
async def export_csv(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    if not os.path.exists(CSV_FILE):
        await message.answer("Нет заявок")
        return
    await message.answer_document(FSInputFile(CSV_FILE), caption="Все заявки")

# --- Webhook ---
async def on_startup(app: web.Application):
    logging.info("Ожидание 120 секунд — Amvera полностью просыпается...")
    await asyncio.sleep(120)  # 120 СЕКУНД — ГАРАНТИРОВАННО
    domain = config('AMVERA_APP_DOMAIN')
    if not domain or domain == "localhost":
        logging.error("AMVERA_APP_DOMAIN НЕ ЗАДАН!")
        return
    webhook_url = f"https://{domain}/webhook"
    try:
        await bot.set_webhook(webhook_url)
        logging.info(f"WEBHOOK УСПЕШНО: {webhook_url}")
    except Exception as e:
        logging.error(f"ОШИБКА ВЕБХУКА: {e}")

async def on_shutdown(app: web.Application):
    try:
        await bot.delete_webhook()
        await bot.session.close()
        logging.info("WEBHOOK УДАЛЁН")
    except:
        pass

# --- Запуск ---
app = web.Application()
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
setup_application(app, dp, bot=bot)
dp.include_router(router)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8000)
