"""MineraAI — Ecossistema completo de descoberta viral, inteligência de produtos
e criação de conteúdo com IA.

Funcionalidades inspiradas em ferramentas de pesquisa viral, analytics de
TikTok Shop e laboratórios de criação para canais dark — reconstruídas do zero
com design próprio e arquitetura de dados plugável (APIs oficiais + demo).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (ai_engine, curation, data as demo, free_sources, pipeline, providers,
               scrapling_sources, storage)

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="MineraAI", version="1.0.0",
              description="Ecossistema de descoberta viral + criação com IA")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

PLATFORMS = {"tiktok", "instagram", "youtube", "all"}


# ------------------------------------------------------------ status das APIs
def provider_status() -> dict:
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
            "oficial": "n8n + RunPod/ComfyUI (Fábrica ComfyUI)",
            "conectado": bool(cfg.get("N8N_WEBHOOK_URL")),
            "custo": "n8n self-host grátis · RunPod serverless paga por segundo de GPU",
        },
    }


@app.get("/api/status")
async def status():
    st = provider_status()
    live = [k for k, v in st.items() if v["conectado"]]
    return {"modo": "híbrido" if live else "demonstração",
            "providers": st, "live": live}


# ------------------------------------------------------------ radar viral
@app.get("/api/search")
async def search(q: str = "tendências", platform: str = "all", period: str = "30d",
                 sort: str = "viral_score", min_views: int = 0, limit: int = 14):
    platform = platform if platform in PLATFORMS else "all"
    period = period if period in {"24h", "7d", "30d", "90d", "all"} else "30d"
    plats = ["tiktok", "instagram", "youtube"] if platform == "all" else [platform]
    limit = max(3, min(limit, 30))

    demo_set = demo.search_aggregate(q, plats, period, min_views, limit)
    st = provider_status()
    official, coletados = [], []

    # 1) APIs oficiais (quando conectadas) — em paralelo
    jobs = []
    if "youtube" in plats and st["youtube"]["conectado"]:
        jobs.append(providers.youtube_search(q, max_results=limit, order="viewCount"))
    if "tiktok" in plats and st["tiktok"]["conectado"]:
        jobs.append(providers.tiktok_search(q, max_results=limit))
    if "instagram" in plats and st["instagram"]["conectado"]:
        jobs.append(providers.instagram_hashtag_search(q, max_results=limit))
    if jobs:
        results = await asyncio.gather(*jobs, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                official += res

    # 2) Coleta pública via Scrapling (sem chave) — em thread, com teto de tempo
    coleta_errors = []
    if st["coleta"]["conectado"]:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(scrapling_sources.collect, q, plats, limit),
                timeout=50)
            coletados = res.get("videos", [])
            coleta_errors = res.get("errors", [])
        except Exception:
            coleta_errors = ["timeout na coleta"]

    # 3) Mineração persistida (n8n agendado) + ingestão n8n
    automatizados = pipeline.mined_for_query(q) + pipeline.ingested_for_query(q)

    # 4) Mescla: oficial > coleta/n8n > demo (dedupe por título+autor)
    videos, seen = [], set()
    for v in official + coletados + automatizados + demo_set["videos"]:
        key = (v["platform"], (v["title"] or "").lower()[:60],
               (v["author"] or "").lower())
        if key in seen:
            continue
        seen.add(key)
        videos.append(v)
    if min_views:
        videos = [v for v in videos if v["views"] >= min_views]

    sort_key = {"viral_score": "viral_score", "views": "views", "likes": "likes",
                "engagement": "engagement", "recent": "age_hours"}.get(sort, "viral_score")
    videos.sort(key=lambda v: v[sort_key], reverse=(sort != "recent"))

    return {
        "query": q, "period": period, "sort": sort,
        "source_breakdown": {
            "oficial": sum(1 for v in videos if v["source"] == "oficial"),
            "coleta": sum(1 for v in videos if v["source"] == "coleta"),
            "n8n": sum(1 for v in videos if v["source"] == "n8n"),
            "demo": sum(1 for v in videos if v["source"] == "demo"),
        },
        "coleta_errors": coleta_errors,
        "videos": videos[:limit * len(plats)],
        "top_hashtags": demo_set["top_hashtags"],
        "top_sounds": demo_set["top_sounds"],
        "top_creators": demo_set["top_creators"],
        "total": len(videos),
    }


# ------------------------------------------------------------ produtos
@app.get("/api/products")
async def products(q: Optional[str] = None, category: str = "", sort: str = "gmv",
                   limit: int = 18):
    items = demo.demo_products(q, category, sort, min(limit, 40))
    total_gmv = sum(p["gmv"] for p in items)
    out = {"products": items, "total_gmv": total_gmv,
           "categories": list(demo.NICHOS.keys()),
           "note": "Estimativas baseadas em modelo público de GMV (views × conversão × ticket).",
           "mercadolivre": [], "ml_signal": {}}
    # Mercado Livre: dados REAIS de mercado BR — API pública oficial, sem chave
    if q and scrapling_sources.coleta_enabled():
        try:
            ml = await asyncio.wait_for(
                asyncio.to_thread(free_sources.mercadolivre_search, q, 12), timeout=25)
            out["mercadolivre"] = ml
            out["ml_signal"] = free_sources.mercadolivre_trend_signal(ml)
        except Exception:
            out["mercadolivre"] = []
    return out


# ------------------------------------------------------------ ideias de pauta
@app.get("/api/ideas")
async def ideas(q: str = "renda extra", subreddit: str = "Brasil"):
    """Pauta viral: top do Reddit + autocomplete do Google (grátis, sem chave)."""
    result = {"reddit": [], "sugestoes": [], "subreddit": subreddit}
    if scrapling_sources.coleta_enabled():
        try:
            result["reddit"] = await asyncio.wait_for(
                asyncio.to_thread(free_sources.reddit_trending, subreddit, 8),
                timeout=25)
        except Exception:
            pass
        try:
            result["sugestoes"] = await asyncio.wait_for(
                asyncio.to_thread(free_sources.google_suggest, q), timeout=15)
        except Exception:
            pass
    return result


@app.get("/api/products/{product_id}")
async def product_detail(product_id: str):
    return demo.demo_product_detail(product_id)


# ------------------------------------------------------------ criadores
@app.get("/api/creators")
async def creators(q: Optional[str] = None, platform: str = "all", limit: int = 14):
    return {"creators": demo.demo_creators(q, platform, min(limit, 30))}


# ------------------------------------------------------------ vídeos & lives
@app.get("/api/lives")
async def lives(limit: int = 12):
    ls = demo.demo_lives(min(limit, 30))
    return {"lives": ls,
            "gmv_total": sum(l["gmv"] for l in ls),
            "ao_vivo_agora": sum(1 for l in ls if l["live_now"])}


# ------------------------------------------------------------ tendências reais
@app.get("/api/trends")
async def trends(limit: int = 12):
    """Termos em alta agora no Brasil — Google Trends (RSS público, grátis)."""
    if not scrapling_sources.coleta_enabled():
        return {"terms": [], "fonte": "desativado"}
    try:
        terms = await asyncio.wait_for(
            asyncio.to_thread(scrapling_sources.google_trends_br, min(limit, 20)),
            timeout=30)
        return {"terms": terms, "fonte": "Google Trends BR (tempo real)"}
    except Exception as e:
        return {"terms": [], "fonte": "indisponível",
                "erro": f"{type(e).__name__}: {str(e)[:90]}"}


# ------------------------------------------------------------ radar de nichos
@app.get("/api/niches")
async def niches(limit: int = 14):
    return {"niches": demo.demo_niches(min(limit, 24)),
            "criterio": "Canais com poucos vídeos e muitas views = micro-nicho viral antes da onda."}


# ------------------------------------------------------------ estúdio IA
class HooksIn(BaseModel):
    product: str = Field(..., min_length=2, max_length=120)
    niche: str = ""
    audience: str = ""
    tone: str = "direto"
    count: int = 10


class ScriptIn(BaseModel):
    product: str = Field(..., min_length=2, max_length=120)
    niche: str = ""
    duration: int = 30
    format: str = "ugc"


class CaptionIn(BaseModel):
    product: str = Field(..., min_length=2, max_length=120)
    platform: str = "tiktok"
    benefit: str = ""


class TitlesIn(BaseModel):
    theme: str = Field(..., min_length=2, max_length=120)


class AnalyzeIn(BaseModel):
    subject: str = Field(..., min_length=2, max_length=400)


class NarrationIn(BaseModel):
    text: str = Field(..., min_length=4, max_length=4000)
    tone: str = "suspense"


@app.post("/api/ai/hooks")
async def ai_hooks(body: HooksIn):
    return await ai_engine.generate_hooks(body.product, body.niche, body.audience,
                                          body.tone, max(3, min(body.count, 14)))


@app.post("/api/ai/script")
async def ai_script(body: ScriptIn):
    return await ai_engine.generate_script(body.product, body.niche,
                                           max(10, min(body.duration, 180)), body.format)


@app.post("/api/ai/caption")
async def ai_caption(body: CaptionIn):
    plat = body.platform if body.platform in {"tiktok", "instagram", "youtube"} else "tiktok"
    return await ai_engine.generate_caption(body.product, plat, body.benefit)


@app.post("/api/ai/titles")
async def ai_titles(body: TitlesIn):
    return await ai_engine.generate_titles(body.theme)


@app.post("/api/ai/analyze")
async def ai_analyze(body: AnalyzeIn):
    analise = await ai_engine.analyze_video(body.subject)
    # Enriquecimento com metadados REAIS do vídeo via oEmbed oficial (grátis)
    if free_sources.looks_like_video_url(body.subject):
        try:
            real = await asyncio.wait_for(
                asyncio.to_thread(free_sources.oembed_lookup, body.subject),
                timeout=20)
            if real:
                analise["video_real"] = real
        except Exception:
            pass
    return analise


@app.post("/api/ai/narration")
async def ai_narration(body: NarrationIn):
    tone = body.tone if body.tone in {"suspense", "energetico", "documental",
                                      "jornalistico"} else "suspense"
    return ai_engine.prepare_narration(body.text, tone)


# ------------------------------------------------------------ Fábrica (n8n + RunPod/ComfyUI) — imagem, vídeo ou misto
class JobIn(BaseModel):
    product: str = Field(..., min_length=2, max_length=160)
    prompt: str = Field("", max_length=4000)  # prompt principal (pode ser roteiro completo)
    style: str = "dark"  # dark, cinematic, ugc, produto, anime
    duration: int = 6
    tipo: str = "video"  # imagem | video | misto
    roteiro: dict = {}  # {hook, cenas: [{nome, descricao, prompt, duracao}], narracao}
    prompts: list = []  # prompts extras para imagens
    extra: dict = {}


class JobResultIn(BaseModel):
    status: str = "pronto"          # pronto | erro | processando
    video_url: str = ""
    images: list = []               # [{url, prompt, cena, thumb}]
    thumb_url: str = ""
    cost_usd: Optional[float] = None
    error: str = ""


class IngestIn(BaseModel):
    videos: list = []
    query: str = ""


class MiningRunIn(BaseModel):
    keywords: list = []


@app.post("/api/fabrica/jobs")
async def fabrica_create(body: JobIn):
    """Cria job de imagem/vídeo/misto e dispara o webhook do n8n (que orquestra o ComfyUI no RunPod)."""
    tipo = body.tipo if body.tipo in ("imagem", "video", "misto") else "video"
    job = pipeline.job_create(body.product, body.prompt, body.style,
                              max(2, min(body.duration, 60)),
                              extra=body.extra, tipo=tipo,
                              roteiro=body.roteiro, prompts=body.prompts)
    updated = await pipeline.dispatch_to_n8n(job)
    return {"job": updated}


@app.get("/api/fabrica/jobs")
async def fabrica_list():
    jobs = pipeline.jobs_list()
    cfg = storage.settings_get()
    return {"jobs": jobs,
            "webhook_configurado": bool(cfg.get("N8N_WEBHOOK_URL"))}


@app.post("/api/fabrica/jobs/{job_id}/result")
async def fabrica_result(job_id: str, body: JobResultIn,
                         x_pipeline_token: Optional[str] = Header(None)):
    """Callback do n8n com imagem/vídeo/misto pronto (protegido por token opcional)."""
    if not pipeline.check_token(x_pipeline_token or ""):
        raise HTTPException(401, "Token inválido")
    status = body.status if body.status in {"pronto", "erro", "processando"} else "pronto"
    if body.video_url or body.images:
        status = "pronto"
    job = pipeline.job_update(job_id, {
        "status": status,
        "video_url": body.video_url or None,
        "images": body.images or [],
        "thumb_url": body.thumb_url or None,
        "cost_usd": body.cost_usd,
        "error": body.error or None,
    })
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return {"ok": True, "job": job}


@app.delete("/api/fabrica/jobs/{job_id}")
async def fabrica_delete(job_id: str):
    if not pipeline.job_delete(job_id):
        raise HTTPException(404, "Job não encontrado")
    return {"ok": True}


@app.get("/api/fabrica/broll")
async def fabrica_broll(q: str = "produto"):
    """B-roll gratuito (Pexels) para enriquecer os vídeos da Fábrica."""
    return await asyncio.to_thread(free_sources.pexels_broll, q, 10)


# ------------------------------------------------------------ mineração & ingestão (n8n)
@app.post("/api/mining/run")
async def mining_run(body: MiningRunIn):
    """Disparado pelo n8n (ou manualmente): minera palavras-chave com Scrapling
    e persiste os resultados, que entram no Radar Viral automaticamente."""
    kws = [k.strip() for k in (body.keywords or []) if k.strip()][:6]
    if not kws:
        raise HTTPException(400, "Informe ao menos uma palavra-chave")
    if not scrapling_sources.coleta_enabled():
        raise HTTPException(400, "Coleta Scrapling desativada")
    results = []
    for kw in kws:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(scrapling_sources.collect, kw,
                                  ["youtube", "tiktok", "instagram"], 8),
                timeout=70)
            results.append(pipeline.mined_save(kw, res["videos"], res["errors"]))
        except Exception as e:
            results.append(pipeline.mined_save(kw, [], [f"timeout: {type(e).__name__}"]))
    return {"ok": True, "results": results}


@app.get("/api/mining/summary")
async def mining_summary():
    return {"cache": pipeline.mined_summary()}


@app.post("/api/ingest/videos")
async def ingest_videos(body: IngestIn,
                        x_pipeline_token: Optional[str] = Header(None)):
    """Qualquer workflow n8n pode empurrar vídeos minerados de outras fontes."""
    if not pipeline.check_token(x_pipeline_token or ""):
        raise HTTPException(401, "Token inválido")
    n = pipeline.ingest_videos(body.videos or [], body.query or "n8n")
    return {"ok": True, "importados": n}


# ------------------------------------------------------------ curadoria
class CurationDecideIn(BaseModel):
    decision: str = Field(..., min_length=2)
    notas: str = ""
    por: str = "humano"

class CurationBulkDecideIn(BaseModel):
    ids: list[str] = []
    decision: str = Field(..., min_length=2)
    notas: str = ""

class CurationEnrichIn(BaseModel):
    hooks: list = []
    analise: dict = {}
    tags_sugeridas: list = []
    titulo_sugerido: str = ""
    notas_ia: str = ""
    extra: dict = {}

class CurationImportIn(BaseModel):
    videos: list = []
    query: str = ""
    source: str = "manual"

class CurationRulesIn(BaseModel):
    rules: dict = {}

class CurationAutoIn(BaseModel):
    query: str = Field(..., min_length=2)
    platform: str = "all"
    limit: int = 12


@app.get("/api/curation/queue")
async def curation_queue(status: str = "", platform: str = "all", min_score: int = 0,
                         q: str = "", limit: int = 50, sort: str = "score"):
    items = curation.curation_list(status=status, platform=platform,
                                   min_score=min_score, q=q, limit=limit, sort=sort)
    stats = curation.curation_stats()
    return {"items": items, "stats": stats, "rules": curation.rules_get()}


@app.get("/api/curation/outliers")
async def curation_outliers_endpoint(min_score: int = 75, limit: int = 20):
    items = curation.curation_outliers(min_score=min_score, limit=limit)
    return {"outliers": items, "count": len(items), "min_score": min_score}


@app.get("/api/curation/stats")
async def curation_stats_endpoint():
    return curation.curation_stats()


@app.get("/api/curation/rules")
async def curation_rules_get():
    return {"rules": curation.rules_get()}


@app.post("/api/curation/rules")
async def curation_rules_save(body: CurationRulesIn):
    saved = curation.rules_save(body.rules or {})
    return {"ok": True, "rules": saved}


@app.post("/api/curation/items")
async def curation_import(body: CurationImportIn,
                          x_pipeline_token: Optional[str] = Header(None)):
    """Importa vídeos para curadoria — usado pelo frontend, n8n e API."""
    # se token configurado, exige para source n8n
    if body.source in ("n8n", "auto") and not pipeline.check_token(x_pipeline_token or ""):
        # permite se token não configurado
        if storage.settings_get().get("N8N_TOKEN"):
            raise HTTPException(401, "Token inválido")
    if not body.videos:
        raise HTTPException(400, "Nenhum vídeo enviado")
    # normaliza
    normalized = []
    for v in body.videos:
        try:
            nv = providers.normalize_video(v, v.get("platform", "tiktok"))
            normalized.append(nv)
        except Exception:
            continue
    result = curation.curation_bulk_create(normalized, query_origem=body.query, source=body.source)
    return {"ok": True, **result}


@app.post("/api/curation/auto-curate")
async def curation_auto_curate(body: CurationAutoIn):
    """Busca no Radar e já joga para curadoria com regras aplicadas."""
    # reutiliza a lógica de search (sem duplicar código pesado, faz chamada interna)
    # aqui faz busca rápida via pipeline + demo
    plats = ["tiktok", "instagram", "youtube"] if body.platform == "all" else [body.platform]
    limit = max(3, min(body.limit, 20))

    # tenta coleta real + demo (simplificado para não depender de gather)
    videos = []
    st = provider_status()
    if st["coleta"]["conectado"]:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(scrapling_sources.collect, body.query, plats, limit),
                timeout=45)
            videos += res.get("videos", [])
        except Exception:
            pass
    # completa com demo
    demo_set = demo.search_aggregate(body.query, plats, "30d", 0, limit)
    # dedupe
    seen = set()
    merged = []
    for v in videos + demo_set["videos"]:
        key = (v["platform"], v["id"])
        if key in seen:
            continue
        seen.add(key)
        merged.append(v)

    result = curation.curation_bulk_create(merged[:limit * len(plats)],
                                           query_origem=body.query, source="auto")
    return {"ok": True, "query": body.query, **result}


@app.post("/api/curation/items/{item_id}/decision")
async def curation_decide_endpoint(item_id: str, body: CurationDecideIn):
    if body.decision not in curation.VALID_DECISIONS:
        raise HTTPException(400, f"Decisão inválida. Use: {', '.join(curation.STATUSES)}")
    updated = curation.curation_decide(item_id, body.decision, body.notas, body.por)
    if not updated:
        raise HTTPException(404, "Item não encontrado")
    # se aprovado e tem vídeo, opcionalmente já salva na biblioteca
    if body.decision == "aprovado":
        try:
            v = updated.get("video", {})
            storage.library_add({"kind": "video", "ref": v.get("id"),
                                 "title": v.get("title"),
                                 "payload": {"curadoria_id": item_id, **v}})
        except Exception:
            pass
    return {"ok": True, "item": updated}


@app.post("/api/curation/bulk-decision")
async def curation_bulk_decide_endpoint(body: CurationBulkDecideIn):
    if not body.ids:
        raise HTTPException(400, "Nenhum ID enviado")
    if body.decision not in curation.VALID_DECISIONS:
        raise HTTPException(400, "Decisão inválida")
    res = curation.curation_bulk_decide(body.ids, body.decision, body.notas)
    # se aprovado em lote, salva todos na biblioteca
    if body.decision == "aprovado":
        try:
            for iid in body.ids:
                it = curation.curation_get(iid)
                if it:
                    v = it.get("video", {})
                    storage.library_add({"kind": "video", "ref": v.get("id"),
                                         "title": v.get("title"),
                                         "payload": {"curadoria_id": iid, **v}})
        except Exception:
            pass
    return res


@app.post("/api/curation/items/{item_id}/enrich")
async def curation_enrich_endpoint(item_id: str, body: CurationEnrichIn,
                                   x_pipeline_token: Optional[str] = Header(None)):
    # token opcional para n8n
    if x_pipeline_token and not pipeline.check_token(x_pipeline_token):
        if storage.settings_get().get("N8N_TOKEN"):
            raise HTTPException(401, "Token inválido")
    updated = curation.curation_enrich(item_id, {
        "hooks": body.hooks,
        "analise": body.analise,
        "tags_sugeridas": body.tags_sugeridas,
        "titulo_sugerido": body.titulo_sugerido,
        "notas_ia": body.notas_ia,
        "extra": body.extra,
    })
    if not updated:
        raise HTTPException(404, "Item não encontrado")
    return {"ok": True, "item": updated}


@app.post("/api/curation/items/{item_id}/auto-enrich")
async def curation_auto_enrich(item_id: str):
    """Enriquece automaticamente com IA (hooks + análise Viral Lab)."""
    it = curation.curation_get(item_id)
    if not it:
        raise HTTPException(404, "Item não encontrado")
    video = it.get("video", {})
    title = video.get("title", "")

    # gera hooks e análise em paralelo
    hooks_task = ai_engine.generate_hooks(title[:80] or video.get("author", "produto"),
                                          niche="", audience="", tone="direto", count=5)
    analyze_task = ai_engine.analyze_video(title)

    hooks_res, analise_res = await asyncio.gather(hooks_task, analyze_task)

    enrich = {
        "hooks": hooks_res.get("hooks", [])[:5],
        "analise": analise_res,
        "tags_sugeridas": list(set((video.get("hashtags") or []) + ["#viral", "#curadoria"])),
        "titulo_sugerido": f"{title[:60]} — análise curadoria",
        "notas_ia": f"Outlier {analise_res.get('outlier_score', 0)} · {analise_res.get('veredito', '')}",
        "extra": {"engine_hooks": hooks_res.get("engine"), "engine_analise": analise_res.get("engine")},
    }
    updated = curation.curation_enrich(item_id, enrich)
    return {"ok": True, "item": updated, "enrich": enrich}


@app.delete("/api/curation/items/{item_id}")
async def curation_delete_endpoint(item_id: str):
    if not curation.curation_delete(item_id):
        raise HTTPException(404, "Item não encontrado")
    return {"ok": True}


@app.post("/api/curation/clear")
async def curation_clear(status: str = ""):
    """Limpa fila por status (ex: rejeitados)."""
    from .storage import DATA_DIR, _read, _write, _lock
    with _lock:
        all_items = _read(curation.CURATION_FILE, [])
        if status and status in curation.VALID_DECISIONS:
            kept = [i for i in all_items if i.get("status") != status]
            removed = len(all_items) - len(kept)
        else:
            kept = []
            removed = len(all_items)
        _write(curation.CURATION_FILE, kept)
    return {"ok": True, "removidos": removed}


# ------------------------------------------------------------ biblioteca
class LibraryItem(BaseModel):
    kind: str = "video"
    ref: str = ""
    title: str = ""
    payload: dict = {}


@app.get("/api/library")
async def library():
    return {"items": storage.library_list()}


@app.post("/api/library")
async def library_add(item: LibraryItem):
    saved = storage.library_add({"kind": item.kind, "ref": item.ref,
                                 "title": item.title, "payload": item.payload})
    return {"saved": saved, "count": len(storage.library_list())}


@app.delete("/api/library/{item_id}")
async def library_del(item_id: str):
    if not storage.library_remove(item_id):
        raise HTTPException(404, "Item não encontrado")
    return {"ok": True, "count": len(storage.library_list())}


# ------------------------------------------------------------ conexões
@app.get("/api/settings")
async def get_settings():
    cfg = storage.settings_get()
    return {"settings": {k: storage.secret_mask(v) if "TOKEN" in k or "KEY" in k
                         or "SECRET" in k else v
                         for k, v in cfg.items()},
            "connected": [k for k, v in provider_status().items() if v["conectado"]]}


class SettingsIn(BaseModel):
    settings: dict


@app.post("/api/settings")
async def save_settings(body: SettingsIn):
    storage.settings_save(body.settings)
    return await get_settings()


@app.post("/api/settings/test/{service}")
async def test_service(service: str):
    if service == "youtube":
        return await providers.youtube_key_test()
    if service == "coleta":
        return await asyncio.wait_for(
            asyncio.to_thread(scrapling_sources.health_check), timeout=60)
    if service == "n8n":
        cfg = storage.settings_get()
        url = cfg.get("N8N_WEBHOOK_URL", "")
        if not url:
            return {"ok": False, "message": "Configure a URL do webhook do n8n primeiro."}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.post(url, json={"ping": True,
                                                 "token": cfg.get("N8N_TOKEN", "")})
            if r.status_code < 400:
                return {"ok": True, "message": f"n8n respondeu ({r.status_code}) — conexão ok."}
            return {"ok": False, "message": f"n8n respondeu com erro {r.status_code}."}
        except Exception as e:
            return {"ok": False, "message": f"Webhook inacessível: {type(e).__name__}"}
    if service == "fontes":
        testes = {}
        for nome, fn, arg in [("mercadolivre", free_sources.mercadolivre_search, "garrafa térmica"),
                              ("reddit", free_sources.reddit_trending, "Brasil"),
                              ("google_suggest", free_sources.google_suggest, "como ganhar dinheiro")]:
            try:
                r = await asyncio.wait_for(asyncio.to_thread(fn, arg), timeout=20)
                testes[nome] = {"ok": bool(r), "itens": len(r)}
            except Exception as e:
                testes[nome] = {"ok": False, "erro": type(e).__name__}
        ok = sum(1 for t in testes.values() if t.get("ok"))
        return {"ok": ok > 0, "message": f"{ok}/3 fontes gratuitas respondendo",
                "detalhe": testes}
    if service == "instagram":
        return await providers.ig_token_test()
    if service == "tiktok":
        token = await providers._tiktok_token()
        if token:
            return {"ok": True, "message": "Credenciais válidas — TikTok Research conectado."}
        cfg = storage.settings_get()
        if not (cfg.get("TIKTOK_CLIENT_KEY") and cfg.get("TIKTOK_CLIENT_SECRET")):
            return {"ok": False, "message": "Preencha Client Key e Secret da Research API."}
        return {"ok": False, "message": "Credenciais recusadas. Verifique se o app foi aprovado."}
    raise HTTPException(404, "Serviço desconhecido")


# ------------------------------------------------------------ frontend
STATIC = ROOT / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.exception_handler(Exception)
async def unhandled(request, exc):  # resposta amigável em JSON
    return JSONResponse(status_code=500, content={"error": str(exc)})
