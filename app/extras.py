"""Внешние бесплатные API без ключей: погода (Open-Meteo), песни (iTunes, Spotify)."""

import html
import logging
import re

import httpx

log = logging.getLogger(__name__)


# --- Погода -------------------------------------------------------------------

def _describe(code):
    """Код погоды WMO -> (эмодзи, текст)."""
    if code == 0:
        return "☀️", "ясно"
    if code in (1, 2):
        return "🌤", "переменная облачность"
    if code == 3:
        return "☁️", "пасмурно"
    if code in (45, 48):
        return "🌫", "туман"
    if 51 <= code <= 57:
        return "🌦", "морось"
    if 61 <= code <= 67:
        return "🌧", "дождь"
    if 71 <= code <= 77:
        return "❄️", "снег"
    if 80 <= code <= 82:
        return "🌧", "ливень"
    if code in (85, 86):
        return "🌨", "снегопад"
    if code >= 95:
        return "⛈", "гроза"
    return "🌡", "погода"


def _temp(t):
    t = round(t)
    return f"+{t}" if t > 0 else str(t)


def get_weather(lat, lon, day_iso):
    """Погода за день строкой, например '🌧 дождь, +3…+7°'. None, если не получилось."""
    try:
        r = httpx.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min",
                "timezone": "auto",
                "start_date": day_iso,
                "end_date": day_iso,
            },
            timeout=8,
        )
        r.raise_for_status()
        daily = r.json()["daily"]
        emoji, text = _describe(daily["weather_code"][0])
        tmin, tmax = daily["temperature_2m_min"][0], daily["temperature_2m_max"][0]
        return f"{emoji} {text}, {_temp(tmin)}…{_temp(tmax)}°"
    except Exception as exc:  # погода — бонус, из-за неё запись не должна падать
        log.warning("Погода: %s", exc)
        return None


# --- Поиск песни по названию (iTunes) ----------------------------------------------

def search_songs(query, limit=3):
    """Список {'artist', 'track', 'url'} или []."""
    with httpx.Client(timeout=8) as client:
        for country in ("RU", "US"):
            try:
                r = client.get(
                    "https://itunes.apple.com/search",
                    params={"term": query, "media": "music", "entity": "song",
                            "limit": limit, "country": country},
                )
                results = r.json().get("results", [])
            except Exception as exc:
                log.warning("iTunes (%s): %s", country, exc)
                continue
            if results:
                return [{"artist": x.get("artistName", ""), "track": x.get("trackName", ""),
                         "url": x.get("trackViewUrl")} for x in results]
    return []


# --- Spotify: ссылка из «Поделиться → Копировать ссылку» ---------------------------

SPOTIFY_HOSTS = ("open.spotify.com", "spotify.link", "spotify.app.link")


def find_spotify_link(text):
    for word in text.split():
        if any(host in word for host in SPOTIFY_HOSTS):
            return word if word.startswith("http") else "https://" + word
    return None


def spotify_track(url):
    """Ссылка Spotify -> {'artist', 'track', 'url'} или None."""
    try:
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            if "open.spotify.com" not in url:  # короткая ссылка spotify.link -> редирект
                url = str(client.get(url).url)
            url = url.split("?")[0]
            r = client.get("https://open.spotify.com/oembed", params={"url": url})
            r.raise_for_status()
            track = r.json().get("title", "")
            artist = ""
            page = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            m = re.search(r'<meta property="og:description" content="([^"]+)"', page.text)
            if m:  # "Исполнитель · Альбом · Song · 2020"
                artist = html.unescape(m.group(1)).split(" · ")[0]
        return {"artist": artist, "track": track, "url": url} if track else None
    except Exception as exc:
        log.warning("Spotify: %s", exc)
        return None
