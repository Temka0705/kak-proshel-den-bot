"""Статистика и картинка «год в пикселях»."""

import html
import io
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")  # рисуем без окна, сразу в файл
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

MONTHS_AXIS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _d(e):
    return date.fromisoformat(e["date"])


def _streak(entries, today):
    """Сколько дней подряд есть записи (считая сегодня или вчера)."""
    days = {_d(e) for e in entries}
    cur = today if today in days else today - timedelta(days=1)
    n = 0
    while cur in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def stats_text(entries, today, period=30):
    since = today - timedelta(days=period - 1)
    recent = [e for e in entries if _d(e) >= since and e["score"] is not None]
    if not recent:
        return "Пока нет записей за последние 30 дней. Начни с /day 🙂"

    scores = [e["score"] for e in recent]
    lines = [f"📊 <b>Последние {period} дней</b> — записей: {len(recent)}", ""]
    lines.append(f"⭐ Средняя оценка: <b>{statistics.mean(scores):.1f}</b>")

    with_sleep = [e for e in recent if e["sleep"] is not None]
    if with_sleep:
        lines.append(f"😴 Средний сон: <b>{statistics.mean(e['sleep'] for e in with_sleep):.1f} ч</b>")

    with_energy = [e["energy"] for e in recent if e["energy"] is not None]
    if with_energy:
        lines.append(f"⚡ Средняя энергия: <b>{statistics.mean(with_energy):.1f}/5</b>")

    streak = _streak(entries, today)
    if streak >= 2:
        lines.append(f"🔥 Серия: {streak} дн. подряд")

    best = max(recent, key=lambda e: e["score"])
    worst = min(recent, key=lambda e: e["score"])
    lines.append("")
    lines.append(f"🏆 Лучший день: {_d(best).day} {MONTHS_SHORT[_d(best).month - 1]} — {best['score']}/10")
    lines.append(f"🌧 Худший день: {_d(worst).day} {MONTHS_SHORT[_d(worst).month - 1]} — {worst['score']}/10")

    # Связь сна и оценки дня
    if len(with_sleep) >= 5:
        xs = [e["sleep"] for e in with_sleep]
        ys = [e["score"] for e in with_sleep]
        lines.append("")
        lines.append("<b>Сон и настроение</b>")
        try:
            r = statistics.correlation(xs, ys)
            strength = "почти не связаны" if abs(r) < 0.2 else ("умеренная связь" if abs(r) < 0.5 else "сильная связь")
            lines.append(f"Корреляция: {r:+.2f} ({strength})")
        except statistics.StatisticsError:
            pass  # все значения одинаковые — корреляцию не посчитать
        good = [e["score"] for e in with_sleep if e["sleep"] >= 7]
        bad = [e["score"] for e in with_sleep if e["sleep"] < 7]
        if good and bad:
            lines.append(
                f"Спал ≥ 7 ч → в среднем {statistics.mean(good):.1f}, "
                f"меньше 7 ч → {statistics.mean(bad):.1f}"
            )

    # Средняя оценка по тегам
    by_tag = defaultdict(list)
    for e in recent:
        for tag in filter(None, (e["tags"] or "").split(" | ")):
            by_tag[tag].append(e["score"])
    tag_rows = sorted(
        ((statistics.mean(v), tag, len(v)) for tag, v in by_tag.items() if len(v) >= 2),
        reverse=True,
    )
    if tag_rows:
        lines.append("")
        lines.append("<b>Средняя оценка по тегам</b>")
        for avg, tag, n in tag_rows[:6]:
            lines.append(f"{tag} → {avg:.1f} ({n} дн.)")

    return "\n".join(lines)


def pixels_png(entries, year):
    """Картинка-сетка на год: каждая клетка — день, цвет — оценка."""
    scores = {_d(e): e["score"] for e in entries if e["date"].startswith(str(year))}
    jan1, dec31 = date(year, 1, 1), date(year, 12, 31)
    start = jan1 - timedelta(days=jan1.weekday())  # понедельник первой недели
    ncols = (dec31 - start).days // 7 + 1
    cmap = plt.get_cmap("RdYlGn")

    fig, ax = plt.subplots(figsize=(ncols * 0.22 + 1, 2.9), dpi=200)
    d = jan1
    while d <= dec31:
        col, row = (d - start).days // 7, d.weekday()
        s = scores.get(d)
        color = cmap((s - 1) / 9) if s else "#e8e8e8"
        ax.add_patch(Rectangle((col, -row), 0.85, 0.85, color=color, linewidth=0))
        if d.day == 1:
            ax.text(col, 1.3, MONTHS_AXIS[d.month - 1], fontsize=7, color="#555")
        d += timedelta(days=1)

    for row, name in ((0, "Пн"), (2, "Ср"), (4, "Пт"), (6, "Вс")):
        ax.text(-1.6, -row + 0.2, name, fontsize=6, color="#777")

    # Легенда 1..10 снизу
    for i in range(1, 11):
        x = ncols - 11 + i
        ax.add_patch(Rectangle((x, -7.6), 0.85, 0.85, color=cmap((i - 1) / 9), linewidth=0))
        ax.text(x + 0.42, -8.4, str(i), fontsize=5, ha="center", va="top", color="#555")

    filled = len(scores)
    ax.set_title(f"Год в пикселях · {year}  ·  записей: {filled}", fontsize=9, loc="left")
    ax.set_xlim(-2, ncols + 0.5)
    ax.set_ylim(-9, 2.2)
    ax.set_aspect("equal")
    ax.axis("off")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


# --- Музыка ------------------------------------------------------------------

MONTHS_NOM = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
              "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]
GOOD_SCORE, BAD_SCORE = 8, 4  # хорошие дни: 8+, плохие: 4 и ниже


def _song_html(e):
    song = html.escape(e["song"])
    return f'<a href="{html.escape(e["song_url"])}">{song}</a>' if e["song_url"] else song


def _song_line(e):
    d = _d(e)
    return f"{d.day:02d}.{d.month:02d} · ⭐{e['score']} · {_song_html(e)}"


def _artist(e):
    return e["song"].split(" — ")[0] if " — " in e["song"] else None


def _with_songs(entries):
    return [e for e in entries if e["song"]]


def chunk_lines(lines, limit=3800):
    """Делит длинный текст на сообщения (у Telegram лимит 4096 символов)."""
    chunks, cur = [], ""
    for line in lines:
        if len(cur) + len(line) + 1 > limit:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    return chunks


def songs_month(entries, year, month):
    songs = [e for e in _with_songs(entries) if _d(e).year == year and _d(e).month == month]
    title = f"🎵 <b>Песни за {MONTHS_NOM[month - 1]} {year}</b>"
    if not songs:
        return [f"{title}\n\nВ этом месяце песен нет."]
    lines = [f"{title} — {len(songs)}", ""] + [_song_line(e) for e in songs]
    top = Counter(a for a in map(_artist, songs) if a).most_common(1)
    if top and top[0][1] >= 2:
        lines += ["", f"👑 Исполнитель месяца: {html.escape(top[0][0])} ({top[0][1]} дн.)"]
    return chunk_lines(lines)


def songs_all(entries):
    songs = _with_songs(entries)
    if not songs:
        return ["🎵 Песен пока нет — добавляй песню дня при записи 🙂"]
    unique = len({e["song"].lower() for e in songs})
    lines = [f"🎵 <b>Все песни</b> — {len(songs)} дн., разных треков: {unique}", ""]

    artists = [(a, n) for a, n in Counter(a for a in map(_artist, songs) if a).most_common(5) if n >= 2]
    if artists:
        lines.append("<b>Топ исполнителей</b>")
        lines += [f"{i}. {html.escape(a)} — {n} дн." for i, (a, n) in enumerate(artists, 1)]
        lines.append("")
    repeats = [(s, n) for s, n in Counter(e["song"] for e in songs).most_common(5) if n >= 2]
    if repeats:
        lines.append("<b>Песни, которые возвращались</b>")
        lines += [f"🔁 {html.escape(s)} — ×{n}" for s, n in repeats]
        lines.append("")

    current = None
    for e in songs:
        key = (_d(e).year, _d(e).month)
        if key != current:
            current = key
            lines.append(f"\n<b>{MONTHS_NOM[key[1] - 1].capitalize()} {key[0]}</b>")
        lines.append(_song_line(e))
    return chunk_lines(lines)


def soundtrack(entries, good=True):
    if good:
        days = [e for e in _with_songs(entries) if e["score"] >= GOOD_SCORE]
        title = f"🌞 <b>Саундтрек хороших дней</b> (оценка {GOOD_SCORE}+)"
        empty = "Пока нет хороших дней с песней — всё впереди ✨"
    else:
        days = [e for e in _with_songs(entries) if e["score"] <= BAD_SCORE]
        title = f"🌧 <b>Саундтрек плохих дней</b> (оценка {BAD_SCORE} и ниже)"
        empty = "Плохих дней с песней нет — и это отлично 🙌"
    if not days:
        return [f"{title}\n\n{empty}"]
    days.sort(key=lambda e: (e["score"], e["date"]), reverse=good)
    return chunk_lines([f"{title} — {len(days)}", ""] + [_song_line(e) for e in days])


# --- График настроения -------------------------------------------------------

def mood_chart_png(entries, today, days=30):
    """Линия оценки дня + столбики сна за последние `days` дней. None, если данных мало."""
    since = today - timedelta(days=days - 1)
    recent = [e for e in entries if since <= _d(e) <= today and e["score"] is not None]
    if len(recent) < 2:
        return None
    xs = [_d(e) for e in recent]
    ys = [e["score"] for e in recent]
    cmap = plt.get_cmap("RdYlGn")

    fig, ax = plt.subplots(figsize=(9, 4), dpi=170)
    sleep_pts = [(_d(e), e["sleep"]) for e in recent if e["sleep"] is not None]
    if sleep_pts:
        ax2 = ax.twinx()
        ax2.bar([p[0] for p in sleep_pts], [p[1] for p in sleep_pts], color="#9ec5ff", alpha=0.45, width=0.7)
        ax2.set_ylim(0, 14)
        ax2.set_ylabel("сон, ч", color="#5b8fd9", fontsize=8)
        ax2.tick_params(axis="y", colors="#5b8fd9", labelsize=7)
        for side in ("top", "left"):
            ax2.spines[side].set_visible(False)
        ax.set_zorder(ax2.get_zorder() + 1)
        ax.patch.set_visible(False)

    ax.plot(xs, ys, color="#444", linewidth=1.6, zorder=2)
    ax.scatter(xs, ys, c=[cmap((y - 1) / 9) for y in ys], s=55, edgecolors="#333", linewidths=0.6, zorder=3)
    avg = statistics.mean(ys)
    ax.axhline(avg, color="#999", linestyle="--", linewidth=0.9)
    ax.text(since, avg + 0.25, f"среднее {avg:.1f}", fontsize=7, color="#777")

    ax.set_ylim(0.5, 10.5)
    ax.set_yticks(range(1, 11))
    ax.set_xlim(since - timedelta(days=1), today + timedelta(days=1))
    ax.set_ylabel("оценка дня", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
    ax.grid(axis="y", alpha=0.25)
    ax.spines["top"].set_visible(False)
    ax.set_title(f"Настроение и сон · последние {days} дней", fontsize=10, loc="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf


# --- Итоги недели ------------------------------------------------------------

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _square(score):
    if score >= 8:
        return "🟩"
    if score >= 6:
        return "🟨"
    if score >= 4:
        return "🟧"
    return "🟥"


def week_summary(entries, monday):
    """Итоги недели, которая начинается с `monday`. None, если записей нет."""
    by_day = {_d(e): e for e in entries if e["score"] is not None}
    week = [by_day.get(monday + timedelta(days=i)) for i in range(7)]
    filled = [e for e in week if e]
    if not filled:
        return None
    prev = [by_day.get(monday - timedelta(days=7 - i)) for i in range(7)]
    prev = [e for e in prev if e]

    sunday = monday + timedelta(days=6)
    if monday.month == sunday.month:
        period = f"{monday.day}–{sunday.day} {MONTHS_SHORT[sunday.month - 1]}"
    else:
        period = f"{monday.day} {MONTHS_SHORT[monday.month - 1]} – {sunday.day} {MONTHS_SHORT[sunday.month - 1]}"
    lines = [f"🗓 <b>Итоги недели</b> · {period}", ""]

    for i, e in enumerate(week):
        if e:
            row = f"{WEEKDAYS_SHORT[i]} {_square(e['score'])} {e['score']}"
            if e["sleep"] is not None:
                row += f" · 😴 {e['sleep']:g} ч"
        else:
            row = f"{WEEKDAYS_SHORT[i]} ⬜ —"
        lines.append(row)

    avg = statistics.mean(e["score"] for e in filled)
    score_line = f"⭐ Средняя оценка: <b>{avg:.1f}</b>"
    if prev:
        delta = avg - statistics.mean(e["score"] for e in prev)
        arrow = "📈" if delta > 0.05 else ("📉" if delta < -0.05 else "➡️")
        score_line += f"  {arrow} {delta:+.1f} к прошлой неделе"
    lines += ["", score_line]
    sleeps = [e["sleep"] for e in filled if e["sleep"] is not None]
    if sleeps:
        lines.append(f"😴 Сон в среднем: {statistics.mean(sleeps):.1f} ч")
    energy = [e["energy"] for e in filled if e["energy"] is not None]
    if energy:
        lines.append(f"⚡ Энергия: {statistics.mean(energy):.1f}/5")
    lines.append(f"📝 Записано дней: {len(filled)}/7")

    best = max(filled, key=lambda e: (e["score"], e["date"]))
    lines += ["", f"🏆 Лучший день — {WEEKDAYS_SHORT[_d(best).weekday()]}, {best['score']}/10"]
    if best["note"]:
        lines.append(f"<i>«{html.escape(best['note'])}»</i>")

    song_day = best if best["song"] else next((e for e in reversed(filled) if e["song"]), None)
    if song_day:
        lines.append(f"🎵 Песня недели: {_song_html(song_day)}")

    tags = Counter(t for e in filled for t in (e["tags"] or "").split(" | ") if t).most_common(1)
    if tags:
        lines.append(f"🏷 Чаще всего: {html.escape(tags[0][0])} ({tags[0][1]} дн.)")
    return "\n".join(lines)
