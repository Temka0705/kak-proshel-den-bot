"""Хранение данных.

В облаке — Postgres (переменная окружения DATABASE_URL или POSTGRES_URL).
Локально для тестов — SQLite-файл (если адреса базы нет).
"""

import json
import os
import sqlite3
from pathlib import Path

DEFAULT_LAT, DEFAULT_LON = 55.7558, 37.6173  # Москва, пока не прислали геолокацию

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS users (
    chat_id     BIGINT PRIMARY KEY,
    lat         REAL DEFAULT {DEFAULT_LAT},
    lon         REAL DEFAULT {DEFAULT_LON},
    remind_time TEXT DEFAULT 'on'
);
CREATE TABLE IF NOT EXISTS entries (
    chat_id  BIGINT,
    date     TEXT,
    score    INTEGER,
    sleep    REAL,
    energy   INTEGER,
    song     TEXT,
    song_url TEXT,
    tags     TEXT,
    note     TEXT,
    weather  TEXT,
    PRIMARY KEY (chat_id, date)
);
CREATE TABLE IF NOT EXISTS drafts (
    chat_id BIGINT PRIMARY KEY,
    step    TEXT,
    data    TEXT
);
"""

_conn = None


def _db_url():
    return os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")


def _connect():
    url = _db_url()
    if url:
        import psycopg
        from psycopg.rows import dict_row

        conn = psycopg.connect(url, autocommit=True, row_factory=dict_row)
        with conn.cursor() as cur:
            cur.execute(SCHEMA)
        return conn
    path = os.environ.get("SQLITE_PATH") or str(Path(__file__).resolve().parent.parent / "diary_local.db")
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _sqlite():
    return isinstance(_conn, sqlite3.Connection)


def _run(sql, params=(), fetch=None, _retry=True):
    """Выполнить запрос. fetch: None / 'one' / 'all'. Плейсхолдеры пишем как %s."""
    global _conn
    if _conn is None:
        _conn = _connect()
    try:
        if _sqlite():
            cur = _conn.execute(sql.replace("%s", "?"), params)
            rows = cur.fetchall() if fetch else None
            _conn.commit()
            rows = [dict(r) for r in rows] if rows is not None else None
        else:
            with _conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall() if fetch else None
    except Exception:
        # серверная функция могла «уснуть» и потерять соединение — переподключимся один раз
        if not _retry or _sqlite():
            raise
        _conn = None
        return _run(sql, params, fetch, _retry=False)
    if fetch == "one":
        return rows[0] if rows else None
    return rows


# --- Пользователи ----------------------------------------------------------------

def ensure_user(chat_id):
    _run("INSERT INTO users (chat_id) VALUES (%s) ON CONFLICT (chat_id) DO NOTHING", (chat_id,))


def get_user(chat_id):
    ensure_user(chat_id)
    return _run("SELECT * FROM users WHERE chat_id = %s", (chat_id,), "one")


def all_users():
    return _run("SELECT * FROM users", fetch="all")


def set_location(chat_id, lat, lon):
    ensure_user(chat_id)
    _run("UPDATE users SET lat = %s, lon = %s WHERE chat_id = %s", (lat, lon, chat_id))


def set_remind(chat_id, value):
    ensure_user(chat_id)
    _run("UPDATE users SET remind_time = %s WHERE chat_id = %s", (value, chat_id))


# --- Записи ------------------------------------------------------------------------

ENTRY_COLS = ["score", "sleep", "energy", "song", "song_url", "tags", "note", "weather"]


def save_entry(chat_id, e):
    values = [e.get(c) for c in ENTRY_COLS]
    values[ENTRY_COLS.index("tags")] = " | ".join(e.get("tags") or [])
    updates = ", ".join(f"{c} = excluded.{c}" for c in ENTRY_COLS)
    _run(
        f"INSERT INTO entries (chat_id, date, {', '.join(ENTRY_COLS)}) "
        f"VALUES (%s, %s, {', '.join(['%s'] * len(ENTRY_COLS))}) "
        f"ON CONFLICT (chat_id, date) DO UPDATE SET {updates}",
        (chat_id, e["date"], *values),
    )


def get_entry(chat_id, day_iso):
    return _run("SELECT * FROM entries WHERE chat_id = %s AND date = %s", (chat_id, day_iso), "one")


def get_entries(chat_id):
    return _run("SELECT * FROM entries WHERE chat_id = %s ORDER BY date", (chat_id,), "all")


# --- Черновик текущей записи (на каком шаге диалога пользователь) --------------------

def get_draft(chat_id):
    row = _run("SELECT * FROM drafts WHERE chat_id = %s", (chat_id,), "one")
    if not row:
        return None, None
    return row["step"], json.loads(row["data"])


def save_draft(chat_id, step, data):
    _run(
        "INSERT INTO drafts (chat_id, step, data) VALUES (%s, %s, %s) "
        "ON CONFLICT (chat_id) DO UPDATE SET step = excluded.step, data = excluded.data",
        (chat_id, step, json.dumps(data, ensure_ascii=False)),
    )


def delete_draft(chat_id):
    _run("DELETE FROM drafts WHERE chat_id = %s", (chat_id,))
