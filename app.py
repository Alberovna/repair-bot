from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery, ReplyKeyboardRemove
)
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
import re
from datetime import datetime

# ----------------------------------------------------------------------
# Настройка
# ----------------------------------------------------------------------
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
BOT_TOKEN = config("BOT_TOKEN")
ADMIN_ID = config("ADMIN_ID", default=None, cast=int)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# ----------------------------------------------------------------------
# CSV-файл с заявками
# ----------------------------------------------------------------------
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
CSV_FILE = os.path.join(DATA_DIR, "repair_requests.csv")
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, 'w', encoding='utf-8', newline='') as f:
        csv.writer(f).writerow(
            ["ID", "Имя", "Телефон", "Устройство", "Проблема", "Время", "Дата создания"]
        )

# ----------------------------------------------------------------------
# Клавиатуры
# ----------------------------------------------------------------------
main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Заявка на ремонт"), KeyboardButton(text="Контакты")],
        [KeyboardButton(text="Эхо (только админ)")]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)
confirm_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Да"), KeyboardButton(text="Нет")]],
    resize_keyboard=True,
    one_time_keyboard=True
)

# ----------------------------------------------------------------------
# FSM-состояния
# ----------------------------------------------------------------------
class RepairRequest(StatesGroup):
    name = State()
    phone = State()
    device_type = State()
    problem_description = State()
    preferred_time = State()
    confirm = State()

# ----------------------------------------------------------------------
# Глобальные переменные
# ----------------------------------------------------------------------
request_counter = 0
requests_data: dict[int, list[str]] = {}
LOGIN_URL = "https://t.me/placeholder_bot?start=login"  # будет переопределён

# ----------------------------------------------------------------------
# Загрузка заявок из CSV
# ----------------------------------------------------------------------
def load_requests() -> None:
    global request_counter, requests_data
    requests_data.clear()
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) >= 6 and row[0].isdigit():
                    rid = int(row[0])
                    requests_data[rid] = row[1:6]
                    request_counter = max(request_counter, rid)
    request_counter = max(requests_data.keys(), default=0)
load_requests()

# ----------------------------------------------------------------------
# Валидация телефона
# ----------------------------------------------------------------------
def is_valid_phone(phone: str) -> bool:
    cleaned = re.sub(r"[^\d+]", "", phone)
    return bool(re.fullmatch(r"\+?\d{10,15}", cleaned)) and len(cleaned.lstrip('+')) >= 10

# ----------------------------------------------------------------------
# Перезапись CSV
# ----------------------------------------------------------------------
def _rewrite_csv() -> None:
    tmp_file = CSV_FILE + ".tmp"
    with open(tmp_file, 'w', encoding='utf-8', newline='') as tf:
        writer = csv.writer(tf)
        writer.writerow(["ID", "Имя", "Телефон", "Устройство", "Проблема", "Время", "Дата создания"])
        for rid, data in sorted(requests_data.items()):
            created = "Неизвестно"
            if os.path.exists(CSV_FILE):
                with open(CSV_FILE, 'r', encoding='utf-8') as rf:
                    for row in csv.reader(rf):
                        if row and len(row) >= 7 and row[0] == str(rid):
                            created = row[6]
                            break
            writer.writerow([rid] + data + [created])
    os.replace(tmp_file, CSV_FILE)

# ----------------------------------------------------------------------
# Хендлеры
# ----------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    args = message.text.strip().split(maxsplit=1)
    if len(args) > 1 and "login" in args[1].lower():
        if message.from_user.id == ADMIN_ID:
            await message.answer("Вход подтверждён! Можете закрыть это окно.")
        else:
            await message.answer("Доступ запрещён")
        return

    await message.answer(
        "Привет! Добро пожаловать в **сервисный центр «TechFix»**!\n\n"
        "Я помогу вам оформить заявку на ремонт.\n\n"
        "Выберите действие:",
        reply_markup=main_keyboard
    )

@router.message(F.text == "Заявка на ремонт")
async def start_request(message: Message, state: FSMContext):
    await message.answer("**Как вас зовут?**", reply_markup=ReplyKeyboardRemove())
    await state.set_state(RepairRequest.name)

@router.message(F.text == "Контакты")
async def show_contacts(message: Message):
    await message.answer(
        "**Наши контакты:**\n\n"
        "Адрес: **ул. Техническая, 10**\n"
        "Телефон: **+7 (123) 456-78-90**\n"
        "Часы работы: **Пн–Пт: 10:00–19:00**\n\n"
        "Мы всегда рады помочь!",
        reply_markup=main_keyboard
    )

@router.message(F.text == "Эхо (только админ)")
async def echo_mode(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    await message.answer("Эхо-режим включён. Отправьте сообщение — я повторю.", reply_markup=main_keyboard)

# ------------------- FSM -------------------
@router.message(RepairRequest.name)
async def get_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Имя слишком короткое. Попробуйте снова:")
        return
    await state.update_data(name=name)
    await message.answer(
        "**Отлично!**\n\nВведите ваш **номер телефона**:\n\n"
        "Формат: `+79123456789` или `89123456789`"
    )
    await state.set_state(RepairRequest.phone)

@router.message(RepairRequest.phone)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not is_valid_phone(phone):
        await message.answer(
            "**Неверный формат!**\n\nПримеры:\n`+79123456789`\n`89123456789`"
        )
        return
    await state.update_data(phone=phone)
    await message.answer(
        "**Какое устройство нужно починить?**\n\n"
        "Например: *смартфон Samsung*, *ноутбук Lenovo*"
    )
    await state.set_state(RepairRequest.device_type)

@router.message(RepairRequest.device_type)
async def get_device_type(message: Message, state: FSMContext):
    await state.update_data(device_type=message.text.strip())
    await message.answer(
        "**Опишите проблему подробно:**\n\n"
        "Например:\n"
        "• Не включается\n"
        "• Разбит экран\n"
        "• Не заряжается"
    )
    await state.set_state(RepairRequest.problem_description)

@router.message(RepairRequest.problem_description)
async def get_problem_description(message: Message, state: FSMContext):
    await state.update_data(problem_description=message.text.strip())
    await message.answer(
        "**Когда вам удобно принять звонок?**\n\n"
        "Например:\n"
        "• Завтра после 14:00\n"
        "• Вечером в будни"
    )
    await state.set_state(RepairRequest.preferred_time)

@router.message(RepairRequest.preferred_time)
async def get_preferred_time(message: Message, state: FSMContext):
    await state.update_data(preferred_time=message.text.strip())
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
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [
        request_counter, data['name'], data['phone'],
        data['device_type'], data['problem_description'],
        data['preferred_time'], created_at
    ]
    requests_data[request_counter] = row[1:6]
    with open(CSV_FILE, 'a', encoding='utf-8', newline='') as f:
        csv.writer(f).writerow(row)
    await message.answer(
        "**Заявка успешно отправлена!**\n\n"
        "Мы свяжемся с вами в указанное время.\n"
        "Спасибо за доверие!",
        reply_markup=main_keyboard
    )
    if ADMIN_ID:
        admin_text = (
            f"**НОВАЯ ЗАЯВКА #{request_counter}**\n\n"
            f"**Имя:** {data['name']}\n"
            f"**Телефон:** `{data['phone']}`\n"
            f"**Устройство:** {data['device_type']}\n"
            f"**Проблема:** {data['problem_description']}\n"
            f"**Время:** {data['preferred_time']}\n"
            f"**Создано:** {created_at}"
        )
        await bot.send_message(ADMIN_ID, admin_text)
    await state.clear()

@router.message(RepairRequest.confirm, F.text == "Нет")
async def confirm_no(message: Message, state: FSMContext):
    await message.answer(
        "**Хорошо, давайте исправим!**\n\n**Как вас зовут?**",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(RepairRequest.name)

# ------------------- Админ-панель -------------------
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    if not requests_data:
        await message.answer("Нет заявок", reply_markup=main_keyboard)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for rid, data in sorted(requests_data.items()):
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"#{rid} {data[0]}", callback_data=f"view_{rid}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"delete_{rid}")
        ])
    await message.answer("**Админ-панель:**", reply_markup=kb)

@router.callback_query(F.data.startswith("view_"))
async def view_request(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    data = requests_data.get(rid)
    if not data:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    created = "Неизвестно"
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'r', encoding='utf-8') as f:
            for row in csv.reader(f):
                if row and len(row) >= 7 and row[0] == str(rid):
                    created = row[6]
                    break
    text = (
        f"**Заявка #{rid}**\n\n"
        f"**Имя:** {data[0]}\n"
        f"**Телефон:** `{data[1]}`\n"
        f"**Устройство:** {data[2]}\n"
        f"**Проблема:** {data[3]}\n"
        f"**Время:** {data[4]}\n"
        f"**Создано:** {created}"
    )
    await callback.message.answer(text)
    await callback.answer()

@router.callback_query(F.data.startswith("delete_"))
async def delete_request(callback: CallbackQuery):
    rid = int(callback.data.split("_")[1])
    if rid in requests_data:
        del requests_data[rid]
        _rewrite_csv()
        await callback.message.edit_text(
            f"**Заявка #{rid} удалена**",
            reply_markup=None
        )
        await cmd_admin(callback.message)
    else:
        await callback.answer("Заявка не найдена", show_alert=True)

@router.message(Command("get_csv"))
async def cmd_get_csv(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("Доступ запрещён")
        return
    if not os.path.exists(CSV_FILE):
        await message.answer("Нет заявок")
        return
    with open(CSV_FILE, 'rb') as f:
        file = BufferedInputFile(f.read(), filename="repair_requests.csv")
    await message.answer_document(file, caption="Все заявки")

# ------------------- Эхо для админа -------------------
@router.message(lambda m: m.from_user.id == ADMIN_ID)
async def echo_admin(message: Message, state: FSMContext):
    if message.text and message.text.startswith('/'):
        return
    if message.text in ["Заявка на ремонт", "Контакты", "Эхо (только админ)", "Да", "Нет"]:
        return
    if await state.get_state() is not None:
        return
    await message.answer(f"**Эхо:** {message.text}")

# ----------------------------------------------------------------------
# Веб-панель
# ----------------------------------------------------------------------
async def login_page(request):
    user_id = request.query.get("user")
    if user_id and int(user_id) == ADMIN_ID:
        raise web.HTTPFound(f"/admin?user={user_id}")

    return web.Response(
        text=f"""
        <!DOCTYPE html>
        <html><head><title>TechFix — Вход</title><meta charset="utf-8">
        <style>
            body {{font-family: Arial; margin:40px; background:#f4f4f4; text-align:center;}}
            a {{padding:12px 24px; background:#3498db; color:white; text-decoration:none; border-radius:6px; font-size:18px;}}
        </style></head><body>
        <h2>Админ-панель TechFix</h2>
        <p><a href="{LOGIN_URL}" target="_blank">Нажмите, чтобы войти через Telegram</a></p>
        <p style="color:#7f8c8d; margin-top:20px;">
            После подтверждения в Telegram — <strong>нажмите F5</strong> или обновите страницу
        </p>
        </body></html>
        """,
        content_type="text/html"
    )
    
async def admin_panel(request):
    user_id = request.query.get("user")
    if not user_id or int(user_id) != ADMIN_ID:
        return web.Response(text="Доступ запрещён", status=403)
    if not requests_data:
        return web.Response(text="<h2>Нет заявок</h2>", content_type="text/html")

    html = f"""
    <!DOCTYPE html>
    <html><head><title>Админ-панель</title><meta charset="utf-8">
    <style>
        body {{font-family: Arial; margin:40px; background:#f4f4f4;}}
        h2 {{color:#2c3e50;}} table {{width:100%; border-collapse:collapse; margin:20px 0;}}
        th,td {{border:1px solid #ddd; padding:12px; text-align:left;}}
        th {{background:#3498db; color:white;}}
        .btn {{padding:8px 16px; margin:4px; background:#e74c3c; color:white; text-decoration:none; border-radius:4px;}}
        .download {{background:#27ae60;}}
    </style></head><body>
    <h2>Заявки на ремонт</h2>
    <a href="/download_csv?user={user_id}" class="btn download">Скачать CSV</a>
    <table>
    <tr><th>ID</th><th>Имя</th><th>Телефон</th><th>Устройство</th><th>Проблема</th><th>Время</th><th>Создано</th><th>Действие</th></tr>
    """
    with open(CSV_FILE, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 7:
                rid = row[0]
                html += (
                    f"<tr><td>{rid}</td><td>{row[1]}</td><td>{row[2]}</td>"
                    f"<td>{row[3]}</td><td>{row[4]}</td><td>{row[5]}</td><td>{row[6]}</td>"
                    f"<td><a href='/delete/{rid}?user={user_id}' class='btn'>Удалить</a></td></tr>"
                )
    html += "</table></body></html>"
    return web.Response(text=html, content_type="text/html")

async def delete_web(request):
    user_id = request.query.get("user")
    if not user_id or int(user_id) != ADMIN_ID:
        return web.Response(text="Доступ запрещён", status=403)
    rid = int(request.match_info["id"])
    if rid in requests_data:
        del requests_data[rid]
        _rewrite_csv()
    return web.HTTPFound(f"/admin?user={user_id}")

async def download_csv_web(request):
    user_id = request.query.get("user")
    if not user_id or int(user_id) != ADMIN_ID:
        return web.Response(text="Доступ запрещён", status=403)
    if not os.path.exists(CSV_FILE):
        return web.Response(text="Нет заявок", status=404)
    return web.FileResponse(
        CSV_FILE,
        headers={"Content-Disposition": "attachment; filename=repair_requests.csv"}
    )

# ----------------------------------------------------------------------
# on_startup
# ----------------------------------------------------------------------
async def on_startup(app: web.Application):
    global LOGIN_URL
    try:
        me = await bot.get_me()
        LOGIN_URL = f"https://t.me/{me.username}?start=login"
        logging.info(f"Bot: @{me.username} | Login URL: {LOGIN_URL}")
    except Exception as e:
        logging.error(f"Ошибка получения username: {e}")

# ----------------------------------------------------------------------
# Веб-приложение
# ----------------------------------------------------------------------
app = web.Application()
app.router.add_get("/", login_page)
app.router.add_get("/admin", admin_panel)
app.router.add_get("/delete/{id}", delete_web)
app.router.add_get("/download_csv", download_csv_web)

# Регистрация webhook
SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path="/webhook")
setup_application(app, dp, bot=bot)

# Включаем роутер
dp.include_router(router)

# ----------------------------------------------------------------------
# Запуск — ТОЛЬКО webhook
# ----------------------------------------------------------------------
import os

async def main():
    await on_startup(app)
    
    port = int(os.environ.get("PORT", 8000))
    webhook_url = f"https://tehnobot-miyassarova110604.amvera.io/webhook"
    
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    logging.info(f"Webhook установлен: {webhook_url}")
    
    await web._run_app(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    asyncio.run(main())
