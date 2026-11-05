"""Camada de pesquisa unificada — o "data layer" do MineraAI.

Todo consumidor (Radar, Outliers, Agents, API pública) chama estas funções em
vez de falar direto com as fontes. A ordem de confiança é sempre:

    API oficial  >  coleta pública (Scrapling)  >  n8n (mineração/ingestão)  >  demo

e o resultado sai normalizado (server/schema.py), deduplicado e com as métricas
calculadas (server/metrics.py). É isso que permite trocar a fonte sem tocar na
UI nem nos agentes.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from . import data as demo
from . import metrics, pipeline, providers, schema, scrapling_sources, storage

PLATFORMS = {"tiktok", "instagram", "youtube", "all"}
PERIODS = {"24h", "7d", "30d", "90d", "all"}
ALL_PLATFORMS = ["tiktok", "instagram", "youtube"]


# ------------------------------------------------------------------ status
def provider_status() -> dict:
    """Estado de cada fonte — alimenta /api/status e a tela de conexões."""
    cfg = storage.settings_get()
    return {
        "youtube": {
            "oficial": "YouTube Data API v3",
            "conectado": bool(cfg.get("YOUTUBE_API_KEY")),
            "custo": "Gratuita · 10.000 unidades/dia (search = 100 unid.)",
        },
        "tiktok": {
            "oficial": "TikTok Research API",
            "conectado": bool(cfg.get("TIKTOK_CLIENT_KEY") and cfg.get("TIKTOK_CLIENT_SECRET")),
            "custo": "Gratuita · requer aprovação acadêmica/institucional",
        },
        "instagram": {
            "oficial": "Instagram Graph API",
            "conectado": bool(cfg.get("IG_ACCESS_TOKEN") and cfg.get("IG_USER_ID")),
            "custo": "Gratuita · requer conta Business/Creator + revisão de app",
        },
        "ia": {
            "oficial": "Groq / Gemini / OpenAI (opcional)",
            "conectado": bool(cfg.get("GROQ_API_KEY") or cfg.get("GEMINI_API_KEY")
                              or cfg.get("OPENAI_API_KEY")),
            "custo": "Motor interno grátis incluso · LLMs externos opcionais",
        },
        "coleta": {
            "oficial": "Scrapling — coleta pública em tempo real",
            "conectado": scrapling_sources.coleta_enabled(),
            "custo": "Open source · sem chave · dados públicos reais (1 req/busca)",
        },
        "fontes_gratuitas": {
            "oficial": "Reddit · Mercado Livre · Google Suggest · oEmbed · Trends · Pexels",
            "conectado": True,
            "custo": "Gratuitas e sem chave (Pexels usa chave grátis opcional p/ B-roll)",
        },
        "automacao": {
            "oficial": "n8n + RunPod/ComfyUI (Fábrica de Vídeos)",
            "conectado": bool(cfg.get("N8N_WEBHOOK_URL")),
            "custo": "n8n self-host grátis · RunPod serverless paga por segundo de GPU",
        },
    }


def mode() -> dict:
    st = provider_status()
    live = [k for k, v in st.items() if v["conectado"]]
    return {"modo": "híbrido" if live else "demonstração",
            "providers": st, "live": live}


# ------------------------------------------------------------------ coleta
async def collect_official(q: str, plats: list[str], limit: int) -> list[dict]:
    """APIs oficiais conectadas, em paralelo. Falha de uma nunca derruba as outras."""
    st = provider_status()
    jobs = []
    if "youtube" in plats and st["youtube"]["conectado"]:
        jobs.append(providers.youtube_search(q, max_results=limit, order="viewCount"))
    if "tiktok" in plats and st["tiktok"]["conectado"]:
        jobs.append(providers.tiktok_search(q, max_results=limit))
    if "instagram" in plats and st["instagram"]["conectado"]:
        jobs.append(providers.instagram_hashtag_search(q, max_results=limit))
    if not jobs:
        return []
    results = await asyncio.gather(*jobs, return_exceptions=True)
    out = []
    for res in results:
        if isinstance(res, list):
            out += res
    return out


async def collect_public(q: str, plats: list[str], limit: int,
                         timeout: float = 50) -> tuple[list[dict], list[str]]:
    """Coleta pública via Scrapling (sem chave), com teto de tempo."""
    if not scrapling_sources.coleta_enabled():
        return [], []
    try:
        res = await asyncio.wait_for(
            asyncio.to_thread(scrapling_sources.collect, q, plats, limit),
            timeout=timeout)
        return res.get("videos", []), res.get("errors", [])
    except Exception as exc:
        return [], [f"timeout na coleta ({type(exc).__name__})"]


# ------------------------------------------------------------------ busca
async def search_videos(q: str = "tendências", platform: str = "all",
                        period: str = "30d", min_views: int = 0,
                        limit: int = 14, include_demo: bool = True) -> dict:
    """Busca unificada: oficial → coleta → n8n → demo, deduplicada e pontuada."""
    platform = platform if platform in PLATFORMS else "all"
    period = period if period in PERIODS else "30d"
    plats = ALL_PLATFORMS if platform == "all" else [platform]
    limit = max(1, min(int(limit), 60))

    demo_set = demo.search_aggregate(q, plats, period, min_views, limit)

    official = await collect_official(q, plats, limit)
    coletados, coleta_errors = await collect_public(q, plats, limit)
    automatizados = pipeline.mined_for_query(q) + pipeline.ingested_for_query(q)

    raw = list(official) + list(coletados) + list(automatizados)
    if include_demo:
        raw += demo_set["videos"]

    # normaliza o que ainda não veio no esquema unificado (idempotente)
    unified = [v if v.get("uid") else schema.normalize_video(v, v.get("platform", "tiktok"))
               for v in raw]
    videos = schema.dedupe(unified, key_fields=("platform", "title", "handle"))

    if min_views:
        videos = [v for v in videos if int(v.get("views") or 0) >= min_views]

    videos = metrics.enrich_videos(videos)
    return {
        "query": q, "period": period, "platform": platform,
        "videos": videos,
        "facets": {
            "top_hashtags": demo_set["top_hashtags"],
            "top_sounds": demo_set["top_sounds"],
            "top_creators": demo_set["top_creators"],
        },
        "source_breakdown": {
            "oficial": sum(1 for v in videos if v["source"] == "oficial"),
            "coleta": sum(1 for v in videos if v["source"] == "coleta"),
            "n8n": sum(1 for v in videos if v["source"] == "n8n"),
            "demo": sum(1 for v in videos if v["source"] == "demo"),
        },
        "coleta_errors": coleta_errors,
    }


SORT_FIELDS = {
    "viral_score": "viral_score",
    "views": "views",
    "likes": "likes",
    "engagement": "engagement",
    "outlier_score": "outlier_score",
    "recent": "age_hours",
}


def sort_videos(videos: list[dict], sort: str) -> list[dict]:
    field = SORT_FIELDS.get(sort, "viral_score")
    return sorted(videos, key=lambda v: v.get(field) or 0, reverse=(sort != "recent"))


# ------------------------------------------------------------------ outliers
async def find_outliers(q: str = "tendências", platform: str = "all",
                        period: str = "30d", limit: int = 12,
                        min_score: int = 30) -> dict:
    """Detecta vídeos furando a curva do criador/nicho — o sinal central do Radar.

    Estratégia: buscamos um corpus maior que o pedido (3x) porque o baseline
    precisa de contexto; enriquecemos com outlier_score e devolvemos apenas os
    que passam do corte, ordenados pelo score.
    """
    limit = max(3, min(int(limit), 30))
    corpus = await search_videos(q, platform, period, 0, limit * 3)
    videos = corpus["videos"]

    outliers = [v for v in videos if v.get("outlier_score", 0) >= min_score]
    outliers.sort(key=lambda v: -(v.get("outlier_score", 0)))

    by_platform: dict[str, int] = {}
    for v in outliers:
        by_platform[v["platform"]] = by_platform.get(v["platform"], 0) + 1

    views = [int(v.get("views") or 0) for v in videos]
    corpus_median = metrics.corpus_baseline(videos)
    top = outliers[0] if outliers else None
    return {
        "query": q, "period": period, "platform": platform,
        "criterio": (f"views ÷ baseline do criador (mediana do nicho quando não há "
                     f"histórico) ≥ {min_score} pontos"),
        "corpus": {"videos": len(videos),
                   "mediana_views": int(corpus_median),
                   "p90_views": int(metrics.percentile_rank(views, sorted(views)[int(len(views) * 0.9)])) if views else 0,
                   "fonte": corpus["source_breakdown"]},
        "outliers": outliers[:limit],
        "total": len(outliers),
        "por_plataforma": by_platform,
        "destaque": {
            "titulo": (top or {}).get("title"),
            "ratio": (top or {}).get("outlier_ratio"),
            "score": (top or {}).get("outlier_score"),
            "handle": (top or {}).get("handle"),
        } if top else None,
    }
