from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# --- CSV ---
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
CSV_FILE = os.path.join(DATA_DIR, "repair_requests.csv")

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        csv.writer(f).writerow(["ID", "Имя", "Телефон", "Устройство", "Проблема", "Время"])

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

# --- Глобальные данные ---
request_counter = 0
requests_data = {}
LOGIN_URL = ""  # Будет заполнено в on_startup

# --- Загрузка заявок ---
def load_requests():
    global request_counter, requests_data
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) == 6:
                    req_id = int(row[0])
                    requests_data[req_id] = row[1:]
                    request_counter = max(request_counter, req_id)

load_requests()

# --- Хендлеры ---
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Добро пожаловать в **сервисный центр «TechFix»**!\n\n"
        "Я помогу вам оформить заявку на ремонт.\n\n"
        "Выберите действие:",
        reply_markup=main_keyboard
    )

@router.message(F.text == "Заявка на ремонт")
async def start_request(message: Message, state: FSMContext):
    await message.answer("**Как вас зовут?**")
    await state.set_state(RepairRequest.name)

@router.message(F.text == "Контакты")
async def show_contacts(message: Message):
    await message.answer(
        "**Наши контакты:**\n\n"
        "Адрес: **ул. Техническая, 10**\n"
        "Телефон: **+7 (123) 456-78-90**\n"
        "Часы работы: **Пн–Пт: 10:00–19:00**\n\n"
        "Мы всегда рады помочь!"
    )

@router.message(RepairRequest.name)
async def get_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("**Отлично!**\n\nВведите ваш **номер телефона**:\n\n"
                         "Формат: `+79123456789` или `89123456789`")
    await state.set_state(RepairRequest.phone)

@router.message(RepairRequest.phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not (phone.startswith('+') and phone[1:].isdigit()) and not phone.isdigit():
        await message.answer("**Неверный формат!**\n\n"
                             "Пожалуйста, введите номер в формате:\n"
                             "`+79123456789`")
        return
    await state.update_data(phone=phone)
    await message.answer("**Какое устройство нужно починить?**\n\n"
                         "Например: *смартфон Samsung*, *ноутбук Lenovo*")
    await state.set_state(RepairRequest.device_type)

@router.message(RepairRequest.device_type)
async def get_device_type(message: Message, state: FSMContext):
    await state.update_data(device_type=message.text)
    await message.answer("**Опишите проблему подробно:**\n\n"
                         "Например:\n"
                         "• Не включается\n"
                         "• Разбит экран\n"
                         "• Не заряжается")
    await state.set_state(RepairRequest.problem_description)

@router.message(RepairRequest.problem_description)
async def get_problem_description(message: Message, state: FSMContext):
    await state.update_data(problem_description=message.text)
    await message.answer("**Когда вам удобно принять звонок?**\n\n"
                         "Например:\n"
                         "• Завтра после 14:00\n"
                         "• Вечером в будни")
")
    await state.set_state(RepairRequest.preferred_time)

@router.message(RepairRequest.preferred_time)
async def get_preferred_time(message: Message, state: FSMContext):
    await state.update_data(preferred_time=message.text)
    data = await state.get_data()
    text = (
        "**Проверьте вашу заявку:**\n\n"
        f"**Имя:** {data['name']}\n"
        f"**Телефон:** `{data['phone']}`\n"
        f"**Устройство:** {data['device_type']}\n"
        f"**Проблема:** {data['problem_description']}\n"
        f"**Время звонка:** {data['preferred_time']}\n\n"
        "**Всё верно?**"
    )
    await message.answer(text, reply_markup=confirm_keyboard)
    await state.set_state(RepairRequest.confirm)

@router.message(RepairRequest.confirm, F.text == "Да")
async def confirm_yes(message: Message, state: FSMContext):
    global request_counter
    data = await state.get_data()
    request_counter += 1
    row = [request_counter, data['name'], data['phone'], data['device_type'], data['problem_description'], data['preferred_time']]
    requests_data[request_counter] = row[1:]

    with open(CSV_FILE, 'a', encoding='utf-8', newline='') as f:
        csv.writer(f).writerow(row)

    await message.answer(
        "**Заявка успешно отправлена!**\n\n"
        "Мы свяжемся с вами в указанное время.\n"
        "Спасибо за доверие!",
        reply_markup=main_keyboard
    )
    if ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"**НОВАЯ ЗАЯВКА #{request_counter}**\n\n" + "\n".join(f"**{k}:** {v}" for k, v in data.items()))
    await state.clear()

@router.message(RepairRequest.confirm, F.text == "Нет")
async def confirm_no(message: Message, state: FSMContext):
    await message.answer("**Хорошо, давайте исправим!**\n\n**Как вас зовут?**")
    await state.set_state(RepairRequest.name)

# --- Админ ---
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    if not requests_data:
        await message.answer("Нет заявок")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for req_id, data in requests_data.items():
        keyboard.inline_keyboard.append([
            InlineKeyboardButton(text=f"#{req_id} {data[0]}", callback_data=f"view_{req_id}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"delete_{req_id}")
        ])
    await message.answer("**Админ-панель:**", reply_markup=keyboard)

@router.callback_query(F.data.startswith("view_"))
async def view_request(callback: CallbackQuery):
    req_id = int(callback.data.split("_")[1])
    data = requests_data.get(req_id, [])
    if not data:
        await callback.answer("Заявка не найдена")
        return
    text = f"**Заявка #{req_id}**\n\n**Имя:** {data[0]}\n**Телефон:** `{data[1]}`\n**Устройство:** {data[2]}\n**Проблема:** {data[3]}\n**Время:** {data[4]}"
    await callback.message.answer(text)

@router.callback_query(F.data.startswith("delete_"))
async def delete_request(callback: CallbackQuery):
    req_id = int(callback.data.split("_")[1])
    if req_id in requests_data:
        del requests_data[req_id]
        with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Имя", "Телефон", "Устройство", "Проблема", "Время"])
            for rid, data in sorted(requests_data.items()):
                writer.writerow([rid] + data)
        await callback.message.edit_text(f"**Заявка #{req_id} удалена**")
    else:
        await callback.answer("Заявка не найдена")

@router.message(Command("get_csv"))
async def cmd_get_csv(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    if not os.path.exists(CSV_FILE):
        await message.answer("Нет заявок")
        return
    await message.answer_document(FSInputFile(CSV_FILE), caption="Все заявки")

# --- ВЕБ-ПАНЕЛЬ ---
async def login_page(request):
    return web.Response(text=f"""
    <h2>Админ-панель</h2>
    <p><a href="{LOGIN_URL}" target="_blank">Нажмите сюда, чтобы войти через Telegram</a></p>
    """, content_type="text/html")

async def admin_panel(request):
    user_id = request.query.get("user")
    if not user_id or int(user_id) != ADMIN_ID:
        return web.Response(text="Доступ запрещён", status=403)

    if not requests_data:
        return web.Response(text="<h2>Нет заявок</h2>", content_type="text/html")

    html = f"""
    <!DOCTYPE html>
    <html><head><title>Админ-панель</title>
    <meta charset="utf-8">
    <style>
        body {{font-family: Arial; margin: 40px; background: #f4f4f4;}}
        h2 {{color: #2c3e50;}}
        table {{width: 100%; border-collapse: collapse; margin: 20px 0;}}
        th, td {{border: 1px solid #ddd; padding: 12px; text-align: left;}}
        th {{background: #3498db; color: white;}}
        .btn {{padding: 8px 16px; margin: 4px; background: #e74c3c; color: white; text-decoration: none; border-radius: 4px;}}
        .download {{background: #27ae60;}}
    </style>
    </head><body>
    <h2>Заявки на ремонт</h2>
    <a href="/download_csv?user={user_id}" class="btn download">Скачать CSV</a>
    <table>
    <tr><th>ID</th><th>Имя</th><th>Телефон</th><th>Устройство</th><th>Проблема</th><th>Время</th><th>Действие</th></tr>
    """
    for req_id, data in sorted(requests_data.items()):
        html += f"<tr><td>{req_id}</td><td>{data[0]}</td><td>{data[1]}</td><td>{data[2]}</td><td>{data[3]}</td><td>{data[4]}</td>"
        html += f"<td><a href='/delete/{req_id}?user={user_id}' class='btn'>Удалить</a></td></tr>"
    html += "</table></body></html>"
    return web.Response(text=html, content_type="text/html")

async def delete_web(request):
    user_id = request.query.get("user")
    if not user_id or int(user_id) != ADMIN_ID:
        return web.Response(text="Доступ запрещён", status=403)
    req_id = int(request.match_info['id'])
    if req_id in requests_data:
        del requests_data[req_id]
        with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["ID", "Имя", "Телефон", "Устройство", "Проблема", "Время"])
            for rid, data in sorted(requests_data.items()):
                writer.writerow([rid] + data)
    return web.HTTPFound(f"/admin?user={user_id}")

async def download_csv_web(request):
    user_id = request.query.get("user")
    if not user_id or int(user_id) != ADMIN_ID:
        return web.Response(text="Доступ запрещён", status=403)
    if not os.path.exists(CSV_FILE):
        return web.Response(text="Нет заявок", status=404)
    return web.FileResponse(CSV_FILE, headers={"Content-Disposition": "attachment; filename=repair_requests.csv"})

# --- Логин ---
@router.message(Command("start"))
async def cmd_start_login(message: Message, state: FSMContext):
    if "login" in message.text.lower():
        if message.from_user.id == ADMIN_ID:
            await message.answer(f"Вы вошли! Перейдите: https://{config('AMVERA_APP_DOMAIN', '')}/admin?user={message.from_user.id}")
        else:
            await message.answer("Доступ запрещён")
        return
    await cmd_start(message)

# --- on_startup ---
async def on_startup(app: web.Application):
    global LOGIN_URL
    domain = config('AMVERA_APP_DOMAIN', default=None)
    if domain:
        await asyncio.sleep(30)
        try:
            me = await bot.get_me()
            LOGIN_URL = f"https://t.me/{me.username}?start=login"
            logging.info(f"LOGIN_URL: {LOGIN_URL}")
        except Exception as e:
            logging.error(f"Ошибка: {e}")
            LOGIN_URL = "https://t.me/твой_бот?start=login"

        webhook_url = f"https://{domain}/webhook"
        for _ in range(5):
            try:
                await bot.set_webhook(webhook_url)
                logging.info(f"WEBHOOK УСПЕШНО: {webhook_url}")
                break
            except Exception as e:
                logging.warning(f"Ошибка: {e}")
                await asyncio.sleep(10)

app = web.Application()
app.router.add_get("/", login_page)
app.router.add_get("/admin", admin_panel)
app.router.add_get("/delete/{id}", delete_web)
app.router.add_get("/download_csv", download_csv_web)

SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
setup_application(app, dp, bot=bot)
dp.include_router(router)
app.on_startup.append(on_startup)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8000)
