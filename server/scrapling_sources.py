"""Camada de COLETA — Scrapling (https://github.com/D4Vinci/Scrapling).

Terceira fonte de dados do MineraAI: coleta pública em tempo real das páginas
web das plataformas, sem chave de API. Fica entre as APIs oficiais e o modo
demonstração:

    oficial (chaves)  →  coleta (Scrapling, dados públicos reais)  →  demo

Cada vídeo coletado recebe source="coleta". As funções de parsing são puras
e testáveis sem rede; o fetch usa Fetcher (impersonação de Chrome) ou,
opcionalmente, StealthyFetcher (navegador stealth — requer `scrapling install`).

Uso responsável: uma única requisição por busca, timeouts curtos, sem
contornar login/paywall (Instagram normalmente retorna vazio por exigir login).
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from . import storage
from .providers import normalize_video

FETCH_TIMEOUT = 20
RETRIES = 1


# ------------------------------------------------------------------ config
def coleta_enabled() -> bool:
    """Ligada por padrão — só desliga com '0'/'false' explícito ('' = ligado)."""
    v = storage.settings_get().get("SCRAPLING_ENABLED", "")
    return v not in ("0", "false", "no")


def stealthy_enabled() -> bool:
    cfg = storage.settings_get()
    return cfg.get("SCRAPLING_STEALTHY", "0") in ("1", "true", "yes")


def _fetch(url: str, params: dict | None = None):
    """Busca HTTP com fingerprint TLS de Chrome; StealthyFetcher opcional."""
    if stealthy_enabled():
        from scrapling.fetchers import StealthyFetcher
        return StealthyFetcher.fetch(url, headless=True, timeout=FETCH_TIMEOUT)
    from scrapling.fetchers import Fetcher
    return Fetcher.get(url, params=params, impersonate="chrome",
                       stealthy_headers=True, timeout=FETCH_TIMEOUT,
                       retries=RETRIES, retry_delay=1, follow_redirects=True)


def _html(page) -> str:
    body = getattr(page, "body", None)
    if isinstance(body, str):
        return body
    content = getattr(page, "html_content", None)
    return str(content) if content is not None else str(body)


# ------------------------------------------------------------------ util
_NUM_WORD = {"k": 1e3, "mil": 1e3, "m": 1e6, "mi": 1e6, "b": 1e9, "bi": 1e9}


def parse_count(txt) -> int:
    """'1.234.567 visualizações' | '1,2 mi' | '12K views' → int."""
    if txt is None:
        return 0
    if isinstance(txt, (int, float)):
        return int(txt)
    t = str(txt).lower().strip().replace("visualizações", "").replace("views", "") \
        .replace("exibições", "").replace("+", "").strip()
    m = re.search(r"([\d.,]+)\s*(mil|mi|bi|k|m|b)?", t)
    if not m:
        return 0
    num = m.group(1)
    mult = _NUM_WORD.get(m.group(2) or "", 1)
    # formato brasileiro: 1.234.567 | misto 1,2 mi | inglês 1.2M
    if mult > 1:
        num = num.replace(",", ".")
        try:
            return int(float(num) * mult)
        except ValueError:
            return 0
    if num.count(".") > 1:
        num = num.replace(".", "")
    num = num.replace(",", ".")
    try:
        return int(float(num))
    except ValueError:
        return 0


def parse_age_hours(txt) -> int:
    """'há 3 dias' / '3 days ago' / '2 semanas atrás' → horas."""
    if not txt:
        return 48
    t = str(txt).lower()
    m = re.search(r"(\d+)\s*(hora|hour|dia|day|semana|week|mês|mes|month|ano|year)", t)
    if not m:
        return 48
    n = int(m.group(1))
    unit = m.group(2)
    if unit.startswith(("hora", "hour")):
        return max(1, n)
    if unit.startswith(("dia", "day")):
        return n * 24
    if unit.startswith(("semana", "week")):
        return n * 168
    if unit.startswith(("mês", "mes", "month")):
        return n * 720
    return n * 8760


def _extract_hashtags(text: str) -> list[str]:
    return re.findall(r"#\w+", text or "")[:6]


# ------------------------------------------------------------------ YouTube
def parse_yt_initial_data(html: str) -> list[dict]:
    """Extrai vídeos do JSON embutido `ytInitialData` da busca do YouTube."""
    m = re.search(r"var ytInitialData = (\{.*?\});</script>", html, re.S)
    if not m:
        m = re.search(r'window\["ytInitialData"\] = (\{.*?\});', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    renderers: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if "videoRenderer" in node:
                renderers.append(node["videoRenderer"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)

    out = []
    for r in renderers:
        vid = r.get("videoId")
        if not vid:
            continue
        title = ""
        try:
            runs = r.get("title", {}).get("runs", [])
            title = "".join(x.get("text", "") for x in runs) or \
                r.get("title", {}).get("simpleText", "")
        except Exception:
            pass
        channel = ""
        try:
            channel = r["ownerText"]["runs"][0]["text"]
        except Exception:
            pass
        views_txt = r.get("viewCountText", {}).get("simpleText") or \
            "".join(x.get("text", "") for x in r.get("viewCountText", {}).get("runs", []))
        published = r.get("publishedTimeText", {}).get("simpleText", "")
        length = r.get("lengthText", {}).get("simpleText", "")
        dur = 0
        if length:
            parts = [int(p) for p in length.split(":") if p.isdigit()]
            while len(parts) < 3:
                parts.insert(0, 0)
            dur = parts[0] * 3600 + parts[1] * 60 + parts[2]
        thumb = ""
        try:
            thumbs = r["thumbnail"]["thumbnails"]
            thumb = thumbs[-1]["url"]
        except Exception:
            pass
        out.append({
            "id": vid, "title": title, "author": channel, "handle": channel,
            "views": parse_count(views_txt), "likes": 0, "comments": 0, "shares": 0,
            "age_hours": parse_age_hours(published),
            "hashtags": [], "duration": dur or None,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "thumb": thumb, "source": "coleta",
        })
    return out


def scrape_youtube(q: str, limit: int = 12) -> list[dict]:
    page = _fetch("https://www.youtube.com/results",
                  params={"search_query": q, "hl": "pt", "gl": "BR"})
    items = parse_yt_initial_data(_html(page))
    return [normalize_video(v, "youtube") for v in items[:limit]]


# ------------------------------------------------------------------ TikTok
def parse_tiktok_universal_data(html: str) -> list[dict]:
    """Extrai vídeos do JSON `__UNIVERSAL_DATA_FOR_REHYDRATION__` da busca."""
    m = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(\{.*?\})</script>',
        html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    candidates: list[dict] = []

    def walk(node):
        # item de vídeo: tem "stats" com playCount + "desc" ou "id"
        if isinstance(node, dict):
            stats = node.get("stats")
            if isinstance(stats, dict) and "playCount" in stats and \
                    ("desc" in node or "video" in node):
                candidates.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)

    out, seen = [], set()
    for item in candidates:
        vid = str(item.get("id") or item.get("video", {}).get("id") or "")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        desc = item.get("desc", "") or "Vídeo TikTok"
        author = item.get("author", {})
        username = author.get("uniqueId") or author.get("nickname") or ""
        duration = item.get("video", {}).get("duration")
        out.append({
            "id": vid, "title": desc[:120], "author": username,
            "handle": f"@{username}" if username else "",
            "views": parse_count(item.get("stats", {}).get("playCount", 0)),
            "likes": parse_count(item.get("stats", {}).get("diggCount", 0)),
            "comments": parse_count(item.get("stats", {}).get("commentCount", 0)),
            "shares": parse_count(item.get("stats", {}).get("shareCount", 0)),
            "age_hours": max(1, int((
                __import__("time").time() - int(item.get("createTime", 0))
            ) / 3600)) if item.get("createTime") else 48,
            "hashtags": _extract_hashtags(desc),
            "duration": int(duration) if duration else None,
            "url": f"https://www.tiktok.com/@{username}/video/{vid}" if username else "",
            "source": "coleta",
        })
    return out


def scrape_tiktok(q: str, limit: int = 12) -> list[dict]:
    page = _fetch("https://www.tiktok.com/search", params={"q": q})
    items = parse_tiktok_universal_data(_html(page))
    return [normalize_video(v, "tiktok") for v in items[:limit]]


# ------------------------------------------------------------------ Instagram
def scrape_instagram(q: str, limit: int = 12) -> list[dict]:
    """Tenta a página pública de hashtag do Instagram.

    Na prática o Instagram exige login para buscas; mantemos a tentativa
    (a Meta pode servir dados limitados dependendo da região) e retornamos
    vazio sem quebrar — o recomendado para IG continua sendo a Graph API.
    """
    tag = q.strip().lstrip("#").split()[0] if q.strip() else ""
    if not tag:
        return []
    try:
        page = _fetch(f"https://www.instagram.com/explore/tags/{tag}/")
    except Exception:
        return []
    html = _html(page)
    # procura JSON de mídia embutido em páginas públicas (quando existem)
    m = re.search(r'"edge_hashtag_to_media":\s*(\{.*?\})\s*,\s*"edge_hashtag_to_related', html, re.S)
    if not m:
        return []
    try:
        media = json.loads(m.group(1)).get("edges", [])
    except json.JSONDecodeError:
        return []
    out = []
    for edge in media[:limit]:
        node = edge.get("node", {})
        out.append(normalize_video({
            "id": node.get("id", ""),
            "title": (node.get("edge_media_to_caption", {})
                      .get("edges", [{}])[0].get("node", {})
                      .get("text", "Post do Instagram"))[:120],
            "author": "", "handle": "",
            "views": max(parse_count(node.get("video_view_count", 0)),
                         parse_count(node.get("edge_liked_by", {}).get("count", 0)) * 10),
            "likes": parse_count(node.get("edge_liked_by", {}).get("count", 0)),
            "comments": parse_count(node.get("edge_media_to_comment", {}).get("count", 0)),
            "shares": 0, "age_hours": 48,
            "hashtags": [f"#{tag}"],
            "url": f"https://www.instagram.com/p/{node.get('shortcode', '')}/",
            "thumb": node.get("display_url"),
            "source": "coleta",
        }, "instagram"))
    return out


# ------------------------------------------------------------------ Google Trends
def google_trends_br(limit: int = 12) -> list[dict]:
    """Termos em alta agora no Brasil — RSS público oficial do Google Trends."""
    page = _fetch("https://trends.google.com/trending/rss", params={"geo": "BR"})
    raw = _html(page)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    ns_ht = "{https://trends.google.com/trending/rss}"
    out = []
    for item in root.iter("item"):
        title = item.findtext("title", "").strip()
        traffic = item.findtext(f"{ns_ht}approx_traffic", "0")
        news = item.find(f"{ns_ht}news")
        source_title = ""
        if news is not None:
            first = news.find(f"{ns_ht}newsItem")
            if first is not None:
                source_title = first.findtext(f"{ns_ht}source", "") or \
                    first.findtext(f"{ns_ht}title", "")
        out.append({"term": title, "traffic": parse_count(traffic),
                    "traffic_raw": traffic, "source": source_title})
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ agregado
import time as _time

_circuit_until = 0.0   # cooldown após falha total (rede restrita etc.)
CIRCUIT_SECONDS = 600


def collect(q: str, platforms: list[str], limit: int = 10) -> dict:
    """Executa a coleta para as plataformas pedidas (sequencial, 1 req cada).

    Circuit breaker: se uma varredura falhar por completo (0 vídeos + erros),
    a coleta entra em cooldown de 10 min para não atrasar buscas em ambientes
    sem saída de rede. Qualquer sucesso reseta o circuito.
    """
    global _circuit_until
    now = _time.time()
    if now < _circuit_until:
        return {"videos": [], "errors": ["coleta em cooldown (falha recente de rede)"]}

    videos, errors = [], []
    scrapers = {"youtube": scrape_youtube, "tiktok": scrape_tiktok,
                "instagram": scrape_instagram}
    for p in platforms:
        fn = scrapers.get(p)
        if not fn:
            continue
        try:
            videos.extend(fn(q, limit))
        except Exception as e:
            errors.append(f"{p}: {type(e).__name__}")

    if videos:
        _circuit_until = 0.0
    elif errors:
        _circuit_until = now + CIRCUIT_SECONDS
    return {"videos": videos, "errors": errors}


def health_check() -> dict:
    """Teste rápido: coleta real de 3 resultados no YouTube."""
    try:
        vids = scrape_youtube("tendências", 3)
        if vids:
            return {"ok": True,
                    "message": f"Coleta funcionando — {len(vids)} vídeos reais obtidos. "
                               f"Ex.: “{vids[0]['title'][:60]}”"}
        return {"ok": False, "message": "Página carregou mas nenhum vídeo foi extraído."}
    except Exception as e:
        return {"ok": False,
                "message": f"Falha na coleta: {type(e).__name__}: {str(e)[:110]}. "
                           "Verifique se este servidor tem acesso direto à internet."}
