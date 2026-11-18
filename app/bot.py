"""Логика бота: обрабатывает одно обновление от Telegram за раз (вебхук).

Состояние диалога («на каком шаге записи») хранится в базе, в таблице drafts,
потому что серверная функция между сообщениями ничего не помнит.
"""

import csv
import html
import io
import logging
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import extras, stats, storage, tg

log = logging.getLogger("diary")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Europe/Moscow"))

TAGS_LIST = [
    "🏃 спорт", "📚 учёба", "👥 друзья", "❤️ близкие", "🎉 тусовка",
    "🎮 отдых", "💼 работа", "🎬 кино/сериал", "🤒 болел", "✈️ поездка",
]
ENERGY_LABELS = {1: "🪫 1", 2: "😮‍💨 2", 3: "🙂 3", 4: "💪 4", 5: "⚡ 5"}

BTN_DAY = "📝 Записать день"
BTN_STATS = "📊 Статистика"
BTN_PIXELS = "🟩 Год в пикселях"
BTN_HISTORY = "📖 Последние дни"
BTN_SONGS = "🎵 Песни"
BTN_CHART = "📈 График"
BTN_WEEK = "🗓 Неделя"
MAIN_KB = tg.reply_keyboard(
    [[BTN_DAY], [BTN_STATS, BTN_CHART], [BTN_SONGS, BTN_WEEK], [BTN_PIXELS, BTN_HISTORY]]
)

MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]

COMMANDS = [
    ("day", "Записать день"),
    ("stats", "Статистика за 30 дней"),
    ("chart", "График настроения"),
    ("songs", "Песни"),
    ("week", "Итоги недели"),
    ("pixels", "Год в пикселях"),
    ("history", "Последние 7 дней"),
    ("edit", "Исправить прошлый день"),
    ("delete", "Удалить запись"),
    ("remind", "Напоминания вкл/выкл"),
    ("export", "Выгрузить в CSV"),
    ("cancel", "Отменить запись"),
]


# --- Вспомогательное ------------------------------------------------------------

def diary_date():
    """День, к которому относится запись. До 5 утра — это ещё вчерашний день."""
    now = datetime.now(TZ)
    if now.hour < 5:
        now -= timedelta(days=1)
    return now.date()


def fmt_date(d):
    return f"{d.day} {MONTHS_GEN[d.month - 1]}, {WEEKDAYS[d.weekday()]}"


def short_date(d):
    return f"{d.day} {MONTHS_GEN[d.month - 1]}"


def parse_day(text):
    """«вчера», «15.11», «15.11.2026», «2026-11-15» -> date. None, если не понял или день в будущем."""
    t = text.strip().lower()
    today = diary_date()
    named = {"сегодня": 0, "вчера": 1, "позавчера": 2}
    if t in named:
        return today - timedelta(days=named[t])
    has_year = True
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        y, mo, dd = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", t)
        if not m:
            return None
        dd, mo = int(m[1]), int(m[2])
        has_year = bool(m[3])
        y = int(m[3]) if m[3] else today.year
        y += 2000 if y < 100 else 0
    try:
        d = date(y, mo, dd)
        if not has_year and d > today:  # «20.12» в ноябре — значит, прошлый год
            d = date(y - 1, mo, dd)
    except ValueError:
        return None
    return d if d <= today else None


def entry_to_draft(row):
    """Запись из базы -> черновик для редактирования (теги списком)."""
    draft = {k: row[k] for k in ("date", "score", "sleep", "energy", "song", "song_url", "note", "weather")}
    draft["tags"] = [t for t in (row["tags"] or "").split(" | ") if t]
    return draft


def song_title(s):
    return f"{s['artist']} — {s['track']}" if s.get("artist") else s["track"]


def render_entry(e):
    d = datetime.fromisoformat(e["date"]).date()
    lines = [f"📅 <b>{fmt_date(d)}</b>", "", f"⭐ Оценка: <b>{e['score']}/10</b>"]
    if e.get("sleep") is not None:
        lines.append(f"😴 Сон: {e['sleep']:g} ч")
    if e.get("energy") is not None:
        lines.append(f"⚡ Энергия: {e['energy']}/5")
    if e.get("weather"):
        lines.append(f"🌡 Погода: {html.escape(e['weather'])}")
    if e.get("song"):
        song = html.escape(e["song"])
        if e.get("song_url"):
            song = f'<a href="{html.escape(e["song_url"])}">{song}</a>'
        lines.append(f"🎵 {song}")
    tags = e.get("tags")
    if isinstance(tags, str):
        tags = [t for t in tags.split(" | ") if t]
    if tags:
        lines.append(f"🏷 {html.escape(', '.join(tags))}")
    if e.get("note"):
        lines.append(f"\n💬 <i>{html.escape(e['note'])}</i>")
    return "\n".join(lines)


def score_kb():
    return tg.inline([[(str(i), f"score:{i}") for i in row] for row in (range(1, 6), range(6, 11))])


def sleep_kb():
    return tg.inline([[(f"{h} ч", f"sleep:{h}") for h in row] for row in ((5, 6, 7), (8, 9, 10))])


def energy_kb():
    return tg.inline([[(label, f"energy:{n}") for n, label in ENERGY_LABELS.items()]])


def skip_kb(prefix, label="Пропустить ➡️"):
    return tg.inline([[(label, f"{prefix}:skip")]])


def tags_kb(selected):
    buttons = [(("✅ " if t in selected else "") + t, f"tag:{i}") for i, t in enumerate(TAGS_LIST)]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    rows.append([("Готово ✔️", "tags:done")])
    return tg.inline(rows)


# --- Команды -----------------------------------------------------------------------

def cmd_start(chat_id):
    storage.ensure_user(chat_id)
    tg.send(
        chat_id,
        "Привет! Я твой дневник 📔\n\n"
        "Каждый вечер я спрошу, как прошёл день: оценка, сон, энергия, песня дня, "
        "теги и главное за день. Погоду подставлю сам.\n\n"
        "📍 Пришли геолокацию (скрепка → Геопозиция), чтобы погода была по твоему городу. "
        "Пока считаю, что ты в Москве.\n\n"
        "/day — записать день\n"
        "/stats — статистика за 30 дней\n"
        "/chart — график настроения и сна\n"
        "/songs — песни: за месяц, за всё время, хорошие и плохие дни\n"
        "/week — итоги недели (в понедельник утром пришлю их сам)\n"
        "/pixels — год в пикселях\n"
        "/history — последние 7 дней\n"
        "/edit — исправить или дописать прошлый день (/edit 15.11, /edit вчера)\n"
        "/delete — удалить запись за день\n"
        "/remind off — выключить вечерние напоминания\n"
        "/export — выгрузить всё в CSV",
        MAIN_KB,
        html=False,
    )


def cmd_remind(chat_id, args):
    user = storage.get_user(chat_id)
    if not args:
        state = "выключены" if user["remind_time"] == "off" else "включены (около 22:00)"
        tg.send(chat_id, f"⏰ Напоминания {state}.\n/remind on — включить, /remind off — выключить")
        return
    value = "off" if args[0].lower() in ("off", "выкл", "нет") else "on"
    storage.set_remind(chat_id, value)
    tg.send(chat_id, "🔕 Напоминания выключены" if value == "off" else "⏰ Напоминания включены, пишу около 22:00")


def cmd_stats(chat_id):
    tg.send(chat_id, stats.stats_text(storage.get_entries(chat_id), diary_date()))


def cmd_pixels(chat_id):
    png = stats.pixels_png(storage.get_entries(chat_id), diary_date().year)
    tg.send_photo(chat_id, png, "🟩 Каждая клетка — день, цвет — оценка")


def cmd_chart(chat_id):
    png = stats.mood_chart_png(storage.get_entries(chat_id), diary_date())
    if png is None:
        tg.send(chat_id, "Для графика нужно хотя бы 2 записи за последние 30 дней 🙂")
        return
    tg.send_photo(chat_id, png, "📈 Точки — оценка дня, голубые столбики — сон")


def cmd_history(chat_id):
    entries = storage.get_entries(chat_id)[-7:]
    if not entries:
        tg.send(chat_id, "Записей пока нет. Начни с /day 🙂")
        return
    for e in entries:
        tg.send(chat_id, render_entry(e), tg.inline([[
            ("✏️ Исправить", f"pick:edit:{e['date']}"), ("🗑 Удалить", f"del:ask:{e['date']}"),
        ]]))


def cmd_export(chat_id):
    entries = storage.get_entries(chat_id)
    if not entries:
        tg.send(chat_id, "Пока нечего выгружать.")
        return
    cols = ["date", "score", "sleep", "energy", "weather", "song", "song_url", "tags", "note"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(cols)
    for e in entries:
        writer.writerow([e[c] for c in cols])
    tg.send_document(chat_id, buf.getvalue().encode("utf-8-sig"), f"diary_{diary_date().isoformat()}.csv")


def cmd_week(chat_id):
    entries = storage.get_entries(chat_id)
    today = diary_date()
    monday = today - timedelta(days=today.weekday())
    text = stats.week_summary(entries, monday) or stats.week_summary(entries, monday - timedelta(days=7))
    tg.send(chat_id, text or "За эту и прошлую неделю записей нет. Начни с /day 🙂")


def songs_menu_kb():
    month = diary_date().strftime("%Y-%m")
    return tg.inline([
        [("📅 За этот месяц", f"songs:m:{month}"), ("💿 За всё время", "songs:all")],
        [("🌞 Хорошие дни", "songs:good"), ("🌧 Плохие дни", "songs:bad")],
    ])


def month_nav_kb(year, month):
    prev_y, prev_m = (year, month - 1) if month > 1 else (year - 1, 12)
    next_y, next_m = (year, month + 1) if month < 12 else (year + 1, 1)
    row = [("◀ Раньше", f"songs:m:{prev_y}-{prev_m:02d}")]
    today = diary_date()
    if (next_y, next_m) <= (today.year, today.month):
        row.append(("Позже ▶", f"songs:m:{next_y}-{next_m:02d}"))
    return tg.inline([row])


def on_songs_button(chat_id, data):
    entries = storage.get_entries(chat_id)
    parts = data.split(":")
    kb = None
    if parts[1] == "m":
        year, month = map(int, parts[2].split("-"))
        chunks = stats.songs_month(entries, year, month)
        kb = month_nav_kb(year, month)
    elif parts[1] == "all":
        chunks = stats.songs_all(entries)
    else:
        chunks = stats.soundtrack(entries, good=parts[1] == "good")
    for i, chunk in enumerate(chunks):
        tg.send(chat_id, chunk, kb if i == len(chunks) - 1 else None)


# --- Исправление и удаление прошлых дней ------------------------------------------------

def edit_menu_kb(day_iso):
    return tg.inline([
        [("⭐ Оценка", f"ef:score:{day_iso}"), ("😴 Сон", f"ef:sleep:{day_iso}"), ("⚡ Энергия", f"ef:energy:{day_iso}")],
        [("🎵 Песня", f"ef:song:{day_iso}"), ("🏷 Теги", f"ef:tags:{day_iso}"), ("💬 Заметка", f"ef:note:{day_iso}")],
        [("🗑 Удалить этот день", f"del:ask:{day_iso}")],
    ])


def pick_days_kb(chat_id, action):
    """Кнопки с последними записанными днями. None, если записей нет."""
    entries = storage.get_entries(chat_id)[-8:][::-1]
    if not entries:
        return None
    buttons = []
    for e in entries:
        d = date.fromisoformat(e["date"])
        buttons.append((f"{d.day:02d}.{d.month:02d} · ⭐{e['score']}", f"pick:{action}:{e['date']}"))
    return tg.inline([buttons[i:i + 2] for i in range(0, len(buttons), 2)])


def cmd_edit(chat_id, args):
    if args:
        d = parse_day(" ".join(args))
        if not d:
            tg.send(chat_id, "Не понял дату 🤔 Примеры: /edit 15.11, /edit вчера, /edit 15.11.2026")
            return
        show_edit_menu(chat_id, d.isoformat())
        return
    kb = pick_days_kb(chat_id, "edit")
    if not kb:
        tg.send(chat_id, "Записей пока нет. Начни с /day 🙂")
        return
    tg.send(chat_id, "✏️ Какой день исправить?\n<i>Другой день — так: /edit 12.11 (можно и пропущенный)</i>", kb)


def cmd_delete(chat_id, args):
    if args:
        d = parse_day(" ".join(args))
        if not d:
            tg.send(chat_id, "Не понял дату 🤔 Примеры: /delete 15.11, /delete вчера")
            return
        confirm_delete(chat_id, d.isoformat())
        return
    kb = pick_days_kb(chat_id, "del")
    if not kb:
        tg.send(chat_id, "Записей пока нет — удалять нечего.")
        return
    tg.send(chat_id, "🗑 Какой день удалить?\n<i>Другой день — так: /delete 12.11</i>", kb)


def show_edit_menu(chat_id, day_iso):
    row = storage.get_entry(chat_id, day_iso)
    when = short_date(date.fromisoformat(day_iso))
    if not row:
        tg.send(chat_id, f"За {when} записи нет. Записать этот день сейчас?",
                tg.inline([[("📝 Записать этот день", f"day:start:{day_iso}")]]))
        return
    tg.send(chat_id, render_entry(row) + "\n\n✏️ <b>Что исправить?</b>", edit_menu_kb(day_iso))


def edit_field(chat_id, field, day_iso):
    row = storage.get_entry(chat_id, day_iso)
    if not row:
        tg.send(chat_id, "Этой записи уже нет. Посмотреть дни: /edit")
        return
    draft = entry_to_draft(row)
    draft["mode"] = "edit"
    storage.save_draft(chat_id, field, draft)
    when = short_date(date.fromisoformat(day_iso))
    if field == "score":
        tg.send(chat_id, f"⭐ Новая оценка за {when} (сейчас {row['score']}/10):", score_kb())
    elif field == "sleep":
        tg.send(chat_id, f"😴 Сколько спал {when}? Нажми или напиши число:", sleep_kb())
    elif field == "energy":
        tg.send(chat_id, f"⚡ Сколько было энергии {when}?", energy_kb())
    elif field == "song":
        now = f"\nСейчас: {html.escape(row['song'])}" if row["song"] else ""
        tg.send(chat_id, f"🎵 Песня за {when}: пришли ссылку Spotify или название.{now}",
                skip_kb("song", "🚫 Убрать песню"))
    elif field == "tags":
        tg.send(chat_id, f"🏷 Теги за {when} — нажми, чтобы поставить или снять:", tags_kb(draft["tags"]))
    elif field == "note":
        now = f"\nСейчас: <i>{html.escape(row['note'])}</i>" if row["note"] else ""
        tg.send(chat_id, f"💬 Напиши новое «главное за день» за {when}:{now}",
                skip_kb("note", "🚫 Убрать заметку"))


def finish_edit(chat_id, draft):
    draft.pop("mode", None)
    storage.save_entry(chat_id, draft)
    storage.delete_draft(chat_id)
    tg.send(chat_id, "✏️ Исправил!\n\n" + render_entry(draft) + "\n\nИсправить что-то ещё?",
            edit_menu_kb(draft["date"]))


def advance_edit(chat_id, draft):
    """В режиме исправления одно поле = сразу сохранить. True, если это был режим исправления."""
    if draft.get("mode") == "edit":
        finish_edit(chat_id, draft)
        return True
    return False


def confirm_delete(chat_id, day_iso):
    row = storage.get_entry(chat_id, day_iso)
    when = short_date(date.fromisoformat(day_iso))
    if not row:
        tg.send(chat_id, f"За {when} записи нет — удалять нечего.")
        return
    tg.send(chat_id, f"🗑 <b>Удалить запись за {when}?</b> Вернуть её не получится.\n\n" + render_entry(row),
            tg.inline([[("🗑 Да, удалить", f"del:yes:{day_iso}"), ("Отмена", "del:no")]]))


def on_delete_button(chat_id, message_id, data):
    parts = data.split(":")
    if parts[1] == "ask":
        confirm_delete(chat_id, parts[2])
    elif parts[1] == "yes":
        day_iso = parts[2]
        storage.delete_entry(chat_id, day_iso)
        step, draft = storage.get_draft(chat_id)
        if draft and draft.get("date") == day_iso:
            storage.delete_draft(chat_id)  # если этот день как раз редактировали
        tg.edit(chat_id, message_id, f"🗑 Запись за {short_date(date.fromisoformat(day_iso))} удалена.")
    else:
        tg.edit(chat_id, message_id, "Окей, ничего не удаляю 🙂")


# --- Диалог записи дня ----------------------------------------------------------------
# Шаги: score -> sleep -> energy -> song -> tags -> note -> сохранение.
# В режиме исправления (draft["mode"] == "edit") после любого шага запись сразу сохраняется.

def day_start(chat_id, d=None):
    storage.ensure_user(chat_id)
    d = d or diary_date()
    storage.save_draft(chat_id, "score", {"date": d.isoformat(), "tags": []})
    title = f"📝 Записываем {fmt_date(d)}"
    if storage.get_entry(chat_id, d.isoformat()):
        title += "\n(запись за этот день уже есть — перезапишу)"
    tg.send(chat_id, f"{title}\n\n⭐ Как прошёл день? Оцени от 1 до 10:", score_kb())


def ask_energy(chat_id, draft):
    storage.save_draft(chat_id, "energy", draft)
    tg.send(chat_id, "⚡ Сколько было энергии? (1 — разряжен, 5 — на максимум)", energy_kb())


def ask_song(chat_id, draft):
    storage.save_draft(chat_id, "song", draft)
    tg.send(
        chat_id,
        "🎵 Песня дня?\n"
        "• Пришли ссылку из Spotify (Поделиться → Копировать ссылку)\n"
        "• или просто напиши название / исполнителя — найду сам",
        skip_kb("song"),
    )


def ask_tags(chat_id, draft):
    storage.save_draft(chat_id, "tags", draft)
    tg.send(chat_id, "🏷 Что было сегодня? Отметь всё подходящее:", tags_kb(draft["tags"]))


def ask_note(chat_id, draft):
    storage.save_draft(chat_id, "note", draft)
    tg.send(chat_id, "💬 Главное за день — одной-двумя строками:", skip_kb("note"))


def after_song(chat_id, draft):
    if not advance_edit(chat_id, draft):
        ask_tags(chat_id, draft)


def finish(chat_id, draft):
    if advance_edit(chat_id, draft):
        return
    user = storage.get_user(chat_id)
    draft["weather"] = extras.get_weather(user["lat"], user["lon"], draft["date"])
    storage.save_entry(chat_id, draft)
    storage.delete_draft(chat_id)
    tg.send(chat_id, "✅ Записал!\n\n" + render_entry(draft), MAIN_KB)


def on_draft_text(chat_id, step, draft, text):
    """Текстовый ответ во время записи. Возвращает False, если текст не ожидался."""
    if step == "sleep":
        try:
            hours = float(text.replace(",", ".").replace("ч", "").strip())
            if not 0 <= hours <= 24:
                raise ValueError
        except ValueError:
            tg.send(chat_id, "Напиши число часов, например 7 или 7.5")
            return True
        draft["sleep"] = hours
        tg.send(chat_id, f"😴 Сон: {hours:g} ч")
        if not advance_edit(chat_id, draft):
            ask_energy(chat_id, draft)
        return True

    if step == "song":
        link = extras.find_spotify_link(text)
        if link:
            track = extras.spotify_track(link)
            draft["song"], draft["song_url"] = (song_title(track), track["url"]) if track else ("трек из Spotify", link)
            tg.send(chat_id, f"🎵 {html.escape(draft['song'])}")
            after_song(chat_id, draft)
            return True
        options = extras.search_songs(text)
        draft["song_raw"], draft["song_options"] = text, options
        if not options:
            draft["song"], draft["song_url"] = text, None
            draft.pop("song_raw", None)
            draft.pop("song_options", None)
            tg.send(chat_id, f"🎵 Записал как есть: {html.escape(text)}")
            after_song(chat_id, draft)
            return True
        storage.save_draft(chat_id, "song", draft)
        rows = [[(song_title(o)[:60], f"song:pick:{i}")] for i, o in enumerate(options)]
        rows.append([("✏️ Оставить как написал", "song:raw")])
        tg.send(chat_id, "Нашёл вот что — выбери:", tg.inline(rows))
        return True

    if step == "note":
        draft["note"] = text
        finish(chat_id, draft)
        return True

    return False


def on_draft_button(chat_id, message_id, step, draft, data):
    """Нажатие кнопки во время записи."""
    kind, _, value = data.partition(":")

    if kind == "score" and step == "score":
        draft["score"] = int(value)
        tg.edit(chat_id, message_id, f"⭐ Оценка: {value}/10")
        if not advance_edit(chat_id, draft):
            storage.save_draft(chat_id, "sleep", draft)
            tg.send(chat_id, "😴 Сколько спал? Нажми или напиши число (например, 7.5):", sleep_kb())

    elif kind == "sleep" and step == "sleep":
        draft["sleep"] = float(value)
        tg.edit(chat_id, message_id, f"😴 Сон: {float(value):g} ч")
        if not advance_edit(chat_id, draft):
            ask_energy(chat_id, draft)

    elif kind == "energy" and step == "energy":
        draft["energy"] = int(value)
        tg.edit(chat_id, message_id, f"⚡ Энергия: {value}/5")
        if not advance_edit(chat_id, draft):
            ask_song(chat_id, draft)

    elif kind == "song" and step == "song":
        if value == "skip":
            draft["song"], draft["song_url"] = None, None
            tg.edit(chat_id, message_id, "🎵 Без песни")
        elif value == "raw":
            draft["song"], draft["song_url"] = draft.get("song_raw"), None
            tg.edit(chat_id, message_id, f"🎵 {html.escape(draft['song'] or '')}")
        else:
            option = draft["song_options"][int(value.split(":")[1])]
            draft["song"], draft["song_url"] = song_title(option), option["url"]
            tg.edit(chat_id, message_id, f"🎵 {html.escape(draft['song'])}")
        draft.pop("song_options", None)
        draft.pop("song_raw", None)
        after_song(chat_id, draft)

    elif kind == "tag" and step == "tags":
        tag = TAGS_LIST[int(value)]
        draft["tags"].remove(tag) if tag in draft["tags"] else draft["tags"].append(tag)
        storage.save_draft(chat_id, "tags", draft)
        tg.edit_kb(chat_id, message_id, tags_kb(draft["tags"]))

    elif kind == "tags" and step == "tags":
        tags = draft["tags"]
        tg.edit(chat_id, message_id, "🏷 " + html.escape(", ".join(tags) if tags else "без тегов"))
        if not advance_edit(chat_id, draft):
            ask_note(chat_id, draft)

    elif kind == "note" and step == "note":
        draft["note"] = None
        tg.edit(chat_id, message_id, "💬 Без заметки")
        finish(chat_id, draft)

    else:
        return False  # старая кнопка с другого шага
    return True


# --- Точка входа для вебхука --------------------------------------------------------------

MENU_ACTIONS = {
    BTN_DAY: day_start, BTN_STATS: cmd_stats, BTN_PIXELS: cmd_pixels, BTN_HISTORY: cmd_history,
    BTN_SONGS: lambda c: tg.send(c, "🎵 Что показать?", songs_menu_kb()),
    BTN_CHART: cmd_chart, BTN_WEEK: cmd_week,
}
SIMPLE_COMMANDS = {
    "start": cmd_start, "help": cmd_start, "day": day_start, "stats": cmd_stats, "pixels": cmd_pixels,
    "chart": cmd_chart, "history": cmd_history, "export": cmd_export, "week": cmd_week,
    "songs": MENU_ACTIONS[BTN_SONGS],
}


def handle_message(msg):
    chat_id = msg["chat"]["id"]

    if "location" in msg:
        loc = msg["location"]
        storage.set_location(chat_id, loc["latitude"], loc["longitude"])
        weather = extras.get_weather(loc["latitude"], loc["longitude"], diary_date().isoformat())
        tg.send(chat_id, "📍 Запомнил! Погода теперь по этому месту." + (f"\nСегодня: {weather}" if weather else ""), MAIN_KB)
        return

    text = (msg.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/"):
        parts = text.split()
        command = parts[0][1:].split("@")[0].lower()
        if command == "cancel":
            storage.delete_draft(chat_id)
            tg.send(chat_id, "Окей, отменил. Запись не сохранена.", MAIN_KB)
        elif command == "remind":
            cmd_remind(chat_id, parts[1:])
        elif command == "edit":
            cmd_edit(chat_id, parts[1:])
        elif command in ("delete", "del"):
            cmd_delete(chat_id, parts[1:])
        elif command in SIMPLE_COMMANDS:
            SIMPLE_COMMANDS[command](chat_id)
        else:
            tg.send(chat_id, "Не знаю такой команды. Нажми /start, чтобы увидеть список.")
        return

    if text in MENU_ACTIONS:
        MENU_ACTIONS[text](chat_id)
        return

    step, draft = storage.get_draft(chat_id)
    if step and on_draft_text(chat_id, step, draft, text):
        return
    tg.send(chat_id, "Чтобы записать день, нажми «📝 Записать день» 🙂", MAIN_KB)


def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    message_id = cb["message"]["message_id"]
    data = cb.get("data", "")
    tg.answer_callback(cb["id"])

    if data == "day:start" or data.startswith("day:start:"):
        parts = data.split(":")
        day_start(chat_id, date.fromisoformat(parts[2]) if len(parts) > 2 else None)
    elif data.startswith("songs:"):
        on_songs_button(chat_id, data)
    elif data.startswith("pick:"):
        _, action, day_iso = data.split(":")
        show_edit_menu(chat_id, day_iso) if action == "edit" else confirm_delete(chat_id, day_iso)
    elif data.startswith("ef:"):
        _, field, day_iso = data.split(":")
        edit_field(chat_id, field, day_iso)
    elif data.startswith("del:"):
        on_delete_button(chat_id, message_id, data)
    else:
        step, draft = storage.get_draft(chat_id)
        if not step or not on_draft_button(chat_id, message_id, step, draft, data):
            tg.send(chat_id, "Эта кнопка уже неактуальна. Начни запись заново: /day")


def handle_update(update):
    if "message" in update:
        handle_message(update["message"])
    elif "callback_query" in update and "message" in update["callback_query"]:
        handle_callback(update["callback_query"])


# --- Задачи по расписанию (cron) ------------------------------------------------------------

def send_reminders():
    """Вечером: напомнить тем, кто ещё не записал день."""
    today = diary_date().isoformat()
    sent = 0
    for user in storage.all_users():
        if user["remind_time"] == "off" or storage.get_entry(user["chat_id"], today):
            continue
        tg.send(user["chat_id"], "🌙 Как прошёл день? Давай запишем — это меньше минуты.",
                tg.inline([[("📝 Записать", "day:start")]]))
        sent += 1
    return sent


def send_weekly():
    """В понедельник утром: итоги прошедшей недели."""
    today = diary_date()
    last_monday = today - timedelta(days=today.weekday() + 7)
    sent = 0
    for user in storage.all_users():
        text = stats.week_summary(storage.get_entries(user["chat_id"]), last_monday)
        if text:
            tg.send(user["chat_id"], text)
            sent += 1
    return sent
