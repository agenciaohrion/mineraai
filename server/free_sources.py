"""Fontes GRATUITAS adicionais — sem chave na maioria.

  Reddit JSON público ....... pauta viral por subreddit (ideias de conteúdo)
  Mercado Livre API ........... produtos reais BR: preço, vendidos, reviews
  Google Suggest .............. autocomplete = demanda de busca real
  oEmbed (YouTube/TikTok) ..... metadados reais de um link (Viral Lab)
  Pexels ...................... B-roll gratuito (requer chave grátis opcional)

Todas retornam [] com flag de indisponibilidade quando a rede falha —
nenhuma delas derruba a plataforma.
"""
from __future__ import annotations

import json
import re
import time

from . import storage
from .scrapling_sources import _fetch, _html, coleta_enabled

UA = {"User-Agent": "MineraAI/1.0 (pesquisa de tendências; contato: admin)"}


# ------------------------------------------------------------------ Reddit
def reddit_trending(subreddit: str = "Brasil", limit: int = 10,
                    window: str = "week") -> list[dict]:
    """Top posts do subreddit — JSON público oficial, sem chave."""
    url = f"https://old.reddit.com/r/{subreddit}/top.json"
    page = _fetch(url, params={"t": window, "limit": min(limit, 25)})
    data = json.loads(_html(page))
    out = []
    for child in data.get("data", {}).get("children", []):
        d = child.get("data", {})
        if d.get("stickied"):
            continue
        out.append({
            "id": d.get("id"),
            "title": d.get("title", ""),
            "score": d.get("score", 0),
            "comments": d.get("num_comments", 0),
            "author": d.get("author", ""),
            "subreddit": d.get("subreddit", subreddit),
            "url": "https://www.reddit.com" + d.get("permalink", ""),
            "age_hours": max(1, int((time.time() - d.get("created_utc", 0)) / 3600)),
            "is_video": d.get("is_video", False),
        })
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ Mercado Livre
def mercadolivre_search(q: str, limit: int = 12) -> list[dict]:
    """API pública oficial do Mercado Livre (site MLB = Brasil) — sem chave."""
    page = _fetch("https://api.mercadolibre.com/sites/MLB/search",
                  params={"q": q, "limit": min(limit, 30)})
    data = json.loads(_html(page))
    out = []
    for r in data.get("results", []):
        out.append({
            "id": r.get("id"),
            "title": r.get("title", ""),
            "price": r.get("price", 0),
            "original_price": r.get("original_price"),
            "currency": r.get("currency_id", "BRL"),
            "sold_quantity": r.get("sold_quantity", 0),
            "reviews": r.get("reviews", {}),
            "rating": (r.get("reviews") or {}).get("rating_average", 0),
            "total_reviews": (r.get("reviews") or {}).get("total", 0),
            "permalink": r.get("permalink", ""),
            "thumbnail": (r.get("thumbnail") or "").replace("http://", "https://"),
            "free_shipping": (r.get("shipping") or {}).get("free_shipping", False),
            "official_store": bool(r.get("official_store_id")),
            "category_id": r.get("category_id", ""),
        })
    # ordena por mais vendidos — o sinal mais forte pra garimpo
    out.sort(key=lambda x: -(x.get("sold_quantity") or 0))
    return out


def mercadolivre_trend_signal(items: list[dict]) -> dict:
    """Resumo agregado para o módulo Produtos."""
    if not items:
        return {}
    prices = [i["price"] for i in items if i.get("price")]
    sold = [i.get("sold_quantity") or 0 for i in items]
    ratings = [i["rating"] for i in items if i.get("rating")]
    return {
        "count": len(items),
        "price_min": min(prices) if prices else 0,
        "price_max": max(prices) if prices else 0,
        "price_median": sorted(prices)[len(prices) // 2] if prices else 0,
        "total_sold": sum(sold),
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else 0,
    }


# ------------------------------------------------------------------ Google Suggest
def google_suggest(q: str, hl: str = "pt-BR") -> list[str]:
    """Autocomplete do Google — sinal gratuito de demanda de busca."""
    page = _fetch("https://suggestqueries.google.com/complete/search",
                  params={"client": "firefox", "q": q, "hl": hl})
    data = json.loads(_html(page))
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return [s for s in data[1][:12] if isinstance(s, str)]
    return []


# ------------------------------------------------------------------ oEmbed
def oembed_lookup(url: str) -> dict:
    """Metadados reais e oficiais de um link de vídeo (YouTube/TikTok)."""
    url = (url or "").strip()
    if "tiktok.com" in url:
        api = "https://www.tiktok.com/oembed"
        platform = "tiktok"
    elif "youtube.com" in url or "youtu.be" in url:
        api = "https://www.youtube.com/oembed"
        platform = "youtube"
    else:
        return {}
    try:
        page = _fetch(api, params={"url": url, "format": "json"})
        d = json.loads(_html(page))
        return {
            "platform": platform,
            "title": d.get("title", ""),
            "author": d.get("author_name", ""),
            "author_url": d.get("author_url", ""),
            "thumb": d.get("thumbnail_url", ""),
            "source": "oEmbed oficial (gratuito)",
        }
    except Exception:
        return {}


def looks_like_video_url(text: str) -> bool:
    t = (text or "").lower()
    return any(d in t for d in ("tiktok.com", "youtube.com", "youtu.be"))


# ------------------------------------------------------------------ Pexels
def pexels_broll(q: str, limit: int = 12) -> dict:
    """B-roll (fotos/vídeos gratuitos) para a Fábrica — chave grátis opcional."""
    key = storage.settings_get().get("PEXELS_API_KEY", "")
    if not key:
        return {"ok": False, "items": [],
                "message": "Adicione sua chave Pexels (grátis) em APIs & Conexões."}
    try:
        from scrapling.fetchers import Fetcher
        page = Fetcher.get("https://api.pexels.com/videos/search",
                           params={"query": q, "per_page": min(limit, 20)},
                           headers={"Authorization": key},
                           timeout=15, retries=1)
        data = json.loads(_html(page))
        items = []
        for v in data.get("videos", []):
            files = v.get("video_files", [])
            best = max(files, key=lambda f: f.get("width", 0)) if files else {}
            items.append({
                "id": v.get("id"),
                "url": v.get("url", ""),
                "video_file": best.get("link", ""),
                "width": best.get("width"), "height": best.get("height"),
                "duration": v.get("duration"),
                "image": v.get("image", ""),
                "user": (v.get("user") or {}).get("name", ""),
            })
        return {"ok": True, "items": items}
    except Exception as e:
        return {"ok": False, "items": [],
                "message": f"Pexels indisponível: {type(e).__name__}"}
