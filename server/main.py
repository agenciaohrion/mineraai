"""MineraAI — Ecossistema completo de descoberta viral, inteligência de produtos
e criação de conteúdo com IA.

Funcionalidades inspiradas em ferramentas de pesquisa viral, analytics de
TikTok Shop e laboratórios de criação para canais dark — reconstruídas do zero
com design próprio e arquitetura de dados plugável (APIs oficiais + demo).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (agents, ai_engine, credits, data as demo, free_sources, media,
               metrics, mining, pipeline, providers, research, retention, runpod,
               schema, storage, virlo)

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="MineraAI", version="2.0.0",
              description="Ecossistema unificado de descoberta viral, inteligência "
                          "de commerce e produção de conteúdo com IA")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

PLATFORMS = {"tiktok", "instagram", "youtube", "all"}

# A camada de fontes vive em research.py; aqui só reexportamos para os endpoints
provider_status = research.provider_status


# ------------------------------------------------------------ tenant / billing
async def current_tenant(x_api_key: Optional[str] = Header(None),
                         authorization: Optional[str] = Header(None)) -> dict:
    """Resolve o workspace pelo header `X-API-Key` (ou `Authorization: Bearer`).

    Sem chave, cai no workspace de demonstração (plano free) — assim a
    plataforma continua explorável sem cadastro, como nos apps de referência.
    """
    key = (x_api_key or "").strip()
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    if key:
        tenant = credits.resolve_key(key)
        if not tenant:
            raise HTTPException(401, "Chave de API inválida ou revogada")
        return tenant
    return credits.get_tenant(credits.DEFAULT_TENANT) or credits.ensure_default()


@app.on_event("startup")
async def _startup() -> None:
    credits.ensure_default()
    if os.environ.get("AGENTS_SCHEDULER", "1") == "0":
        return
    interval = max(15, int(os.environ.get("AGENTS_INTERVAL", "60")))
    app.state.agents_task = asyncio.create_task(agents.scheduler_loop(interval))
    # monitor de nicho (Comet) — mesmo formato de agendador dos agents
    if os.environ.get("MINING_SCHEDULER", "1") != "0":
        app.state.mining_task = asyncio.create_task(mining.scheduler_loop(120))
    # retenção: roda uma vez no boot e depois a cada RETENTION_INTERVALO_H
    if os.environ.get("RETENTION_ENABLED", "1") != "0":
        app.state.retention_task = asyncio.create_task(retention.loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    for attr in ("agents_task", "mining_task", "retention_task"):
        task = getattr(app.state, attr, None)
        if task:
            task.cancel()


@app.get("/api/status")
async def status():
    """Modo de operação + estado de cada fonte de dados."""
    return research.mode()


# ------------------------------------------------------------ radar viral
@app.get("/api/search")
async def search(q: str = "tendências", platform: str = "all", period: str = "30d",
                 sort: str = "viral_score", min_views: int = 0, limit: int = 14,
                 source: str = "all", include_demo: bool = True,
                 tenant: dict = Depends(current_tenant)):
    """Radar Viral — busca unificada (oficial → Virlo → mineração → demo).

    `source` isola uma camada: `oficial`, `virlo`, `mineracao` ou `demo`.
    Com `include_demo=false` o demo nunca entra como reserva — útil para quem
    paga por cobertura real e não quer número estimado misturado no relatório.
    """
    credits.charge(tenant["id"], "search", meta={"q": q, "platform": platform,
                                                 "source": source})
    limit = max(3, min(limit, 30))
    data = await research.search_videos(q, platform, period, min_views, limit,
                                        include_demo=include_demo, source=source)
    videos = research.sort_videos(data["videos"], sort)
    return {
        "query": q, "period": data["period"], "sort": sort,
        "source": data["source"], "include_demo": include_demo,
        "source_breakdown": data["source_breakdown"],
        "errors": data["errors"],
        "coleta_errors": data["errors"],
        "videos": videos[:limit * (3 if platform == "all" else 1)],
        "top_hashtags": data["facets"]["top_hashtags"],
        "top_sounds": data["facets"]["top_sounds"],
        "top_creators": data["facets"]["top_creators"],
        "total": len(videos),
    }


@app.get("/api/outliers")
async def outliers(q: str = "tendências", platform: str = "all", period: str = "30d",
                   limit: int = 12, min_score: int = 30,
                   tenant: dict = Depends(current_tenant)):
    """Outlier detection — vídeos furando a curva do criador/nicho.

    É o sinal preditivo do ecossistema: mostra o que está crescendo ANTES de
    aparecer na aba de tendências da plataforma.
    """
    credits.charge(tenant["id"], "outliers", meta={"q": q})
    return await research.find_outliers(q, platform, period, limit, min_score)


# ------------------------------------------------------------ produtos
@app.get("/api/products")
async def products(q: Optional[str] = None, category: str = "", sort: str = "gmv",
                   limit: int = 18, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "products", meta={"q": q or "", "category": category})
    raw_items = demo.demo_products(q, category, sort, min(limit, 40))
    items = [schema.normalize_product(p) for p in raw_items]
    total_gmv = sum(p["gmv"] for p in items)
    out = {"products": items, "total_gmv": total_gmv,
           "categories": list(demo.NICHOS.keys()),
           "lojas": [schema.normalize_shop(s) for s in demo.demo_shops(q, category, "gmv", 6)],
           "note": ("Estimativas com faixa de confiança (unidades × ticket). Rankings são "
                    "confiáveis; valores absolutos são direcionais."),
           "mercadolivre": [], "ml_signal": {}}
    # Mercado Livre: dados REAIS de mercado BR — API pública oficial, sem chave
    if q:
        try:
            ml = await asyncio.wait_for(
                asyncio.to_thread(free_sources.mercadolivre_search, q, 12), timeout=30)
            out["mercadolivre"] = ml
            out["ml_signal"] = free_sources.mercadolivre_trend_signal(ml)
        except Exception:
            out["mercadolivre"] = []
    return out


# ------------------------------------------------------------ lojas (commerce)
@app.get("/api/shops")
async def shops(q: Optional[str] = None, category: str = "", sort: str = "gmv",
                limit: int = 16, tenant: dict = Depends(current_tenant)):
    """Ranking de lojas do TikTok Shop: GMV, crescimento, catálogo e dependência de live."""
    credits.charge(tenant["id"], "products", meta={"q": q or "", "view": "shops"})
    items = [schema.normalize_shop(sh) for sh in demo.demo_shops(q, category, sort, min(limit, 40))]
    return {
        "shops": items,
        "total_gmv": sum(i["gmv"] for i in items),
        "categorias": list(demo.NICHOS.keys()),
        "note": "GMV estimado por modelo público, com faixa de confiança.",
    }


@app.get("/api/shops/{shop_id}")
async def shop_detail(shop_id: str, tenant: dict = Depends(current_tenant)):
    return schema.normalize_shop(demo.demo_shop_detail(shop_id))


# ------------------------------------------------------------ ideias de pauta
@app.get("/api/ideas")
async def ideas(q: str = "renda extra", subreddit: str = "Brasil",
                tenant: dict = Depends(current_tenant)):
    """Pauta viral: top do Reddit + autocomplete do Google (grátis, sem chave)."""
    credits.charge(tenant["id"], "ideas", meta={"q": q})
    result = {"reddit": [], "sugestoes": [], "subreddit": subreddit,
              "reddit_oauth": free_sources.reddit_configured()}
    try:
        result["reddit"] = await asyncio.wait_for(
            asyncio.to_thread(free_sources.reddit_trending, subreddit, 8), timeout=30)
    except Exception:
        pass
    try:
        result["sugestoes"] = await asyncio.wait_for(
            asyncio.to_thread(free_sources.google_suggest, q), timeout=20)
    except Exception:
        pass
    return result


@app.get("/api/products/{product_id}")
async def product_detail(product_id: str):
    return demo.demo_product_detail(product_id)


# ------------------------------------------------------------ criadores
@app.get("/api/creators")
async def creators(q: Optional[str] = None, platform: str = "all", limit: int = 14,
                   tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "creators", meta={"q": q or ""})
    items = [schema.normalize_creator(c) for c in demo.demo_creators(q, platform, min(limit, 30))]
    return {"creators": items}


# ------------------------------------------------------------ vídeos & lives
@app.get("/api/lives")
async def lives(limit: int = 12, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "lives")
    ls = [schema.normalize_live(l) for l in demo.demo_lives(min(limit, 30))]
    return {"lives": ls,
            "gmv_total": sum(l["gmv"] for l in ls),
            "ao_vivo_agora": sum(1 for l in ls if l["live_now"])}


# ------------------------------------------------------------ tendências reais
@app.get("/api/trends")
async def trends(limit: int = 12, tenant: dict = Depends(current_tenant)):
    """Termos em alta agora — Google Trends (RSS público, sem chave)."""
    credits.charge(tenant["id"], "trends")
    try:
        terms = await asyncio.wait_for(
            asyncio.to_thread(free_sources.google_trends_br, min(limit, 20)), timeout=30)
        return {"terms": terms, "fonte": "Google Trends (tempo real)",
                "geo": storage.settings_get().get("TRENDS_GEO") or "BR"}
    except Exception as e:
        return {"terms": [], "fonte": "indisponível",
                "erro": f"{type(e).__name__}: {str(e)[:90]}"}


# ------------------------------------------------------------ radar de nichos
@app.get("/api/niches")
async def niches(limit: int = 14, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "niches")
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
async def ai_hooks(body: HooksIn, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "ai_hooks", meta={"product": body.product})
    return await ai_engine.generate_hooks(body.product, body.niche, body.audience,
                                          body.tone, max(3, min(body.count, 14)))


@app.post("/api/ai/script")
async def ai_script(body: ScriptIn, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "ai_script", meta={"product": body.product})
    return await ai_engine.generate_script(body.product, body.niche,
                                           max(10, min(body.duration, 180)), body.format)


@app.post("/api/ai/caption")
async def ai_caption(body: CaptionIn, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "ai_caption")
    plat = body.platform if body.platform in {"tiktok", "instagram", "youtube"} else "tiktok"
    return await ai_engine.generate_caption(body.product, plat, body.benefit)


@app.post("/api/ai/titles")
async def ai_titles(body: TitlesIn, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "ai_titles")
    return await ai_engine.generate_titles(body.theme)


@app.post("/api/ai/analyze")
async def ai_analyze(body: AnalyzeIn, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "ai_analyze")
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
async def ai_narration(body: NarrationIn, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "ai_narration", meta={"chars": len(body.text)})
    tone = body.tone if body.tone in {"suspense", "energetico", "documental",
                                      "jornalistico"} else "suspense"
    return ai_engine.prepare_narration(body.text, tone)


# ------------------------------------------------------------ Fábrica de Vídeos (RunPod direto)
class JobIn(BaseModel):
    product: str = Field(..., min_length=2, max_length=160)
    prompt: str = Field("", max_length=2000)
    style: str = "dark"
    duration: int = 6
    mode: str = "sync"          # sync | async
    images: list = []


class IngestIn(BaseModel):
    videos: list = []
    query: str = ""


class OrbitIn(BaseModel):
    name: str = ""
    keywords: list = []
    platforms: list = ["tiktok", "instagram", "youtube"]
    min_views: int = 0


class CometIn(BaseModel):
    name: str = ""
    keywords: list = []
    platforms: list = ["tiktok", "instagram", "youtube"]
    frequency: str = "daily"
    min_views: int = 0


@app.post("/api/fabrica/jobs")
async def fabrica_create(body: JobIn, tenant: dict = Depends(current_tenant)):
    """Cria o job e chama o RunPod DIRETO (sem n8n).

    `sync` espera o resultado (clipe curto); `async` devolve na hora e o job é
    acompanhado por `GET /api/fabrica/jobs/{id}/poll`.
    """
    credits.charge(tenant["id"], "fabrica_job", meta={"product": body.product})
    job = pipeline.job_create(body.product, body.prompt, body.style,
                             max(2, min(body.duration, 60)),
                             extra={"images": body.images or []},
                             tenant_id=tenant["id"])
    mode = "async" if body.mode == "async" else "sync"
    updated = await pipeline.dispatch_to_runpod(job, mode=mode)
    return {"job": updated, "runpod_configurado": runpod.configured()}


@app.get("/api/fabrica/jobs")
async def fabrica_list():
    jobs = pipeline.jobs_list()
    return {"jobs": jobs,
            "runpod_configurado": runpod.configured(),
            "runpod": runpod.status_resumo()}


@app.get("/api/fabrica/jobs/{job_id}")
async def fabrica_get(job_id: str):
    job = pipeline.job_get(job_id)
    if not job:
        raise HTTPException(404, "Job não encontrado")
    return {"job": job}


@app.get("/api/fabrica/jobs/{job_id}/poll")
async def fabrica_poll(job_id: str):
    """Consulta o RunPod e atualiza o job (para os jobs assíncronos)."""
    try:
        return {"job": await pipeline.poll_job(job_id)}
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    except runpod.RunPodError as exc:
        raise HTTPException(502, str(exc))


@app.post("/api/fabrica/jobs/{job_id}/cancel")
async def fabrica_cancel(job_id: str):
    try:
        return {"job": await pipeline.cancel_job(job_id)}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/fabrica/jobs/{job_id}/file")
async def fabrica_file(job_id: str, download: bool = False,
                       tenant: dict = Depends(current_tenant)):
    """Serve o arquivo local do job (o vídeo não depende mais do S3 do RunPod).

    A URL do worker expira; este endpoint não. Exige o workspace dono do job.
    """
    try:
        info = pipeline.job_media_file(job_id, tenant["id"])
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    if not info:
        raise HTTPException(404, "Este job não tem arquivo salvo")
    if download:
        # attachment explícito: navegador baixa em vez de abrir
        return FileResponse(info["path"], media_type=info["media_type"],
                            filename=f"{job_id}{Path(info['nome']).suffix}")
    # inline: o <video src> toca direto, sem forçar download
    return FileResponse(info["path"], media_type=info["media_type"])


@app.delete("/api/fabrica/jobs/{job_id}")
async def fabrica_delete(job_id: str):
    if not pipeline.job_delete(job_id):
        raise HTTPException(404, "Job não encontrado")
    return {"ok": True}


@app.get("/api/fabrica/broll")
async def fabrica_broll(q: str = "produto", tenant: dict = Depends(current_tenant)):
    """B-roll gratuito (Pexels, chave própria) para enriquecer os vídeos."""
    credits.charge(tenant["id"], "broll")
    return await asyncio.to_thread(free_sources.pexels_broll, q, 10)


# ------------------------------------------------------------ RunPod (conexão direta)
@app.get("/api/runpod/health")
async def runpod_health(tenant: dict = Depends(current_tenant)):
    """Workers prontos, fila e execuções em andamento no endpoint configurado."""
    if not runpod.configured():
        return {"ok": False,
                "message": "Configure API key e endpoint id do RunPod."}
    try:
        return await runpod.health()
    except runpod.RunPodError as exc:
        return {"ok": False, "message": str(exc), "status": exc.status}


@app.get("/api/runpod/workflow")
async def runpod_workflow():
    """Mostra qual grafo ComfyUI será enviado (template salvo ou o padrão)."""
    template = runpod.load_template()
    return {"fonte": "template salvo" if template else "workflow padrão (SDXL txt2img)",
            "workflow": template or runpod.WORKFLOW_PADRAO,
            "estilos": list(runpod.ESTILOS.keys()),
            "custo_gpu_hora": runpod.gpu_price_hora()}


# ------------------------------------------------------------ Virlo API
@app.get("/api/virlo/balance")
async def virlo_balance():
    try:
        return await virlo.balance()
    except virlo.VirloError as exc:
        return {"ok": False, "message": str(exc), "status": exc.status}


@app.get("/api/virlo/trends")
async def virlo_trends(limit: int = 20, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "virlo_read")
    try:
        return {"trends": await virlo.trending(min(limit, 50))}
    except virlo.VirloError as exc:
        return {"trends": [], "message": str(exc)}


@app.get("/api/virlo/hashtags")
async def virlo_hashtags(limit: int = 30, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "virlo_read")
    try:
        return {"hashtags": await virlo.hashtags(min(limit, 100))}
    except virlo.VirloError as exc:
        return {"hashtags": [], "message": str(exc)}


@app.post("/api/virlo/orbit")
async def virlo_orbit_create(body: OrbitIn, tenant: dict = Depends(current_tenant)):
    """Enfileira um Orbit na Virlo (US$ 0,50 ≈ 60 créditos). Leva 5–10 min."""
    credits.charge(tenant["id"], "virlo_orbit", meta={"keywords": body.keywords})
    try:
        orbit = await virlo.orbit_create(body.name or (body.keywords or ["busca"])[0],
                                        body.keywords, body.platforms, body.min_views)
        return {"orbit": orbit, "aviso": "Processamento na Virlo leva 5–10 minutos."}
    except virlo.VirloError as exc:
        raise HTTPException(502, str(exc))


@app.get("/api/virlo/orbit")
async def virlo_orbit_list():
    try:
        return {"orbits": await virlo.orbit_list()}
    except virlo.VirloError as exc:
        return {"orbits": [], "message": str(exc)}


@app.get("/api/virlo/orbit/{orbit_id}")
async def virlo_orbit_status(orbit_id: str, videos: bool = True, limit: int = 25):
    try:
        orbit = await virlo.orbit_get(orbit_id)
        out = {"orbit": orbit}
        if videos:
            out["videos"] = await virlo.orbit_videos(orbit_id, min(limit, 100))
            out["outliers"] = await virlo.orbit_outliers(orbit_id, 20)
        return out
    except virlo.VirloError as exc:
        raise HTTPException(502, str(exc))


@app.get("/api/virlo/satellite/{platform}/{username}")
async def virlo_satellite(platform: str, username: str,
                          tenant: dict = Depends(current_tenant)):
    """Ficha de criador (US$ 0,50 ≈ 60 créditos)."""
    credits.charge(tenant["id"], "virlo_satellite", meta={"user": username})
    try:
        return {"creator": await virlo.satellite(platform, username)}
    except virlo.VirloError as exc:
        raise HTTPException(502, str(exc))


# ------------------------------------------------------------ Mineração própria (Orbit/Comet)
@app.get("/api/mining/como-funciona")
async def mining_explain():
    """Transparência: o pipeline de mineração, etapa por etapa."""
    return mining.como_funciona()


@app.post("/api/mining/orbits")
async def mining_orbit_create(body: OrbitIn, tenant: dict = Depends(current_tenant)):
    """Cria um Orbit próprio e executa a coleta na hora."""
    credits.charge(tenant["id"], "mining_orbit", meta={"keywords": body.keywords})
    try:
        orbit = mining.orbit_create(tenant["id"], body.name, body.keywords,
                                    body.platforms, body.min_views)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"orbit": await mining.orbit_run(orbit["id"], tenant["id"])}


@app.get("/api/mining/orbits")
async def mining_orbit_list(tenant: dict = Depends(current_tenant)):
    return {"orbits": mining.orbit_list(tenant["id"])}


@app.get("/api/mining/orbits/{orbit_id}")
async def mining_orbit_get(orbit_id: str, limit: int = 50,
                           tenant: dict = Depends(current_tenant)):
    orbit = mining.orbit_get(orbit_id, tenant["id"])
    if not orbit:
        raise HTTPException(404, "Orbit não encontrado")
    return {"orbit": {k: v for k, v in orbit.items() if k != "videos"},
            "videos": mining.orbit_videos(orbit_id, limit, tenant_id=tenant["id"]),
            "outliers": mining.orbit_outliers(orbit_id, 20, tenant["id"])}


@app.delete("/api/mining/orbits/{orbit_id}")
async def mining_orbit_delete(orbit_id: str, tenant: dict = Depends(current_tenant)):
    if not mining.orbit_delete(orbit_id, tenant["id"]):
        raise HTTPException(404, "Orbit não encontrado")
    return {"ok": True}


@app.post("/api/mining/comets")
async def mining_comet_create(body: CometIn, tenant: dict = Depends(current_tenant)):
    """Monitor de nicho agendado (o equivalente ao Comet da Virlo)."""
    try:
        comet = mining.comet_create(tenant["id"], body.name, body.keywords,
                                    body.platforms, body.frequency, body.min_views)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"comet": comet}


@app.get("/api/mining/comets")
async def mining_comet_list(tenant: dict = Depends(current_tenant)):
    return {"comets": mining.comet_list(tenant["id"])}


@app.post("/api/mining/comets/{comet_id}/run")
async def mining_comet_run(comet_id: str, tenant: dict = Depends(current_tenant)):
    credits.charge(tenant["id"], "mining_comet", meta={"comet": comet_id})
    try:
        return {"comet": await mining.comet_run(comet_id, tenant["id"])}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.delete("/api/mining/comets/{comet_id}")
async def mining_comet_delete(comet_id: str, tenant: dict = Depends(current_tenant)):
    if not mining.comet_delete(comet_id, tenant["id"]):
        raise HTTPException(404, "Comet não encontrado")
    return {"ok": True}


@app.post("/api/ingest/videos")
async def ingest_videos(body: IngestIn, tenant: dict = Depends(current_tenant)):
    """Qualquer integração externa pode empurrar vídeos minerados (grátis)."""
    n = mining.ingest_videos(body.videos or [], body.query or "ingestao")
    return {"ok": True, "importados": n}


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


# ------------------------------------------------------------ manutenção / retenção
@app.get("/api/maintenance/status")
async def maintenance_status():
    """Configuração de retenção, uso de disco e último relatório de poda."""
    return retention.status()


@app.post("/api/maintenance/run")
async def maintenance_run(tenant: dict = Depends(current_tenant)):
    """Roda a poda agora (sem esperar o ciclo do agendador)."""
    return await asyncio.to_thread(retention.run, True)


# ------------------------------------------------------------ conexões
@app.get("/api/settings")
async def get_settings():
    cfg = storage.settings_get()
    return {"settings": {k: storage.secret_mask(v) if storage.is_secret(k) else v
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
    """Teste ISOLADO por integração — cada fonte responde por si.

    Nenhuma credencial é compartilhada: se o Reddit falha, o Mercado Livre
    continua funcionando e o diagnóstico diz exatamente qual fonte caiu.
    """
    # ---- plataformas oficiais
    if service == "youtube":
        return await providers.youtube_key_test()
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

    # ---- IA (dois provedores independentes)
    if service in ("openai", "gemini"):
        return await ai_engine.test_provider(service)

    # ---- dados pagos
    if service == "virlo":
        if not virlo.configured():
            return {"ok": False, "message": "Informe a API key da Virlo (virlo_tkn_...)."}
        try:
            res = await virlo.balance()
            saldo = res.get("balance") or {}
            return {"ok": True,
                    "message": f"Virlo conectada — saldo: {json.dumps(saldo, ensure_ascii=False)[:120]}"}
        except virlo.VirloError as exc:
            return {"ok": False, "message": str(exc)}

    # ---- fontes gratuitas (uma por uma)
    if service == "reddit":
        return await asyncio.to_thread(free_sources.reddit_test)
    if service == "mercadolivre":
        return await asyncio.to_thread(free_sources.mercadolivre_test)
    if service in ("suggest", "google_suggest"):
        return await asyncio.to_thread(free_sources.google_suggest_test)
    if service == "oembed":
        return await asyncio.to_thread(free_sources.oembed_test)
    if service in ("trends", "google_trends"):
        return await asyncio.to_thread(free_sources.trends_test)
    if service == "pexels":
        return await asyncio.to_thread(free_sources.pexels_test)

    # ---- produção
    if service == "runpod":
        if not runpod.configured():
            return {"ok": False, "message": "Informe API key e endpoint id do RunPod."}
        try:
            h = await runpod.health()
            w, f = h["workers"], h["fila"]
            return {"ok": True,
                    "message": (f"RunPod ok — {w['prontos']} worker(s) pronto(s), "
                                f"{f['na_fila']} na fila, {f['em_execucao']} executando"),
                    "detalhe": h}
        except runpod.RunPodError as exc:
            return {"ok": False, "message": str(exc), "status": exc.status}

    raise HTTPException(404, "Serviço desconhecido")


# ------------------------------------------------------------ OAuth (Reddit / Mercado Livre)
@app.post("/api/integrations/reddit/token")
async def reddit_token(force: bool = True):
    """Força a emissão do token OAuth client_credentials do Reddit."""
    res = await asyncio.to_thread(free_sources.reddit_token, force)
    if res.get("error"):
        return {"ok": False, "message": res["error"]}
    if not res:
        return {"ok": False, "message": "Preencha Client ID e Client Secret do Reddit."}
    return {"ok": True, "message": "Token OAuth emitido e cacheado",
            "expira_em": res.get("exp"), "escopo": res.get("scope", "")}


@app.get("/api/integrations/meli/authorize")
async def meli_authorize():
    """Devolve a URL de consentimento do Mercado Livre (authorization_code)."""
    return await asyncio.to_thread(free_sources.meli_authorize_url, "mineraai")


class MeliCallbackIn(BaseModel):
    code: str = Field(..., min_length=4)


@app.post("/api/integrations/meli/callback")
async def meli_callback(body: MeliCallbackIn):
    """Troca o ?code do redirect pelo par access/refresh token e persiste.

    Versão POST: usada pelo diálogo do app quando o redirect não volta para cá
    (ex.: redirect_uri apontando para outra máquina) e o usuário cola o `code`.
    """
    return await asyncio.to_thread(free_sources.meli_exchange_code, body.code)


def _meli_page(ok: bool, mensagem: str) -> str:
    """Página mínima de retorno do OAuth — sem SPA, sem dependência externa."""
    cor = "#22c55e" if ok else "#ef4444"
    icone = "✔" if ok else "✖"
    titulo = "Mercado Livre autorizado" if ok else "Falha na autorização"
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{titulo} · MineraAI</title>
{'<meta http-equiv="refresh" content="2;url=/#/apis" />' if ok else ''}
<style>
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
          background:#0b0f17; color:#e7ecf3;
          font:15px/1.6 system-ui,-apple-system,Segoe UI,sans-serif; }}
  .box {{ max-width:520px; padding:32px 28px; border:1px solid #1e293b;
          border-radius:16px; background:#0f1622; text-align:center; }}
  .ico {{ font-size:34px; color:{cor}; }}
  h1 {{ font-size:19px; margin:14px 0 8px; }}
  p {{ color:#94a3b8; margin:0 0 18px; }}
  a {{ display:inline-block; padding:10px 18px; border-radius:10px;
       background:#f59e0b; color:#111; font-weight:600; text-decoration:none; }}
</style></head><body><div class="box">
  <div class="ico">{icone}</div>
  <h1>{titulo}</h1>
  <p>{mensagem}</p>
  <a href="/#/apis">Voltar para APIs &amp; Conexões</a>
</div></body></html>"""


@app.get("/api/integrations/meli/callback", response_class=HTMLResponse)
async def meli_callback_get(code: str = "", state: str = "",
                            error: str = "", error_description: str = ""):
    """Recebe o redirect do Mercado Livre (GET) e conclui o OAuth.

    A Mercado Livre devolve o navegador do usuário para esta URL com `?code=…`,
    então esta rota **não pode exigir autenticação** — não é um cliente da API
    chegando, é o navegador. A troca do `code` é feita no servidor e o usuário
    volta para a tela de integrações já com os tokens salvos.
    """
    if error or not code:
        motivo = error_description or error or (
            "O Mercado Livre não devolveu o código de autorização. "
            "Tente autorizar novamente pelo botão no app.")
        return HTMLResponse(_meli_page(False, motivo), status_code=400)

    res = await asyncio.to_thread(free_sources.meli_exchange_code, code)
    if not res.get("ok"):
        return HTMLResponse(
            _meli_page(False, res.get("message") or "Não foi possível trocar o código."),
            status_code=400)
    expira = res.get("expires_in")
    detalhe = (f"Tokens salvos neste servidor (access token válido por "
               f"{int(expira) // 3600}h, renovado automaticamente)."
               if expira else "Tokens salvos neste servidor.")
    return HTMLResponse(_meli_page(True, detalhe))


@app.post("/api/integrations/meli/refresh")
async def meli_refresh():
    return await asyncio.to_thread(free_sources.meli_refresh)


@app.get("/api/integrations")
async def integrations():
    """Inventário de integrações com estado, auth e campos — a UI monta os cards daqui."""
    cfg = storage.settings_get()
    st = research.provider_status()
    return {
        "integracoes": [{**v, "id": k, "campos": _campos_por_integracao(k)} for k, v in st.items()],
        "fontes_gratuitas": free_sources.FREE_SOURCES,
        "meli_redirect_uri": free_sources.meli_redirect_uri(),
        "meli_tokens": {
            "access": storage.secret_mask(cfg.get("MELI_ACCESS_TOKEN", "")),
            "refresh": storage.secret_mask(cfg.get("MELI_REFRESH_TOKEN", "")),
            "expira_em": cfg.get("MELI_TOKEN_EXPIRES_AT", ""),
        },
        "virlo": {"conectado": virlo.configured(), "auto_use": virlo.auto_use(),
                  "base_url": cfg.get("VIRLO_BASE_URL") or virlo.BASE_PADRAO},
        "runpod": runpod.status_resumo(),
    }


def _campos_por_integracao(chave: str) -> list[dict]:
    """Contrato de campos por integração (consumido pela tela de conexões)."""
    mapa = {
        "youtube": [{"k": "YOUTUBE_API_KEY", "tipo": "secret", "label": "API key"}],
        "tiktok": [{"k": "TIKTOK_CLIENT_KEY", "tipo": "secret", "label": "Client key"},
                   {"k": "TIKTOK_CLIENT_SECRET", "tipo": "secret", "label": "Client secret"}],
        "instagram": [{"k": "IG_ACCESS_TOKEN", "tipo": "secret", "label": "Access token"},
                      {"k": "IG_USER_ID", "tipo": "text", "label": "IG user id"}],
        "virlo": [{"k": "VIRLO_API_KEY", "tipo": "secret", "label": "API key (virlo_tkn_...)"},
                  {"k": "VIRLO_AUTO_USE", "tipo": "bool", "label": "Usar como fonte no Radar"},
                  {"k": "VIRLO_BASE_URL", "tipo": "text", "label": "Base URL (opcional)"}],
        "openai": [{"k": "OPENAI_API_KEY", "tipo": "secret", "label": "API key"},
                   {"k": "OPENAI_MODEL", "tipo": "text", "label": "Modelo"},
                   {"k": "OPENAI_BASE_URL", "tipo": "text", "label": "Base URL"}],
        "gemini": [{"k": "GEMINI_API_KEY", "tipo": "secret", "label": "API key"},
                   {"k": "GEMINI_MODEL", "tipo": "text", "label": "Modelo"}],
        "reddit": [{"k": "REDDIT_CLIENT_ID", "tipo": "secret", "label": "Client id"},
                   {"k": "REDDIT_CLIENT_SECRET", "tipo": "secret", "label": "Client secret"},
                   {"k": "REDDIT_USER_AGENT", "tipo": "text", "label": "User agent"},
                   {"k": "REDDIT_DEFAULT_SUB", "tipo": "text", "label": "Subreddit padrão"}],
        "mercadolivre": [{"k": "MELI_CLIENT_ID", "tipo": "secret", "label": "Client id"},
                         {"k": "MELI_CLIENT_SECRET", "tipo": "secret", "label": "Client secret"},
                         {"k": "MELI_REDIRECT_URI", "tipo": "text", "label": "Redirect URI"},
                         {"k": "MELI_SITE_ID", "tipo": "text", "label": "Site (MLB)"}],
        "suggest": [{"k": "GOOGLE_SUGGEST_HL", "tipo": "text", "label": "Idioma (hl)"},
                    {"k": "GOOGLE_SUGGEST_GL", "tipo": "text", "label": "País (gl)"},
                    {"k": "GOOGLE_CSE_API_KEY", "tipo": "secret", "label": "CSE key (opcional)"},
                    {"k": "GOOGLE_CSE_CX", "tipo": "text", "label": "CSE cx (opcional)"}],
        "oembed": [{"k": "OEMBED_TIMEOUT", "tipo": "text", "label": "Timeout (s)"},
                   {"k": "OEMBED_PROXY", "tipo": "text", "label": "Proxy (opcional)"}],
        "trends": [{"k": "TRENDS_GEO", "tipo": "text", "label": "Região (geo)"},
                   {"k": "TRENDS_LANGUAGE", "tipo": "text", "label": "Idioma (hl)"}],
        "pexels": [{"k": "PEXELS_API_KEY", "tipo": "secret", "label": "API key"}],
        "runpod": [{"k": "RUNPOD_API_KEY", "tipo": "secret", "label": "API key"},
                   {"k": "RUNPOD_ENDPOINT_ID", "tipo": "text", "label": "Endpoint id"},
                   {"k": "RUNPOD_BASE_URL", "tipo": "text", "label": "Base URL"},
                   {"k": "RUNPOD_TIMEOUT", "tipo": "text", "label": "Timeout (s)"},
                   {"k": "RUNPOD_GPU_PRICE_HORA", "tipo": "text", "label": "US$/hora GPU"},
                   {"k": "RUNPOD_WORKFLOW_TEMPLATE", "tipo": "textarea",
                    "label": "Workflow ComfyUI (API JSON)"}],
    }
    return mapa.get(chave, [])


# ------------------------------------------------------------ agents
class AgentIn(BaseModel):
    name: str = ""
    query: str = Field(..., min_length=2, max_length=160)
    platform: str = "all"
    period: str = "30d"
    niche: str = ""
    objective: str = "hooks"
    schedule: str = "manual"
    webhook: str = ""
    slack: str = ""
    discord: str = ""


class AgentPatch(BaseModel):
    name: Optional[str] = None
    query: Optional[str] = None
    platform: Optional[str] = None
    period: Optional[str] = None
    niche: Optional[str] = None
    objective: Optional[str] = None
    schedule: Optional[str] = None
    status: Optional[str] = None
    webhook: Optional[str] = None
    slack: Optional[str] = None
    discord: Optional[str] = None


@app.get("/api/agents")
async def agents_list(tenant: dict = Depends(current_tenant)):
    """Agentes de pesquisa do workspace + estatísticas de execução."""
    return {"agents": agents.list_agents(tenant["id"]),
            "stats": agents.stats(tenant["id"]),
            "custo_por_execucao": credits.price_action("agent_run"),
            "agendamentos": list(agents.SCHEDULES.keys())}


@app.post("/api/agents")
async def agents_create(body: AgentIn, tenant: dict = Depends(current_tenant)):
    agent = agents.create_agent(tenant["id"], body.model_dump())
    return {"agent": agent, "custo_por_execucao": credits.price_action("agent_run")}


@app.get("/api/agents/{agent_id}")
async def agents_get(agent_id: str, tenant: dict = Depends(current_tenant)):
    agent = agents.get_agent(agent_id, tenant["id"])
    if not agent:
        raise HTTPException(404, "Agente não encontrado")
    return {"agent": agent}


@app.patch("/api/agents/{agent_id}")
async def agents_patch(agent_id: str, body: AgentPatch,
                       tenant: dict = Depends(current_tenant)):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return {"agent": agents.update_agent(agent_id, tenant["id"], patch)}


@app.delete("/api/agents/{agent_id}")
async def agents_delete(agent_id: str, tenant: dict = Depends(current_tenant)):
    if not agents.delete_agent(agent_id, tenant["id"]):
        raise HTTPException(404, "Agente não encontrado")
    return {"ok": True}


@app.post("/api/agents/{agent_id}/run")
async def agents_run(agent_id: str, tenant: dict = Depends(current_tenant)):
    """Executa o agente agora. Custa 100 créditos (mesmo preço do concorrente)."""
    agent = agents.get_agent(agent_id, tenant["id"])
    if not agent:
        raise HTTPException(404, "Agente não encontrado")
    charged = credits.charge(tenant["id"], "agent_run",
                             meta={"agent": agent_id, "query": agent["query"]})
    result = await agents.run_agent(agent, tenant["id"])
    return {**result, "credits": charged}


# ------------------------------------------------------------ billing / workspace
@app.get("/api/me")
async def me(tenant: dict = Depends(current_tenant)):
    """Identidade do workspace + limites do plano (usado pela UI e pela API)."""
    lim = credits.limits(tenant)
    return {
        "tenant": {"id": tenant["id"], "name": tenant.get("name"),
                   "plan": tenant.get("plan"), "created_at": tenant.get("created_at")},
        "plano": lim,
        "chaves": credits.masked_keys(tenant),
        "agents": agents.stats(tenant["id"]),
    }


class WorkspaceIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    plan: str = "free"


@app.post("/api/workspaces")
async def create_workspace(body: WorkspaceIn):
    """Cadastro: cria um workspace multi-tenant e devolve a primeira chave.

    Em produção este endpoint fica atrás do Stripe Checkout; aqui ele já
    demonstra o isolamento completo (créditos, agentes e chaves por workspace).
    """
    tenant = credits.create_tenant(body.name, body.plan)
    key = tenant["api_keys"][0]
    return {
        "tenant": {"id": tenant["id"], "name": tenant["name"], "plan": tenant["plan"]},
        "api_key": key["key"],
        "aviso": "Guarde a chave: use o header X-API-Key. Ela não será exibida novamente.",
        "limites": credits.limits(tenant),
    }


@app.get("/api/billing/plans")
async def billing_plans():
    return {"plans": credits.plan_catalog(), "custo_por_acao": credits.ACTIONS}


@app.get("/api/billing/usage")
async def billing_usage(days: int = 14, tenant: dict = Depends(current_tenant)):
    return credits.usage_summary(tenant["id"], max(1, min(days, 90)))


class PlanIn(BaseModel):
    plan: str


@app.post("/api/billing/plan")
async def billing_set_plan(body: PlanIn, tenant: dict = Depends(current_tenant)):
    """Simula upgrade de plano (em produção: webhook do Stripe)."""
    updated = credits.set_plan(tenant["id"], body.plan)
    return {"ok": True, "plano": credits.limits(updated)}


class CreditsIn(BaseModel):
    amount: int
    reason: str = "compra de créditos"


@app.post("/api/billing/credits")
async def billing_add_credits(body: CreditsIn, tenant: dict = Depends(current_tenant)):
    """Adiciona créditos avulsos (top-up). Em produção: confirmação de pagamento."""
    credits.grant_credits(tenant["id"], body.amount, body.reason)
    return {"ok": True, "plano": credits.limits(credits.get_tenant(tenant["id"]))}


class KeyIn(BaseModel):
    label: str = "nova chave"


@app.post("/api/billing/keys")
async def billing_create_key(body: KeyIn, tenant: dict = Depends(current_tenant)):
    key = credits.create_key(tenant["id"], body.label)
    return {"key": key, "aviso": "Copie agora — a chave não será exibida novamente."}


@app.delete("/api/billing/keys/{key_id}")
async def billing_revoke_key(key_id: str, tenant: dict = Depends(current_tenant)):
    if not credits.revoke_key(tenant["id"], key_id):
        raise HTTPException(404, "Chave não encontrada")
    return {"ok": True}


# ------------------------------------------------------------ API pública / MCP
@app.get("/api/mcp/manifest")
async def mcp_manifest():
    """Manifesto MCP — permite que Claude/agentes externos operem o MineraAI.

    Exposto como descoberta simples (JSON); o servidor MCP completo fica em
    scripts/mcp_server.py, que consome estes mesmos endpoints.
    """
    return {
        "name": "mineraai",
        "version": app.version,
        "description": "Descoberta viral, commerce intelligence e produção de conteúdo",
        "auth": {"type": "apiKey", "header": "X-API-Key"},
        "tools": [
            {"name": "search_viral", "endpoint": "/api/search",
             "params": ["q", "platform", "period", "sort", "limit"],
             "description": "Busca vídeos virais em TikTok, Instagram e YouTube"},
            {"name": "find_outliers", "endpoint": "/api/outliers",
             "params": ["q", "platform", "period", "limit"],
             "description": "Vídeos furando a curva do próprio criador"},
            {"name": "product_ranking", "endpoint": "/api/products",
             "params": ["q", "category", "sort", "limit"]},
            {"name": "shop_ranking", "endpoint": "/api/shops",
             "params": ["q", "category", "sort", "limit"]},
            {"name": "creator_ranking", "endpoint": "/api/creators",
             "params": ["q", "platform", "limit"]},
            {"name": "niche_radar", "endpoint": "/api/niches", "params": ["limit"]},
            {"name": "generate_hooks", "endpoint": "/api/ai/hooks", "method": "POST",
             "params": ["product", "niche", "audience", "tone", "count"]},
            {"name": "generate_script", "endpoint": "/api/ai/script", "method": "POST",
             "params": ["product", "niche", "duration", "format"]},
            {"name": "run_research_agent", "endpoint": "/api/agents/{id}/run",
             "method": "POST"},
        ],
        "docs": "/docs",
    }


# ------------------------------------------------------------ frontend
STATIC = ROOT / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.exception_handler(Exception)
async def unhandled(request, exc):  # resposta amigável em JSON
    return JSONResponse(status_code=500, content={"error": str(exc)})
