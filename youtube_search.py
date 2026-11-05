"""Busca do YouTube localizada em português, sem tradução artificial de títulos."""
import base64
import re
from urllib.parse import quote, quote_plus

SORT = {"relevance": 0, "date": 2, "views": 3}
UPLOADED = {"any": 0, "today": 2, "week": 3, "month": 4, "year": 5}
LENGTH = {"any": 0, "short": 4, "medium": 5, "long": 2}
ID_RE = re.compile(r"[A-Za-z0-9_-]{11}\Z")


def _varint(number):
    result = bytearray()
    while True:
        byte = number & 127
        number >>= 7
        result.append(byte | (128 if number else 0))
        if not number:
            return bytes(result)


def _field(number, value):
    return _varint(number << 3) + _varint(value)


def search_token(sort="relevance", published="any", duration="any", live=False):
    if sort not in SORT or published not in UPLOADED or duration not in LENGTH:
        raise ValueError("Filtro de pesquisa inválido.")
    inner = _field(2, 1)  # Apenas vídeos, sem canais ou listas.
    if published != "any":
        inner = _field(1, UPLOADED[published]) + inner
    if duration != "any":
        inner += _field(3, LENGTH[duration])
    if live:
        inner += _field(8, 1)
    outer = _field(1, SORT[sort]) if sort != "relevance" else b""
    outer += bytes([0x12]) + _varint(len(inner)) + inner
    return base64.urlsafe_b64encode(outer).decode("ascii").rstrip("=")


def search_videos(query, sort="relevance", published="any", duration="any", live=False, limit=30):
    query = str(query).strip()
    if not 1 <= len(query) <= 160:
        raise ValueError("Digite de 1 a 160 caracteres para pesquisar.")
    limit = min(max(int(limit), 1), 36)
    import yt_dlp
    token = search_token(sort, published, duration, live)
    url = "https://www.youtube.com/results?search_query=" + quote_plus(query) + "&sp=" + quote(token)
    opts = {
        "quiet": True, "no_warnings": True, "extract_flat": True,
        "skip_download": True, "socket_timeout": 20, "playlistend": limit,
        "extractor_args": {"youtube": {"lang": ["pt"], "player_client": ["default"]}},
        "http_headers": {"Accept-Language": "pt-BR,pt;q=0.9"},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        data = ydl.extract_info(url, download=False)
    videos, seen = [], set()
    for item in (data or {}).get("entries") or []:
        if not item:
            continue
        video_id = item.get("id", "")
        if not ID_RE.fullmatch(video_id or "") or video_id in seen:
            continue
        live_status = str(item.get("live_status") or "")
        is_live = live_status == "is_live" or item.get("is_live") is True
        if live and not is_live:
            continue
        if is_live and not live:
            continue
        seen.add(video_id)
        views = item.get("view_count")
        videos.append({
            "id": video_id, "title": item.get("title") or "Sem título",
            "channel": item.get("channel") or item.get("uploader") or "",
            "duration": item.get("duration") or 0, "views": int(views) if isinstance(views, int) else None,
            "live": bool(is_live), "live_status": live_status,
            "thumbnail": "https://i.ytimg.com/vi/" + video_id + "/hqdefault.jpg",
            "url": "https://www.youtube.com/watch?v=" + video_id,
        })
    return videos
