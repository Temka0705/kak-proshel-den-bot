"""Картинки для README: настоящий код бота + выдуманные (демо) записи дневника.

Запуск из корня проекта:  python scripts/make_screenshots.py
Результат — PNG в папке docs/. Нужны Pillow (идёт с matplotlib) и установленный Google Chrome.
"""

import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("BOT_TOKEN", "0:demo")  # токен не нужен — в Telegram ничего не отправляется

from PIL import Image  # noqa: E402

from app import bot, stats  # noqa: E402

OUT = ROOT / "docs"
TODAY = date(2026, 11, 18)
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "google-chrome",
    "chromium",
]

SONGS = [
    ("The Weeknd — Blinding Lights", "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"),
    ("Arctic Monkeys — 505", None),
    ("Земфира — Хочешь?", None),
    ("Кино — Группа крови", None),
    ("Billie Eilish — Lovely", None),
    ("Mac DeMarco — Chamber of Reflection", None),
    ("Radiohead — No Surprises", None),
    ("Monetochka — Каждый раз", None),
    ("Daft Punk — Get Lucky", None),
    ("Frank Ocean — Pink + White", None),
]
NOTES = [
    "Сдал коллоквиум по матану 🎉", "Гуляли с друзьями до ночи", "Весь день над проектом",
    "Наконец выспался", "Сходил в зал после перерыва", "Дождь и дедлайны", "Кино с семьёй",
    "Защитил домашку по ML", None, None, None,
]
WEATHER = ["☀️ ясно, +3…+9°", "☁️ пасмурно, 0…+4°", "🌧 дождь, +2…+6°", "❄️ снег, -3…0°", "🌤 переменная облачность, +1…+7°"]


def demo_entries():
    """~10 месяцев выдуманных записей: оценка зависит от сна, выходных и спорта."""
    rnd = random.Random(42)
    entries = []
    d = date(2026, 1, 12)
    while d <= TODAY:
        recent = d >= TODAY - timedelta(days=10)
        if recent or rnd.random() > 0.12:  # иногда день пропущен, последние 10 дней — без пропусков
            sleep = round(min(10, max(4.5, rnd.gauss(7.2, 1.0))) * 2) / 2
            tags = rnd.sample(bot.TAGS_LIST[:8], rnd.choice([1, 2, 2, 3]))
            score = 0.3 + 0.75 * sleep + (1 if d.weekday() >= 5 else 0) + rnd.gauss(0, 1.3)
            score += 0.8 if "🏃 спорт" in tags else 0
            score += 0.6 if "👥 друзья" in tags else 0
            score = int(min(10, max(1, round(score))))
            song, url = rnd.choice(SONGS) if rnd.random() < 0.85 else (None, None)
            entries.append({
                "date": d.isoformat(), "score": score, "sleep": sleep,
                "energy": int(min(5, max(1, round(score / 2 + rnd.gauss(0, 0.6))))),
                "song": song, "song_url": url, "tags": " | ".join(tags),
                "note": rnd.choice(NOTES), "weather": rnd.choice(WEATHER),
            })
        d += timedelta(days=1)
    # красивая «сегодняшняя» запись для экрана записи дня
    entries[-1].update(score=8, sleep=7.5, energy=4, song=SONGS[0][0], song_url=SONGS[0][1],
                       tags="🏃 спорт | 👥 друзья", note="Сдал коллоквиум по матану 🎉",
                       weather="🌤 переменная облачность, +1…+7°")
    return entries


# --- HTML «как в Telegram» ---------------------------------------------------------

CSS = """
* { box-sizing: border-box; }
body { margin: 0; width: 400px; font: 15px/1.38 "Segoe UI", Roboto, -apple-system, sans-serif;
       background: linear-gradient(160deg, #c5dbb0 0%, #9fc3a8 55%, #86b3a6 100%); color: #000; }
.top { background: #fff; padding: 10px 14px; display: flex; align-items: center; gap: 10px;
       box-shadow: 0 1px 3px rgba(0,0,0,.15); }
.ava { width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center; font-size: 22px;
       background: linear-gradient(135deg, #7bc6ff, #4f8ef7); }
.name { font-weight: 600; } .sub { color: #8a8a8a; font-size: 13px; }
.chat { padding: 10px 8px 12px; display: flex; flex-direction: column; gap: 6px; }
.msg { max-width: 86%; padding: 7px 11px 8px; border-radius: 14px; white-space: pre-wrap; overflow-wrap: anywhere;
       box-shadow: 0 1px 1px rgba(0,0,0,.12); }
.bot { background: #fff; align-self: flex-start; border-bottom-left-radius: 4px; }
.me { background: #e3fbcf; align-self: flex-end; border-bottom-right-radius: 4px; }
.msg a { color: #1a7fc6; text-decoration: none; }
.kb { align-self: flex-start; width: 86%; display: grid; gap: 4px; margin-top: -2px; }
.row { display: flex; gap: 4px; }
.btn { flex: 1; text-align: center; padding: 7px 4px; border-radius: 9px; color: #fff; font-size: 14px;
       background: rgba(40, 80, 60, .32); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.menu { background: #f1f1f1; padding: 6px; display: grid; gap: 5px; border-top: 1px solid #ddd; }
.menu .btn { background: #fff; color: #222; box-shadow: 0 1px 1px rgba(0,0,0,.15); }
.time { float: right; color: #9aa; font-size: 11px; margin: 6px 0 -4px 10px; }
#end { height: 2px; background: #ff00ff; }
"""


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def msg(html, me=False, time="22:14"):
    return f'<div class="msg {"me" if me else "bot"}">{html.strip()}<span class="time">{time}</span></div>'


def kb(rows):
    inner = "".join('<div class="row">' + "".join(f'<div class="btn">{esc(b)}</div>' for b in r) + "</div>"
                    for r in rows)
    return f'<div class="kb">{inner}</div>'


def menu():
    rows = [[bot.BTN_DAY], [bot.BTN_STATS, bot.BTN_CHART], [bot.BTN_SONGS, bot.BTN_WEEK],
            [bot.BTN_PIXELS, bot.BTN_HISTORY]]
    return '<div class="menu">' + "".join(
        '<div class="row">' + "".join(f'<div class="btn">{esc(b)}</div>' for b in r) + "</div>" for r in rows) + "</div>"


def page(parts, with_menu=False):
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head><body>"
            "<div class='top'><div class='ava'>📔</div><div><div class='name'>Как прошёл день?</div>"
            "<div class='sub'>бот</div></div></div>"
            f"<div class='chat'>{''.join(parts)}</div>{menu() if with_menu else ''}<div id='end'></div></body></html>")


def screen_record(entries):
    e = entries[-1]
    d = date.fromisoformat(e["date"])
    tags = e["tags"].split(" | ")
    return page([
        msg(esc(bot.BTN_DAY), me=True),
        msg(f"📝 Записываем {bot.fmt_date(d)}\n\n⭐ Как прошёл день? Оцени от 1 до 10:"),
        kb([[str(i) for i in range(1, 6)], [str(i) for i in range(6, 11)]]),
        msg("⭐ Оценка: 8/10\n😴 Сон: 7.5 ч\n⚡ Энергия: 4/5"),
        msg("open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b", me=True, time="22:15"),
        msg("🎵 The Weeknd — Blinding Lights", time="22:15"),
        msg("🏷 Что было сегодня? Отметь всё подходящее:", time="22:15"),
        kb([[("✅ " if t in tags else "") + t for t in bot.TAGS_LIST[i:i + 2]] for i in range(0, 6, 2)]
           + [["Готово ✔️"]]),
        msg(esc(e["note"]), me=True, time="22:16"),
        msg("✅ Записал!\n\n" + bot.render_entry(e), time="22:16"),
    ])


def screen_week(entries):
    monday = TODAY - timedelta(days=TODAY.weekday() + 7)
    return page([
        msg("🗓 Неделя", me=True, time="10:02"),
        msg(stats.week_summary(entries, monday), time="10:02"),
    ], with_menu=True)


def screen_songs(entries):
    good = stats.soundtrack(entries, good=True)[0].strip().split("\n")
    good = "\n".join(good[:11]) + "\n…"
    return page([
        msg(esc(bot.BTN_SONGS), me=True, time="23:40"),
        msg("🎵 Что показать?", time="23:40"),
        kb([["📅 За этот месяц", "💿 За всё время"], ["🌞 Хорошие дни", "🌧 Плохие дни"]]),
        msg(good, time="23:40"),
    ])


def screen_stats(entries):
    return page([
        msg(esc(bot.BTN_STATS), me=True, time="23:41"),
        msg(stats.stats_text(entries, TODAY), time="23:41"),
    ])


# --- Рендер HTML -> PNG ----------------------------------------------------------------

def find_chrome():
    for c in CHROME_CANDIDATES:
        if Path(c).exists() or shutil.which(c):
            return shutil.which(c) or c
    sys.exit("Не нашёл Google Chrome — он нужен, чтобы отрисовать экраны переписки.")


def render(html, out_png, chrome, tmp):
    src = Path(tmp) / (out_png.stem + ".html")
    src.write_text(html, encoding="utf-8")
    raw = Path(tmp) / (out_png.stem + "_raw.png")
    subprocess.run([
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
        f"--user-data-dir={Path(tmp) / 'profile'}", "--window-size=400,2400",
        f"--screenshot={raw}", src.as_uri(),
    ], check=True, capture_output=True)
    img = Image.open(raw).convert("RGB")
    px = img.load()
    w, h = img.size
    cut = h
    for y in range(h):  # обрезаем по розовой метке #end в конце страницы
        r, g, b = px[w // 2, y]
        if r > 240 and g < 20 and b > 240:
            cut = y
            break
    img.crop((0, 0, w, cut)).save(out_png, optimize=True)


def main():
    OUT.mkdir(exist_ok=True)
    entries = demo_entries()

    (OUT / "pixels.png").write_bytes(stats.pixels_png(entries, 2026).read())
    (OUT / "chart.png").write_bytes(stats.mood_chart_png(entries, TODAY).read())

    chrome = find_chrome()
    with tempfile.TemporaryDirectory() as tmp:
        for name, builder in [("record", screen_record), ("week", screen_week),
                              ("songs", screen_songs), ("stats", screen_stats)]:
            render(builder(entries), OUT / f"screen_{name}.png", chrome, tmp)
    print("Готово:", ", ".join(sorted(p.name for p in OUT.glob("*.png"))))


if __name__ == "__main__":
    main()
