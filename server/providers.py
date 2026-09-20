"""Conectores OFICIAIS: YouTube Data API v3, TikTok Research API, Instagram Graph API.

Cada conector retorna dados normalizados no mesmo esquema usado pelo motor de
demonstração, permitindo alternância transparente entre dados reais e demo.
"""
from __future__ import annotations

import time
from typing import Optional

import httpx

from . import storage

TIMEOUT = 20.0


def _cfg() -> dict:
    return storage.settings_get()


# ============================================================= utilidades
def normalize_video(raw: dict, platform: str) -> dict:
    """Garante o esquema unificado de vídeo."""
    views = int(raw.get("views") or 0)
    likes = int(raw.get("likes") or 0)
    comments = int(raw.get("comments") or 0)
    shares = int(raw.get("shares") or 0)
    engagement = 0.0
    if views > 0:
        engagement = round(((likes + comments + shares) / views) * 100, 2)
    age_h = max(raw.get("age_hours") or 24, 1)
    velocity = views / age_h
    viral = min(100, int(
        0.50 * min(velocity / 12000, 1) * 100
        + 0.35 * min(engagement / 12, 1) * 100
        + 0.15 * max(0, 100 - min(age_h, 2400) / 24)
    ))
    return {
        "id": f"{platform}-{raw.get('id')}",
        "platform": platform,
        "title": raw.get("title", ""),
        "author": raw.get("author", ""),
        "handle": raw.get("handle", ""),
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "engagement": engagement,
        "viral_score": viral,
        "age_hours": age_h,
        "days_ago": round(age_h / 24, 1),
        "hashtags": raw.get("hashtags") or [],
        "sound": raw.get("sound"),
        "url": raw.get("url") or "",
        "thumb": raw.get("thumb"),
        "duration": raw.get("duration"),
        "source": raw.get("source", "api"),
    }


# ============================================================= YouTube
async def youtube_search(q: str, max_results: int = 24, order: str = "viewCount",
                         published_after: Optional[str] = None) -> list[dict]:
    """YouTube Data API v3 — oficial e gratuita (10.000 unidades/dia).

    search.list = 100 unidades · videos.list = 1 unidade.
    """
    key = _cfg().get("YOUTUBE_API_KEY", "")
    if not key:
        return []
    base = "https://www.googleapis.com/youtube/v3"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            params = {
                "part": "id",
                "q": q,
                "type": "video",
                "maxResults": min(max_results, 50),
                "order": order,
                "key": key,
            }
            if published_after:
                params["publishedAfter"] = published_after
            r = await client.get(f"{base}/search", params=params)
            r.raise_for_status()
            ids = [i["id"]["videoId"] for i in r.json().get("items", [])
                   if i.get("id", {}).get("videoId")]
            if not ids:
                return []
            r2 = await client.get(f"{base}/videos", params={
                "part": "snippet,statistics",
                "id": ",".join(ids),
                "key": key,
            })
            r2.raise_for_status()
            out = []
            for item in r2.json().get("items", []):
                stats = item.get("statistics", {})
                snippet = item.get("snippet", {})
                published = snippet.get("publishedAt", "")
                age_h = 24
                try:
                    ts = time.strptime(published[:19], "%Y-%m-%dT%H:%M:%S")
                    age_h = max(1, int((time.time() - time.mktime(ts)) / 3600))
                except Exception:
                    pass
                caption = snippet.get("title", "")
                tags = snippet.get("tags") or []
                hashtags = [t for t in tags if t.startswith("#")][:5]
                out.append(normalize_video({
                    "id": item["id"],
                    "title": caption,
                    "author": snippet.get("channelTitle", ""),
                    "handle": snippet.get("channelTitle", ""),
                    "views": stats.get("viewCount", 0),
                    "likes": stats.get("likeCount", 0),
                    "comments": stats.get("commentCount", 0),
                    "shares": 0,
                    "age_hours": age_h,
                    "hashtags": hashtags,
                    "url": f"https://www.youtube.com/watch?v={item['id']}",
                    "thumb": snippet.get("thumbnails", {}).get("medium", {}).get("url"),
                    "source": "oficial",
                }, "youtube"))
            return out
    except Exception:
        return []


async def youtube_key_test() -> dict:
    key = _cfg().get("YOUTUBE_API_KEY", "")
    if not key:
        return {"ok": False, "message": "Nenhuma chave configurada."}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get("https://www.googleapis.com/youtube/v3/videos",
                                 params={"part": "id", "chart": "mostPopular",
                                         "maxResults": 1, "key": key})
            if r.status_code == 200:
                return {"ok": True, "message": "Chave válida — YouTube conectado."}
            detail = r.json().get("error", {}).get("message", r.text[:120])
            return {"ok": False, "message": f"YouTube recusou a chave: {detail}"}
    except Exception as e:
        return {"ok": False, "message": f"Falha de rede: {e}"}


# ============================================================= TikTok Research API
async def _tiktok_token() -> Optional[str]:
    cfg = _cfg()
    ck, cs = cfg.get("TIKTOK_CLIENT_KEY", ""), cfg.get("TIKTOK_CLIENT_SECRET", "")
    if not ck or not cs:
        return None
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                "https://open.tiktokapis.com/v2/oauth/token/",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={"client_key": ck, "client_secret": cs,
                      "grant_type": "client_credentials"},
            )
            r.raise_for_status()
            return r.json().get("access_token")
    except Exception:
        return None


async def tiktok_search(q: str, max_results: int = 20) -> list[dict]:
    """TikTok Research API — oficial e gratuita (requer aprovação acadêmica)."""
    token = await _tiktok_token()
    if not token:
        return []
    fields = ("id,video_description,create_time,like_count,comment_count,"
              "share_count,view_count,username,hashtag_names,duration")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                "https://open.tiktokapis.com/v2/research/video/query/",
                headers={"Authorization": f"Bearer {token}",
                         "Content-Type": "application/json"},
                params={"fields": fields},
                json={
                    "query": {"and": [{"operation": "IN",
                                       "field_name": "keyword",
                                       "field_values": [q]}]},
                    "max_count": min(max_results, 100),
                    "start_date": time.strftime("%Y%m%d", time.gmtime(time.time() - 30 * 86400)),
                    "end_date": time.strftime("%Y%m%d", time.gmtime()),
                },
            )
            r.raise_for_status()
            out = []
            for v in r.json().get("data", {}).get("videos", []):
                created = int(v.get("create_time") or 0)
                age_h = max(1, int((time.time() - created) / 3600)) if created else 48
                desc = v.get("video_description", "") or "Vídeo TikTok"
                out.append(normalize_video({
                    "id": v.get("id"),
                    "title": desc[:110],
                    "author": v.get("username", ""),
                    "handle": v.get("username", ""),
                    "views": v.get("view_count", 0),
                    "likes": v.get("like_count", 0),
                    "comments": v.get("comment_count", 0),
                    "shares": v.get("share_count", 0),
                    "age_hours": age_h,
                    "hashtags": [f"#{h}" for h in (v.get("hashtag_names") or [])][:6],
                    "duration": v.get("duration"),
                    "url": f"https://www.tiktok.com/@{v.get('username')}/video/{v.get('id')}",
                    "source": "oficial",
                }, "tiktok"))
            return out
    except Exception:
        return []


# ============================================================= Instagram Graph API
async def instagram_hashtag_search(q: str, max_results: int = 20) -> list[dict]:
    """Instagram Graph API — oficial e gratuita (conta Business/Creator).

    Usa a busca de hashtags: ig_hashtag_search → {hashtag}/top_media.
    Limite oficial: 30 hashtags únicas por 7 dias por conta.
    """
    cfg = _cfg()
    token, user_id = cfg.get("IG_ACCESS_TOKEN", ""), cfg.get("IG_USER_ID", "")
    if not token or not user_id:
        return []
    tag = q.strip().lstrip("#").split()[0] if q.strip() else ""
    if not tag:
        return []
    base = "https://graph.facebook.com/v20.0"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get(f"{base}/ig_hashtag_search",
                                 params={"user_id": user_id, "q": tag,
                                         "access_token": token})
            r.raise_for_status()
            data = r.json().get("data", [])
            if not data:
                return []
            hid = data[0]["id"]
            r2 = await client.get(f"{base}/{hid}/top_media",
                                  params={"user_id": user_id,
                                          "fields": ("caption,like_count,comments_count,"
                                                     "media_url,permalink,username,"
                                                     "media_type,timestamp"),
                                          "access_token": token})
            r2.raise_for_status()
            out = []
            for m in r2.json().get("data", [])[:max_results]:
                ts = m.get("timestamp", "")
                age_h = 48
                try:
                    age_h = max(1, int(time.time() - time.mktime(
                        time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))))
                except Exception:
                    pass
                caption = (m.get("caption") or "Post do Instagram")[:110]
                out.append(normalize_video({
                    "id": m.get("id"),
                    "title": caption,
                    "author": m.get("username", ""),
                    "handle": m.get("username", ""),
                    "views": max(m.get("like_count", 0) * 12, 1),  # IG não expõe views aqui
                    "likes": m.get("like_count", 0),
                    "comments": m.get("comments_count", 0),
                    "shares": 0,
                    "age_hours": age_h,
                    "hashtags": [f"#{tag}"],
                    "url": m.get("permalink", ""),
                    "thumb": m.get("media_url"),
                    "source": "oficial",
                }, "instagram"))
            return out
    except Exception:
        return []


async def ig_token_test() -> dict:
    cfg = _cfg()
    token = cfg.get("IG_ACCESS_TOKEN", "")
    if not token:
        return {"ok": False, "message": "Nenhum token configurado."}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.get("https://graph.facebook.com/v20.0/me",
                                 params={"access_token": token})
            if r.status_code == 200:
                return {"ok": True, "message": "Token válido — Instagram conectado."}
            return {"ok": False, "message": "Token recusado pela Meta. Gere um token de longa duração."}
    except Exception as e:
        return {"ok": False, "message": f"Falha de rede: {e}"}
