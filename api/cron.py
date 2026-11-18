"""Задачи по расписанию (см. crons в vercel.json):
  /api/cron?task=remind  — каждый вечер ~22:00 МСК
  /api/cron?task=weekly  — по понедельникам ~10:00 МСК
  /api/cron?task=setup   — один раз вручную: подключить бота к Telegram (вебхук + меню команд)
"""

import json
import logging
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

from app import bot, tg  # noqa: E402

logging.basicConfig(level=logging.INFO)


def setup_webhook(host):
    """Говорим Telegram, куда присылать сообщения. Безопасно вызывать сколько угодно раз:
    адрес всегда наш собственный, секрет выводится из токена."""
    url = f"https://{host}/api/webhook"
    ok = tg.call(
        "setWebhook",
        url=url,
        secret_token=tg.webhook_secret(),
        allowed_updates=["message", "callback_query"],
    )
    cmds = tg.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in bot.COMMANDS])
    info = tg.call("getWebhookInfo") or {}
    me = tg.call("getMe") or {}
    return {"bot": me.get("username"), "webhook_set": bool(ok), "commands_set": bool(cmds),
            "webhook_url": info.get("url"), "pending_updates": info.get("pending_update_count"),
            "last_error": info.get("last_error_message")}


def _authorized(headers):
    secret = os.environ.get("CRON_SECRET")
    if secret:  # если задан CRON_SECRET, Vercel сам присылает его в заголовке
        return headers.get("Authorization") == f"Bearer {secret}"
    return headers.get("User-Agent", "").startswith("vercel-cron")


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        task = parse_qs(urlparse(self.path).query).get("task", [""])[0]
        if task != "setup" and not _authorized(self.headers):
            self.send_response(401)
            self.end_headers()
            return
        if task == "setup":
            host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or self.headers.get("Host")
            result = setup_webhook(host)
        elif task == "remind":
            result = {"reminded": bot.send_reminders()}
        elif task == "weekly":
            result = {"weekly_sent": bot.send_weekly()}
        else:
            result = {"error": "unknown task"}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(result).encode())
