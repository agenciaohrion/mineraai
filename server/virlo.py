"""Cliente da Virlo API — dados reais de short-form video (TikTok/Reels/Shorts).

A Virlo expõe três famílias de endpoints em `https://api.virlo.ai/v1`,
todas com `Authorization: Bearer virlo_tkn_...`:

  ORBIT      fila de busca por palavra-chave → vídeos, ads e outliers
             POST /orbit · GET /orbit · GET /orbit/{id} · GET /orbit/{id}/videos
             GET /orbit/{id}/ads · GET /orbit/{id}/creators/outliers
  COMET      monitoramento de nicho agendado (config + coletas recorrentes)
             POST/GET/PATCH/DELETE /comet · GET /comet/{id}/videos|ads|creators/outliers
  SATELLITE  ficha de criador por plataforma + username
             GET /satellite/creator/{platform}/{username}

Leitura (GET) é gratuita; criação de Orbit/Comet e lookup Satellite custam
US$ 0,50 por chamada. Por isso cada ação tem custo em créditos aqui também.

Como o Orbit leva de 5 a 10 minutos para processar (é fila, não busca síncrona),
o Radar usa o caminho rápido (`/videos`, `/trends`, `/hashtags`, leitura) e o
Orbit fica exposto como job assíncrono em `/api/virlo/orbit`.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import httpx

from . import storage

BASE_PADRAO = "https://api.virlo.ai/v1"
TIMEOUT = 40.0


class VirloError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


# ------------------------------------------------------------------ config
def _cfg() -> dict:
    return storage.settings_get()


def configured() -> bool:
    return bool(_cfg().get("VIRLO_API_KEY"))


def auto_use() -> bool:
    """Se o Radar deve consumir a Virlo automaticamente (fonte paga)."""
    return configured() and _cfg().get("VIRLO_AUTO_USE", "0") in ("1", "true", "yes")


def _base() -> str:
    return (_cfg().get("VIRLO_BASE_URL") or BASE_PADRAO).rstrip("/")


def status_resumo() -> dict:
    return {
        "oficial": "Virlo API (Orbit · Comet · Satellite)",
        "conectado": configured(),
        "custo": "US$ 0,50 por Orbit/Satellite/Comet · leitura gratuita",
        "auto_use": auto_use(),
    }


# ------------------------------------------------------------------ HTTP
async def _request(method: str, path: str, payload: Optional[dict] = None,
                   params: Optional[dict] = None, timeout: float = TIMEOUT) -> dict:
    if not configured():
        raise VirloError("Virlo não configurada: informe a API key (virlo_tkn_...)")
    url = _base() + path
    headers = {"Authorization": f"Bearer {_cfg().get('VIRLO_API_KEY', '')}",
               "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, headers=headers,
                                        json=payload, params=params)
    except httpx.TimeoutException:
        raise VirloError("Tempo esgotado consultando a Virlo")
    except httpx.HTTPError as exc:
        raise VirloError(f"Falha de rede com a Virlo: {type(exc).__name__}")

    if resp.status_code == 401:
        raise VirloError("API key da Virlo inválida (HTTP 401)", 401)
    if resp.status_code == 402:
        raise VirloError("Saldo insuficiente na Virlo (HTTP 402)", 402)
    if resp.status_code == 429:
        raise VirloError("Virlo limitou a requisição (HTTP 429)", 429)
    if resp.status_code >= 400:
        raise VirloError(f"Virlo respondeu HTTP {resp.status_code}",
                         resp.status_code, resp.text[:300])
    try:
        return resp.json()
    except ValueError:
        raise VirloError("Virlo devolveu resposta não-JSON")


# ------------------------------------------------------------------ conta
async def balance() -> dict:
    """Saldo/créditos da conta Virlo — usado no botão 'Testar conexão'."""
    data = await _request("GET", "/account/balance")
    return {"ok": True, "balance": data}


# ------------------------------------------------------------------ leitura (grátis)
async def quick_videos(limit: int = 20, platform: str = "", order_by: str = "views") -> list[dict]:
    """Vídeos virais do índice da Virlo (endpoint de leitura, sem custo)."""
    params: dict = {"limit": min(max(limit, 1), 100), "order_by": order_by}
    if platform and platform != "all":
        params["platform"] = platform
    data = await _request("GET", "/videos", params=params)
    items = data.get("data") or data.get("videos") or []
    return items if isinstance(items, list) else []


async def trending(limit: int = 20) -> list[dict]:
    data = await _request("GET", "/trends", params={"limit": limit})
    items = data.get("data") or data.get("trends") or []
    return items if isinstance(items, list) else []


async def hashtags(limit: int = 30) -> list[dict]:
    data = await _request("GET", "/hashtags", params={"limit": limit})
    items = data.get("data") or data.get("hashtags") or []
    return items if isinstance(items, list) else []


# ------------------------------------------------------------------ ORBIT (pago)
async def orbit_create(name: str, keywords: list[str], platforms: list[str],
                       min_views: int = 0, run_analysis: bool = True) -> dict:
    """Enfileira uma busca (US$ 0,50). Processamento leva 5–10 minutos."""
    payload = {
        "name": name[:120],
        "keywords": [k for k in keywords if k][:20],
        "platforms": [p for p in platforms if p] or ["tiktok", "instagram", "youtube"],
        "min_views": int(min_views),
        "run_analysis": bool(run_analysis),
    }
    data = await _request("POST", "/orbit", payload)
    orbit = data.get("data") or data
    return {"id": orbit.get("id"), "status": orbit.get("status", "queued"), "raw": orbit}


async def orbit_list() -> list[dict]:
    data = await _request("GET", "/orbit")
    items = data.get("data") or data.get("orbits") or []
    return items if isinstance(items, list) else []


async def orbit_get(orbit_id: str) -> dict:
    data = await _request("GET", f"/orbit/{orbit_id}")
    return data.get("data") or data


async def orbit_videos(orbit_id: str, limit: int = 25, order_by: str = "views",
                       sort: str = "desc", platform: str = "") -> list[dict]:
    params = {"limit": limit, "order_by": order_by, "sort": sort}
    if platform and platform != "all":
        params["platform"] = platform
    data = await _request("GET", f"/orbit/{orbit_id}/videos", params=params)
    items = data.get("data") or data.get("videos") or []
    return items if isinstance(items, list) else []


async def orbit_outliers(orbit_id: str, limit: int = 20) -> list[dict]:
    data = await _request("GET", f"/orbit/{orbit_id}/creators/outliers",
                          params={"limit": limit})
    items = data.get("data") or data.get("creators") or []
    return items if isinstance(items, list) else []


async def orbit_ads(orbit_id: str, limit: int = 20) -> list[dict]:
    data = await _request("GET", f"/orbit/{orbit_id}/ads", params={"limit": limit})
    items = data.get("data") or data.get("ads") or []
    return items if isinstance(items, list) else []


async def orbit_wait(orbit_id: str, intervalo: float = 30.0,
                     max_segundos: float = 900) -> dict:
    """Espera o Orbit sair de queued/processing (a doc fala em 5–10 min)."""
    inicio = time.time()
    while True:
        orbit = await orbit_get(orbit_id)
        estado = str(orbit.get("status", "")).lower()
        if estado in ("completed", "ready", "done", "failed", "error"):
            return orbit
        if time.time() - inicio > max_segundos:
            return {**orbit, "status": estado or "timeout",
                    "note": f"não concluído em {int(max_segundos)}s"}
        await asyncio.sleep(intervalo)


# ------------------------------------------------------------------ COMET (pago)
async def comet_create(name: str, keywords: list[str], platforms: list[str],
                       frequency: str = "daily", min_views: int = 0) -> dict:
    payload = {"name": name[:120], "keywords": keywords[:20],
               "platforms": platforms or ["tiktok", "instagram", "youtube"],
               "frequency": frequency, "min_views": int(min_views)}
    data = await _request("POST", "/comet", payload)
    return data.get("data") or data


async def comet_list(include_inactive: bool = False) -> list[dict]:
    params = {"include_inactive": "true"} if include_inactive else None
    data = await _request("GET", "/comet", params=params)
    items = data.get("data") or data.get("comets") or []
    return items if isinstance(items, list) else []


async def comet_videos(comet_id: str, limit: int = 25) -> list[dict]:
    data = await _request("GET", f"/comet/{comet_id}/videos", params={"limit": limit})
    items = data.get("data") or data.get("videos") or []
    return items if isinstance(items, list) else []


async def comet_delete(comet_id: str) -> dict:
    return await _request("DELETE", f"/comet/{comet_id}")


# ------------------------------------------------------------------ SATELLITE (pago)
async def satellite(platform: str, username: str) -> dict:
    """Ficha completa de um criador (US$ 0,50)."""
    user = username.lstrip("@")
    data = await _request("GET", f"/satellite/creator/{platform}/{user}")
    return data.get("data") or data


# ------------------------------------------------------------------ normalização
def to_unified_video(raw: dict, platform: str = "") -> dict:
    """Converte o JSON da Virlo no esquema unificado do MineraAI."""
    plat = (platform or raw.get("platform") or "tiktok").lower()
    if plat in ("youtube_shortss", "shorts"):
        plat = "youtube"
    stats = raw.get("stats") or raw.get("statistics") or {}
    author = raw.get("author") or raw.get("creator") or {}
    if isinstance(author, dict):
        handle = author.get("username") or author.get("handle") or ""
    else:
        handle = str(author)
    age = raw.get("age_hours")
    if age is None:
        posted = raw.get("posted_at") or raw.get("created_at") or raw.get("published_at")
        age = 24
        if posted:
            try:
                from datetime import datetime, timezone
                ts = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
                age = max(1, int((datetime.now(timezone.utc) - ts).total_seconds() / 3600))
            except Exception:
                age = 24
    return {
        "id": raw.get("id") or raw.get("video_id") or raw.get("shortcode") or "",
        "platform": plat,
        "title": raw.get("title") or raw.get("caption") or raw.get("description") or "",
        "author": handle.lstrip("@"),
        "handle": handle if handle.startswith("@") else f"@{handle.lstrip('@')}",
        "views": int(stats.get("views") or raw.get("views") or raw.get("play_count") or 0),
        "likes": int(stats.get("likes") or raw.get("likes") or raw.get("like_count") or 0),
        "comments": int(stats.get("comments") or raw.get("comments")
                        or raw.get("comment_count") or 0),
        "shares": int(stats.get("shares") or raw.get("shares") or raw.get("share_count") or 0),
        "age_hours": age,
        "hashtags": raw.get("hashtags") or [],
        "sound": raw.get("sound") or raw.get("music") or None,
        "url": raw.get("url") or raw.get("permalink") or "",
        "thumb": raw.get("thumbnail") or raw.get("cover") or None,
        "duration": raw.get("duration"),
        "source": "virlo",
    }


async def collect(keywords: str, platform: str = "all", limit: int = 20) -> dict:
    """Coleta 'rápida' para o Radar: vídeos + trends + hashtags (somente leitura).

    Não cria Orbit (pago) — usa os endpoints de leitura para trazer o índice
    mais recente da Virlo e filtra pelos termos no cliente.
    """
    videos, trends, tags, erros = [], [], [], []
    try:
        videos = await quick_videos(limit=max(limit * 3, 30), platform=platform)
    except VirloError as exc:
        erros.append(str(exc))
    try:
        trends = await trending(12)
    except VirloError:
        pass
    try:
        tags = await hashtags(20)
    except VirloError:
        pass

    termos = [t for t in (keywords or "").lower().split() if len(t) > 2]

    def combina(v: dict) -> bool:
        if not termos:
            return True
        texto = " ".join([str(v.get("title", "")), str(v.get("caption", "")),
                          " ".join(str(h) for h in (v.get("hashtags") or []))]).lower()
        return any(t in texto for t in termos)

    filtrados = [v for v in videos if combina(v)]
    # se o filtro por termo não achar nada, devolve o índice (melhor que vazio)
    usados = filtrados or videos
    return {
        "videos": [to_unified_video(v, platform) for v in usados][:limit],
        "trends": trends,
        "hashtags": tags,
        "erros": erros,
        "total_indice": len(videos),
        "filtrado_por_termo": bool(filtrados),
    }
