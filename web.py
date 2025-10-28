# web.py
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import csv
import os

app = FastAPI()
CSV_FILE = "/data/repair_requests.csv"

@app.get("/requests", response_class=HTMLResponse)
async def show_requests():
    if not os.path.exists(CSV_FILE):
        return "<h2>Нет заявок</h2>"
    with open(CSV_FILE, encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    html = "<h2>Заявки на ремонт</h2><table border='1' style='border-collapse: collapse;'><tr>" + "".join(f"<th>{h}</th>" for h in rows[0]) + "</tr>"
    for row in rows[1:]:
        html += "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
    return html + "</table>"
