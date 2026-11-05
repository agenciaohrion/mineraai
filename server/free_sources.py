"""Fontes gratuitas — cada uma com sua PRÓPRIA configuração e teste.

Regra da casa: nenhuma fonte compartilha credencial com outra. Se a fonte precisa
de chave, ela tem campo próprio na tela de APIs & Conexões; se não precisa, ela
declara isso abertamente e aceita só ajustes (timeout, proxy, região).

  Reddit .............. OAuth client_credentials (app "script") + fallback público
  Mercado Livre ....... OAuth authorization_code completo + refresh automático
  Google Suggest ...... sem chave (região/idioma configuráveis) + CSE opcional
  oEmbed .............. sem chave (timeout/proxy configuráveis)
  Google Trends ....... sem chave (geo/idioma configuráveis)
  Pexels .............. API key própria (grátis)

Todas as funções são síncronas e chamadas via `asyncio.to_thread` nos endpoints:
falha de rede vira lista vazia + diagnóstico, nunca derruba a plataforma.
"""
from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from . import storage

UA_PADRAO = "MineraAI/2.0 (pesquisa de tendências; +https://minera.ai)"
TIMEOUT_PADRAO = 20.0

# tokens em memória (evita round-trip de OAuth a cada requisição)
_reddit_cache: dict = {"token": "", "exp": 0.0}


# ------------------------------------------------------------------ utilidades
def _cfg() -> dict:
    return storage.settings_get()


def _client(source: str, timeout: Optional[float] = None,
            proxy: Optional[str] = None, headers: Optional[dict] = None) -> httpx.Client:
    """Cliente HTTP por fonte — UA e proxy independentes por integração."""
    cfg = _cfg()
    if timeout is None:
        try:
            timeout = float(cfg.get(f"{source.upper()}_TIMEOUT") or TIMEOUT_PADRAO)
        except (TypeError, ValueError):
            timeout = TIMEOUT_PADRAO
    proxy = proxy if proxy is not None else cfg.get(f"{source.upper()}_PROXY") or None
    h = {"User-Agent": UA_PADRAO, "Accept": "application/json, text/plain, */*"}
    h.update(headers or {})
    return httpx.Client(timeout=timeout, proxy=proxy or None, headers=h,
                        follow_redirects=True)


_NUM_WORD = {"k": 1e3, "mil": 1e3, "m": 1e6, "mi": 1e6, "milhão": 1e6,
             "milhões": 1e6, "b": 1e9, "bi": 1e9, "bilhão": 1e9}


def parse_count(txt) -> int:
    """'1.234.567' | '1,2 mi' | '12K' | '200+' → int."""
    if txt is None:
        return 0
    if isinstance(txt, (int, float)):
        return int(txt)
    t = (str(txt).lower().strip().replace("+", "").replace("visualizações", "")
         .replace("views", "").replace("buscas", "").strip())
    m = re.search(r"([\d.,]+)\s*(milhão|milhões|bilhão|mil|mi|bi|k|m|b)?", t)
    if not m:
        return 0
    num, mult = m.group(1), _NUM_WORD.get(m.group(2) or "", 1)
    if mult > 1:
        num = num.replace(".", "").replace(",", ".") if num.count(",") == 1 and num.count(".") > 1 else num
        num = num.replace(",", ".")
    else:
        num = num.replace(".", "").replace(",", "")
    try:
        return int(float(num) * mult)
    except ValueError:
        return 0


# ================================================================== REDDIT
# OAuth "client credentials" (app tipo script): não exige consentimento do usuário,
# mas autentica de verdade e eleva o rate limit de 10 req/min para 100 req/min.
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_API = "https://oauth.reddit.com"
REDDIT_PUBLIC = "https://www.reddit.com"


def reddit_configured() -> bool:
    cfg = _cfg()
    return bool(cfg.get("REDDIT_CLIENT_ID") and cfg.get("REDDIT_CLIENT_SECRET"))


def reddit_token(force: bool = False) -> dict:
    """Obtém (e cacheia) o token OAuth do Reddit. {} se não configurado/erro."""
    if not reddit_configured():
        return {}
    if not force and _reddit_cache["token"] and _reddit_cache["exp"] > time.time() + 30:
        return {"token": _reddit_cache["token"], "exp": _reddit_cache["exp"]}

    cfg = _cfg()
    ua = cfg.get("REDDIT_USER_AGENT") or UA_PADRAO
    try:
        with httpx.Client(timeout=TIMEOUT_PADRAO, headers={"User-Agent": ua}) as client:
            r = client.post(
                REDDIT_TOKEN_URL,
                auth=(cfg["REDDIT_CLIENT_ID"], cfg["REDDIT_CLIENT_SECRET"]),
                data={"grant_type": "client_credentials"},
            )
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:120]}"}
        d = r.json()
        token = d.get("access_token", "")
        exp = time.time() + int(d.get("expires_in") or 3600)
        _reddit_cache.update({"token": token, "exp": exp})
        return {"token": token, "exp": exp, "scope": d.get("scope", "")}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {str(exc)[:110]}"}


def _reddit_get(path: str, params: dict) -> list[dict]:
    """GET autenticado (OAuth) ou público (fallback), devolvendo children."""
    ua = _cfg().get("REDDIT_USER_AGENT") or UA_PADRAO
    tok = reddit_token()
    if tok.get("token"):
        with httpx.Client(timeout=TIMEOUT_PADRAO, headers={
                "User-Agent": ua, "Authorization": f"Bearer {tok['token']}"}) as client:
            r = client.get(REDDIT_API + path, params=params)
        if r.status_code >= 400:
            raise RuntimeError(f"Reddit OAuth HTTP {r.status_code}")
        return r.json().get("data", {}).get("children", [])

    # fallback sem credencial: JSON público (limite menor)
    with httpx.Client(timeout=TIMEOUT_PADRAO, headers={"User-Agent": ua}) as client:
        r = client.get(REDDIT_PUBLIC + path, params=params)
    if r.status_code >= 400:
        raise RuntimeError(f"Reddit público HTTP {r.status_code}")
    return r.json().get("data", {}).get("children", [])


def reddit_trending(subreddit: str = "", limit: int = 10, window: str = "week") -> list[dict]:
    """Top posts de um subreddit — OAuth quando configurado, público como fallback."""
    sub = (subreddit or _cfg().get("REDDIT_DEFAULT_SUB") or "Brasil").lstrip("r/")
    try:
        children = _reddit_get(f"/r/{sub}/top", {"t": window, "limit": min(limit, 50)})
    except Exception:
        return []
    out = []
    for child in children:
        d = child.get("data", {})
        if d.get("stickied"):
            continue
        out.append({
            "id": d.get("id"),
            "title": d.get("title", ""),
            "score": d.get("score", 0),
            "comments": d.get("num_comments", 0),
            "author": d.get("author", ""),
            "subreddit": d.get("subreddit", sub),
            "url": "https://www.reddit.com" + d.get("permalink", ""),
            "age_hours": max(1, int((time.time() - (d.get("created_utc") or 0)) / 3600)),
            "is_video": d.get("is_video", False),
        })
        if len(out) >= limit:
            break
    return out


def reddit_test() -> dict:
    cfg = _cfg()
    if not reddit_configured():
        posts = reddit_trending("", 2)
        return {"ok": bool(posts),
                "message": ("Sem credenciais: JSON público respondendo "
                            f"({len(posts)} posts). Configure Client ID/Secret para "
                            "OAuth e 10x mais requisições.")
                if posts else "JSON público não respondeu neste ambiente.",
                "modo": "publico"}
    tok = reddit_token(force=True)
    if tok.get("error"):
        return {"ok": False, "message": f"OAuth recusado — {tok['error']}", "modo": "oauth"}
    posts = reddit_trending("", 2)
    return {"ok": bool(posts),
            "message": (f"OAuth ok (escopo '{tok.get('scope') or 'n/d'}') — "
                        f"{len(posts)} posts lidos via oauth.reddit.com"),
            "modo": "oauth"}


# ================================================================== MERCADO LIVRE
MELI_API = "https://api.mercadolibre.com"
MELI_AUTH = "https://auth.mercadolivre.com.br/authorization"
MELI_TOKEN = "https://api.mercadolibre.com/oauth/token"


def meli_configured() -> bool:
    cfg = _cfg()
    return bool(cfg.get("MELI_CLIENT_ID") and cfg.get("MELI_CLIENT_SECRET"))


def meli_redirect_uri() -> str:
    return (_cfg().get("MELI_REDIRECT_URI")
            or "https://developers.mercadolivre.com.br/oauth/callback")


def meli_authorize_url(state: str = "mineraai") -> dict:
    """URL de consentimento (authorization_code). O usuário autoriza e volta com ?code."""
    if not meli_configured():
        return {"ok": False, "message": "Preencha Client ID e Secret do Mercado Livre."}
    cfg = _cfg()
    url = (f"{MELI_AUTH}?response_type=code&client_id={cfg['MELI_CLIENT_ID']}"
           f"&redirect_uri={meli_redirect_uri()}&state={state}")
    return {"ok": True, "url": url, "redirect_uri": meli_redirect_uri()}


def _meli_save_token(d: dict) -> dict:
    exp = int(time.time() + int(d.get("expires_in") or 21600))
    storage.settings_save({
        "MELI_ACCESS_TOKEN": d.get("access_token", ""),
        "MELI_REFRESH_TOKEN": d.get("refresh_token", ""),
        "MELI_TOKEN_EXPIRES_AT": str(exp),
    })
    return {"ok": bool(d.get("access_token")), "expires_at": exp,
            "scope": d.get("scope", "")}


def meli_exchange_code(code: str) -> dict:
    """Troca o ?code do redirect pelo par access/refresh token."""
    if not meli_configured():
        return {"ok": False, "message": "Configure Client ID/Secret primeiro."}
    cfg = _cfg()
    try:
        with httpx.Client(timeout=TIMEOUT_PADRAO) as client:
            r = client.post(MELI_TOKEN, data={
                "grant_type": "authorization_code",
                "client_id": cfg["MELI_CLIENT_ID"],
                "client_secret": cfg["MELI_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": meli_redirect_uri(),
            }, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            return {"ok": False, "message": f"HTTP {r.status_code}: {r.text[:140]}"}
        return {**_meli_save_token(r.json()), "message": "Autorização concluída"}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:110]}"}


def meli_refresh() -> dict:
    """Renova o access token (válido por 6h) usando o refresh token."""
    cfg = _cfg()
    refresh = cfg.get("MELI_REFRESH_TOKEN")
    if not (meli_configured() and refresh):
        return {"ok": False, "message": "Sem refresh token — refaça a autorização."}
    try:
        with httpx.Client(timeout=TIMEOUT_PADRAO) as client:
            r = client.post(MELI_TOKEN, data={
                "grant_type": "refresh_token",
                "client_id": cfg["MELI_CLIENT_ID"],
                "client_secret": cfg["MELI_CLIENT_SECRET"],
                "refresh_token": refresh,
            }, headers={"Accept": "application/json"})
        if r.status_code >= 400:
            return {"ok": False, "message": f"HTTP {r.status_code}: {r.text[:140]}"}
        return {**_meli_save_token(r.json()), "message": "Token renovado"}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {str(exc)[:110]}"}


def meli_access_token(auto_refresh: bool = True) -> str:
    """Token válido: renova sozinho quando faltam <5 min para expirar."""
    cfg = _cfg()
    token = cfg.get("MELI_ACCESS_TOKEN") or ""
    try:
        exp = int(cfg.get("MELI_TOKEN_EXPIRES_AT") or 0)
    except (TypeError, ValueError):
        exp = 0
    if token and exp and exp - time.time() > 300:
        return token
    if auto_refresh and cfg.get("MELI_REFRESH_TOKEN"):
        res = meli_refresh()
        if res.get("ok"):
            return _cfg().get("MELI_ACCESS_TOKEN", "")
    return token


def mercadolivre_search(q: str, limit: int = 12) -> list[dict]:
    """Busca produtos no Mercado Livre — com OAuth quando autorizado."""
    site = _cfg().get("MELI_SITE_ID") or "MLB"
    token = meli_access_token()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with _client("meli", headers=headers) as client:
            r = client.get(f"{MELI_API}/sites/{site}/search",
                           params={"q": q, "limit": min(limit, 50)})
        if r.status_code >= 400:
            return []
        data = r.json()
    except Exception:
        return []

    out = []
    for item in data.get("results", []):
        reviews = item.get("reviews") or {}
        out.append({
            "id": item.get("id"),
            "title": item.get("title", ""),
            "price": item.get("price", 0),
            "original_price": item.get("original_price"),
            "currency": item.get("currency_id", "BRL"),
            "sold_quantity": item.get("sold_quantity", 0),
            "reviews": reviews,
            "rating": reviews.get("rating_average", 0),
            "total_reviews": reviews.get("total", 0),
            "permalink": item.get("permalink", ""),
            "thumbnail": (item.get("thumbnail") or "").replace("http://", "https://"),
            "free_shipping": (item.get("shipping") or {}).get("free_shipping", False),
            "official_store": bool(item.get("official_store_id")),
            "category_id": item.get("category_id", ""),
            "source": "meli_oauth" if token else "meli_publico",
        })
    out.sort(key=lambda x: -(x.get("sold_quantity") or 0))
    return out


def mercadolivre_trend_signal(items: list[dict]) -> dict:
    """Resumo agregado do mercado para o módulo Produtos."""
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
        "autenticado": bool(_cfg().get("MELI_ACCESS_TOKEN")),
    }


def mercadolivre_test() -> dict:
    site = _cfg().get("MELI_SITE_ID") or "MLB"
    items = mercadolivre_search("garrafa térmica", 3)
    if not items:
        return {"ok": False, "message": "Busca não retornou resultados neste ambiente."}
    token = _cfg().get("MELI_ACCESS_TOKEN")
    return {"ok": True,
            "message": (f"{len(items)} produtos lidos (site {site}) — "
                        f"{'OAuth ativo' if token else 'modo público, sem token'}"),
            "exemplo": items[0]["title"][:60]}


# ================================================================== GOOGLE SUGGEST
def google_suggest(q: str, hl: str = "", gl: str = "") -> list[str]:
    """Autocomplete do Google — demanda de busca real, sem chave."""
    cfg = _cfg()
    params = {
        "client": "firefox",
        "q": q,
        "hl": hl or cfg.get("GOOGLE_SUGGEST_HL") or "pt-BR",
        "gl": gl or cfg.get("GOOGLE_SUGGEST_GL") or "BR",
    }
    try:
        with _client("suggest") as client:
            r = client.get("https://suggestqueries.google.com/complete/search", params=params)
        data = r.json()
    except Exception:
        return []
    if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list):
        return [s for s in data[1][:12] if isinstance(s, str)]
    return []


def google_cse_search(q: str, limit: int = 10) -> list[dict]:
    """Busca web completa via Custom Search JSON API (chave + CX próprios, opcional)."""
    cfg = _cfg()
    key, cx = cfg.get("GOOGLE_CSE_API_KEY"), cfg.get("GOOGLE_CSE_CX")
    if not (key and cx):
        return []
    try:
        with _client("google") as client:
            r = client.get("https://www.googleapis.com/customsearch/v1",
                           params={"key": key, "cx": cx, "q": q,
                                   "num": min(limit, 10),
                                   "hl": cfg.get("GOOGLE_SUGGEST_HL") or "pt-BR"})
        items = r.json().get("items", [])
    except Exception:
        return []
    return [{"title": i.get("title", ""), "link": i.get("link", ""),
             "snippet": i.get("snippet", "")} for i in items]


def google_suggest_test() -> dict:
    sugestoes = google_suggest("como ganhar dinheiro")
    cse = google_cse_search("tendências tiktok", 1)
    partes = [f"{len(sugestoes)} sugestões de autocomplete"]
    if _cfg().get("GOOGLE_CSE_API_KEY"):
        partes.append(f"CSE com {len(cse)} resultado(s)")
    return {"ok": bool(sugestoes) or bool(cse),
            "message": " · ".join(partes) + (" (sem chave necessária)" if not cse else "")}


# ================================================================== oEMBED
def oembed_lookup(url: str) -> dict:
    """Metadados oficiais de um link de vídeo (YouTube/TikTok) — sem chave."""
    url = (url or "").strip()
    if "tiktok.com" in url:
        api, platform = "https://www.tiktok.com/oembed", "tiktok"
    elif "youtube.com" in url or "youtu.be" in url:
        api, platform = "https://www.youtube.com/oembed", "youtube"
    else:
        return {}
    cfg = _cfg()
    try:
        timeout = float(cfg.get("OEMBED_TIMEOUT") or 20)
    except (TypeError, ValueError):
        timeout = 20.0
    try:
        with _client("oembed", timeout=timeout,
                     proxy=cfg.get("OEMBED_PROXY") or None) as client:
            r = client.get(api, params={"url": url, "format": "json"})
        d = r.json()
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


def oembed_test() -> dict:
    d = oembed_lookup("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    return {"ok": bool(d.get("title")),
            "message": (f"Metadados lidos: “{d.get('title', '')[:50]}”"
                        if d.get("title") else
                        "oEmbed não respondeu neste ambiente (sem chave necessária).")}


# ================================================================== GOOGLE TRENDS
def google_trends_br(limit: int = 12, geo: str = "", language: str = "") -> list[dict]:
    """Termos em alta agora — RSS público oficial, sem chave."""
    cfg = _cfg()
    params = {"geo": geo or cfg.get("TRENDS_GEO") or "BR"}
    if language or cfg.get("TRENDS_LANGUAGE"):
        params["hl"] = language or cfg.get("TRENDS_LANGUAGE")
    try:
        with _client("trends") as client:
            r = client.get("https://trends.google.com/trending/rss", params=params)
        raw = r.text
    except Exception:
        return []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    ns = "{https://trends.google.com/trending/rss}"
    out = []
    for item in root.iter("item"):
        traffic = item.findtext(f"{ns}approx_traffic", "0")
        news = item.find(f"{ns}news")
        source_title = ""
        if news is not None:
            first = news.find(f"{ns}newsItem")
            if first is not None:
                source_title = (first.findtext(f"{ns}source", "")
                                or first.findtext(f"{ns}title", ""))
        out.append({"term": item.findtext("title", "").strip(),
                    "traffic": parse_count(traffic),
                    "traffic_raw": traffic, "source": source_title})
        if len(out) >= limit:
            break
    return out


def trends_test() -> dict:
    terms = google_trends_br(3)
    return {"ok": bool(terms),
            "message": (f"{len(terms)} termos em alta: "
                        + ", ".join(t["term"] for t in terms[:3]))
            if terms else "Trends não respondeu neste ambiente (sem chave necessária)."}


# ================================================================== PEXELS
def pexels_broll(q: str, limit: int = 12) -> dict:
    """B-roll gratuito para a Fábrica — chave própria do Pexels."""
    key = _cfg().get("PEXELS_API_KEY", "")
    if not key:
        return {"ok": False, "items": [],
                "message": "Adicione a API key do Pexels (grátis) no card desta fonte."}
    try:
        with _client("pexels", headers={"Authorization": key}) as client:
            r = client.get("https://api.pexels.com/videos/search",
                           params={"query": q, "per_page": min(limit, 20)})
        data = r.json()
    except Exception as exc:
        return {"ok": False, "items": [],
                "message": f"Pexels indisponível: {type(exc).__name__}"}
    items = []
    for v in data.get("videos", []):
        files = v.get("video_files", [])
        best = max(files, key=lambda f: f.get("width", 0)) if files else {}
        items.append({
            "id": v.get("id"), "url": v.get("url", ""),
            "video_file": best.get("link", ""),
            "width": best.get("width"), "height": best.get("height"),
            "duration": v.get("duration"), "image": v.get("image", ""),
            "user": (v.get("user") or {}).get("name", ""),
        })
    return {"ok": True, "items": items}


def pexels_test() -> dict:
    res = pexels_broll("produto", 2)
    return {"ok": res["ok"],
            "message": res.get("message") or f"{len(res['items'])} clipes de B-roll"}


# ------------------------------------------------------------------ catálogo
FREE_SOURCES = [
    {"id": "reddit", "name": "Reddit", "auth": "oauth", "chave": "Client ID + Secret",
     "custo": "Grátis · OAuth client_credentials (100 req/min) · fallback JSON público"},
    {"id": "mercadolivre", "name": "Mercado Livre", "auth": "oauth", "chave": "Client ID + Secret",
     "custo": "Grátis · OAuth authorization_code + refresh automático"},
    {"id": "suggest", "name": "Google Suggest", "auth": "none", "chave": "não requer",
     "custo": "Grátis · região e idioma configuráveis · CSE opcional"},
    {"id": "oembed", "name": "oEmbed", "auth": "none", "chave": "não requer",
     "custo": "Grátis · timeout e proxy configuráveis"},
    {"id": "trends", "name": "Google Trends", "auth": "none", "chave": "não requer",
     "custo": "Grátis · RSS público por região"},
    {"id": "pexels", "name": "Pexels", "auth": "key", "chave": "API key (grátis)",
     "custo": "Grátis com chave · B-roll em vídeo"},
]
