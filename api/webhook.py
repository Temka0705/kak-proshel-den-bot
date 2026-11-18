"""Сюда Telegram присылает каждое сообщение и нажатие кнопки (вебхук)."""

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")  # на сервере писать можно только в /tmp

from app import bot, tg  # noqa: E402

logging.basicConfig(level=logging.INFO)


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        # Принимаем только запросы от Telegram: он присылает секрет, который мы задали при setWebhook
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != tg.webhook_secret():
            self.send_response(403)
            self.end_headers()
            return
        try:
            bot.handle_update(json.loads(body))
        except Exception:
            # Всегда отвечаем 200, иначе Telegram будет повторять одно и то же сообщение
            logging.exception("Ошибка при обработке обновления")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Бот-дневник работает 📔".encode())
