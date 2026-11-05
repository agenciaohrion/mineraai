"""Camada de pesquisa unificada — o "data layer" do MineraAI.

Todo consumidor (Radar, Outliers, Agentes, Mineração, API pública) chama estas
funções em vez de falar direto com as fontes. Ordem de confiança:

    API oficial  >  Virlo API  >  ingestão/mineração própria  >  demo

Sem Scrapling: a coleta proprietária saiu. No lugar dela existem três caminhos
legítimos — chaves oficiais (YouTube/TikTok/Instagram), a Virlo API (paga,
opcional) e a mineração própria (`mining.py`), que enfileira buscas nas fontes
acima e persiste o resultado.

Nada aqui calcula score na mão: tudo passa por `metrics.py`.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from . import (ai_engine, data as demo, free_sources, metrics, mining, pipeline,
               providers, runpod, schema, storage, virlo)

PLATFORMS = {"tiktok", "instagram", "youtube", "all"}
PERIODS = {"24h", "7d", "30d", "90d", "all"}
ALL_PLATFORMS = ["tiktok", "instagram", "youtube"]


# ------------------------------------------------------------------ status
def provider_status() -> dict:
    """Estado de cada integração — alimenta /api/status e a tela de conexões.

    Cada fonte é independente: tem o próprio par de campos, o próprio teste e o
    próprio custo. Nenhuma compartilha credencial com outra.
    """
    cfg = storage.settings_get()

    def tem(*keys: str) -> bool:
        return all(bool(cfg.get(k)) for k in keys)

    return {
        # ---------- plataformas oficiais
        "youtube": {
            "grupo": "plataformas",
            "oficial": "YouTube Data API v3",
            "conectado": tem("YOUTUBE_API_KEY"),
            "custo": "Gratuita · 10.000 unidades/dia (search = 100 unid.)",
        },
        "tiktok": {
            "grupo": "plataformas",
            "oficial": "TikTok Research API",
            "conectado": tem("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
            "custo": "Gratuita · requer aprovação acadêmica/institucional",
        },
        "instagram": {
            "grupo": "plataformas",
            "oficial": "Instagram Graph API",
            "conectado": tem("IG_ACCESS_TOKEN", "IG_USER_ID"),
            "custo": "Gratuita · conta Business/Creator + revisão de app",
        },
        # ---------- dados pagos
        "virlo": {**virlo.status_resumo(), "grupo": "dados"},
        # ---------- IA (duas integrações separadas)
        "openai": {
            "grupo": "ia",
            "oficial": "OpenAI",
            "conectado": tem("OPENAI_API_KEY"),
            "custo": "Pago por token · modelo e base URL configuráveis",
        },
        "gemini": {
            "grupo": "ia",
            "oficial": "Google Gemini",
            "conectado": tem("GEMINI_API_KEY"),
            "custo": "Tier gratuito generoso · chave e modelo próprios",
        },
        "ia": {   # visão agregada usada pelo cabeçalho do Estúdio
            "grupo": "ia",
            "oficial": "Motor IA ativo",
            "conectado": bool(ai_engine._llm_config()),
            "custo": "Interno grátis · OpenAI/Gemini opcionais",
        },
        # ---------- fontes gratuitas (uma entrada por fonte)
        "reddit": {
            "grupo": "fontes",
            "oficial": "Reddit (OAuth)",
            "conectado": free_sources.reddit_configured(),
            "custo": "Grátis · OAuth client_credentials · fallback JSON público",
        },
        "mercadolivre": {
            "grupo": "fontes",
            "oficial": "Mercado Livre (OAuth)",
            "conectado": bool(cfg.get("MELI_ACCESS_TOKEN")) or free_sources.meli_configured(),
            "custo": "Grátis · OAuth authorization_code + refresh automático",
        },
        "suggest": {
            "grupo": "fontes",
            "oficial": "Google Suggest",
            "conectado": True,
            "custo": "Grátis · não requer chave · região/idioma configuráveis",
        },
        "oembed": {
            "grupo": "fontes",
            "oficial": "oEmbed (YouTube/TikTok)",
            "conectado": True,
            "custo": "Grátis · não requer chave · timeout/proxy configuráveis",
        },
        "trends": {
            "grupo": "fontes",
            "oficial": "Google Trends",
            "conectado": True,
            "custo": "Grátis · não requer chave · RSS por região",
        },
        "pexels": {
            "grupo": "fontes",
            "oficial": "Pexels",
            "conectado": tem("PEXELS_API_KEY"),
            "custo": "Grátis com chave · B-roll em vídeo",
        },
        # ---------- produção
        "runpod": {**runpod.status_resumo(), "grupo": "producao"},
    }


def mode() -> dict:
    st = provider_status()
    live = [k for k, v in st.items() if v["conectado"]]
    return {"modo": "híbrido" if live else "demonstração",
            "providers": st, "live": live}


# ------------------------------------------------------------------ coleta
async def collect_official(q: str, plats: list[str], limit: int) -> tuple[list[dict], list[str]]:
    """APIs oficiais conectadas, em paralelo. Falha de uma não derruba as outras."""
    st = provider_status()
    jobs, nomes = [], []
    if "youtube" in plats and st["youtube"]["conectado"]:
        jobs.append(providers.youtube_search(q, max_results=limit, order="viewCount"))
        nomes.append("youtube")
    if "tiktok" in plats and st["tiktok"]["conectado"]:
        jobs.append(providers.tiktok_search(q, max_results=limit))
        nomes.append("tiktok")
    if "instagram" in plats and st["instagram"]["conectado"]:
        jobs.append(providers.instagram_hashtag_search(q, max_results=limit))
        nomes.append("instagram")
    if not jobs:
        return [], []

    resultados = await asyncio.gather(*jobs, return_exceptions=True)
    out, erros = [], []
    for nome, res in zip(nomes, resultados):
        if isinstance(res, list):
            out += res
        else:
            erros.append(f"{nome}: {type(res).__name__}")
    return out, erros


async def collect_virlo(q: str, platform: str, limit: int) -> tuple[list[dict], list[str]]:
    """Virlo (somente leitura) — usada no Radar só se VIRLO_AUTO_USE=1."""
    if not virlo.auto_use():
        return [], []
    try:
        res = await virlo.collect(q, platform, limit)
        return res["videos"], res.get("erros", [])
    except virlo.VirloError as exc:
        return [], [f"virlo: {exc}"]


# ------------------------------------------------------------------ busca
async def search_videos(q: str = "tendências", platform: str = "all",
                        period: str = "30d", min_views: int = 0,
                        limit: int = 14, include_demo: bool = True) -> dict:
    """Busca unificada: oficial → Virlo → mineração/ingestão → demo."""
    platform = platform if platform in PLATFORMS else "all"
    period = period if period in PERIODS else "30d"
    plats = ALL_PLATFORMS if platform == "all" else [platform]
    limit = max(1, min(int(limit), 60))

    demo_set = demo.search_aggregate(q, plats, period, min_views, limit)

    oficial, erros = await collect_official(q, plats, limit)
    do_virlo, erros_virlo = await collect_virlo(q, platform, limit)
    erros += erros_virlo

    mineirados = mining.mined_for_query(q)
    ingeridos = mining.ingested_for_query(q)

    raw = list(oficial) + list(do_virlo) + list(mineirados) + list(ingeridos)
    if include_demo:
        raw += demo_set["videos"]

    unificados = [v if v.get("uid") else schema.normalize_video(v, v.get("platform", "tiktok"))
                  for v in raw]
    videos = schema.dedupe(unificados, key_fields=("platform", "title", "handle"))

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
            "oficial": sum(1 for v in videos if v["source"] in ("oficial", "api")),
            "virlo": sum(1 for v in videos if v["source"] == "virlo"),
            "ingestao": sum(1 for v in videos if v["source"] in ("ingestao", "n8n", "mineracao")),
            "demo": sum(1 for v in videos if v["source"] == "demo"),
        },
        "errors": erros,
        "coleta_errors": erros,   # compatibilidade com a UI antiga
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
    campo = SORT_FIELDS.get(sort, "viral_score")
    return sorted(videos, key=lambda v: v.get(campo) or 0, reverse=(sort != "recent"))


# ------------------------------------------------------------------ outliers
async def find_outliers(q: str = "tendências", platform: str = "all",
                        period: str = "30d", limit: int = 12,
                        min_score: int = 30) -> dict:
    """Detecta vídeos furando a curva do criador/nicho.

    Corpus 3x maior que o pedido porque baseline precisa de contexto. Se a Virlo
    estiver conectada, `/creators/outliers` do Orbit daria o mesmo resultado já
    calculado por eles — aqui calculamos com `metrics.outlier_score` para
    funcionar com qualquer fonte.
    """
    limit = max(3, min(int(limit), 30))
    corpus = await search_videos(q, platform, period, 0, limit * 3)
    videos = corpus["videos"]

    outliers = [v for v in videos if v.get("outlier_score", 0) >= min_score]
    outliers.sort(key=lambda v: -(v.get("outlier_score", 0)))

    por_plataforma: dict[str, int] = {}
    for v in outliers:
        por_plataforma[v["platform"]] = por_plataforma.get(v["platform"], 0) + 1

    views = [int(v.get("views") or 0) for v in videos]
    mediana = metrics.corpus_baseline(videos)
    top = outliers[0] if outliers else None
    return {
        "query": q, "period": period, "platform": platform,
        "criterio": (f"views ÷ baseline do criador (mediana do nicho quando não há "
                     f"histórico) ≥ {min_score} pontos"),
        "corpus": {"videos": len(videos),
                   "mediana_views": int(mediana),
                   "fonte": corpus["source_breakdown"]},
        "outliers": outliers[:limit],
        "total": len(outliers),
        "por_plataforma": por_plataforma,
        "destaque": {
            "titulo": (top or {}).get("title"),
            "ratio": (top or {}).get("outlier_ratio"),
            "score": (top or {}).get("outlier_score"),
            "handle": (top or {}).get("handle"),
        } if top else None,
    }
