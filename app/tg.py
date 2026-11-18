"""Минимальный клиент Telegram Bot API: отправить сообщение, фото, файл, кнопки."""

import hashlib
import json
import logging
import os

import httpx

log = logging.getLogger(__name__)
# httpx пишет в лог полный URL запроса, а в URL Bot API есть токен — такие логи отключаем
logging.getLogger("httpx").setLevel(logging.WARNING)


def token():
    return os.environ["BOT_TOKEN"]


def webhook_secret():
    """Секрет вебхука выводим из токена — так не нужна ещё одна переменная окружения."""
    return hashlib.sha256(("diary-webhook:" + token()).encode()).hexdigest()[:48]


def call(method, files=None, **params):
    """Вызов метода Bot API. Возвращает result или None при ошибке."""
    url = f"https://api.telegram.org/bot{token()}/{method}"
    try:
        if files:
            # multipart: сложные поля (клавиатуры) передаются JSON-строкой
            data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                    for k, v in params.items() if v is not None}
            r = httpx.post(url, data=data, files=files, timeout=30)
        else:
            r = httpx.post(url, json={k: v for k, v in params.items() if v is not None}, timeout=15)
        body = r.json()
    except Exception as exc:
        log.warning("Telegram %s: %s", method, exc)
        return None
    if not body.get("ok"):
        log.warning("Telegram %s: %s", method, body.get("description"))
        return None
    return body.get("result")


# --- Клавиатуры ---------------------------------------------------------------

def inline(rows):
    """rows: [[(текст, callback_data), ...], ...] -> inline-клавиатура."""
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


def reply_keyboard(rows):
    return {"keyboard": [[{"text": t} for t in row] for row in rows], "resize_keyboard": True}


# --- Удобные обёртки ----------------------------------------------------------

def send(chat_id, text, kb=None, html=True):
    return call(
        "sendMessage",
        chat_id=chat_id,
        text=text,
        reply_markup=kb,
        parse_mode="HTML" if html else None,
        link_preview_options={"is_disabled": True},
    )


def edit(chat_id, message_id, text, kb=None):
    return call(
        "editMessageText",
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
        link_preview_options={"is_disabled": True},
    )


def edit_kb(chat_id, message_id, kb):
    return call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup=kb)


def answer_callback(callback_id, text=None):
    return call("answerCallbackQuery", callback_query_id=callback_id, text=text)


def send_photo(chat_id, png_buf, caption=None):
    return call("sendPhoto", files={"photo": ("chart.png", png_buf, "image/png")},
                chat_id=chat_id, caption=caption)


def send_document(chat_id, data, filename):
    return call("sendDocument", files={"document": (filename, data, "text/csv")}, chat_id=chat_id)
