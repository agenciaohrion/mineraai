"""MineraAI — Ecossistema completo de descoberta viral, inteligência de produtos
e criação de conteúdo com IA.

Funcionalidades inspiradas em ferramentas de pesquisa viral, analytics de
TikTok Shop e laboratórios de criação para canais dark — reconstruídas do zero
com design próprio e arquitetura de dados plugável (APIs oficiais + demo).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import (agents, ai_engine, credits, data as demo, free_sources, metrics,
               pipeline, providers, research, schema, scrapling_sources, storage)

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


@app.on_event("shutdown")
async def _shutdown() -> None:
    task = getattr(app.state, "agents_task", None)
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
                 tenant: dict = Depends(current_tenant)):
    """Radar Viral — busca unificada (oficial → coleta → n8n → demo)."""
    credits.charge(tenant["id"], "search", meta={"q": q, "platform": platform})
    limit = max(3, min(limit, 30))
    data = await research.search_videos(q, platform, period, min_views, limit)
    videos = research.sort_videos(data["videos"], sort)
    return {
        "query": q, "period": data["period"], "sort": sort,
        "source_breakdown": data["source_breakdown"],
        "coleta_errors": data["coleta_errors"],
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
    if q and scrapling_sources.coleta_enabled():
        try:
            ml = await asyncio.wait_for(
                asyncio.to_thread(free_sources.mercadolivre_search, q, 12), timeout=25)
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
    """Termos em alta agora no Brasil — Google Trends (RSS público, grátis)."""
    credits.charge(tenant["id"], "trends")
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


# ------------------------------------------------------------ Fábrica de Vídeos (n8n + RunPod/ComfyUI)
class JobIn(BaseModel):
    product: str = Field(..., min_length=2, max_length=160)
    prompt: str = Field("", max_length=2000)
    style: str = "dark"
    duration: int = 6


class JobResultIn(BaseModel):
    status: str = "pronto"          # pronto | erro | processando
    video_url: str = ""
    thumb_url: str = ""
    cost_usd: Optional[float] = None
    error: str = ""


class IngestIn(BaseModel):
    videos: list = []
    query: str = ""


class MiningRunIn(BaseModel):
    keywords: list = []


@app.post("/api/fabrica/jobs")
async def fabrica_create(body: JobIn, tenant: dict = Depends(current_tenant)):
    """Cria job de vídeo e dispara o webhook do n8n (que orquestra o ComfyUI)."""
    credits.charge(tenant["id"], "fabrica_job", meta={"product": body.product})
    job = pipeline.job_create(body.product, body.prompt, body.style,
                              max(2, min(body.duration, 60)))
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
    """Callback do n8n com o vídeo pronto (protegido por token opcional)."""
    if not pipeline.check_token(x_pipeline_token or ""):
        raise HTTPException(401, "Token inválido")
    status = body.status if body.status in {"pronto", "erro", "processando"} else "pronto"
    if body.video_url:
        status = "pronto"
    job = pipeline.job_update(job_id, {
        "status": status,
        "video_url": body.video_url or None,
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
async def fabrica_broll(q: str = "produto", tenant: dict = Depends(current_tenant)):
    """B-roll gratuito (Pexels) para enriquecer os vídeos da Fábrica."""
    credits.charge(tenant["id"], "broll")
    return await asyncio.to_thread(free_sources.pexels_broll, q, 10)


# ------------------------------------------------------------ mineração & ingestão (n8n)
@app.post("/api/mining/run")
async def mining_run(body: MiningRunIn, tenant: dict = Depends(current_tenant)):
    """Disparado pelo n8n (ou manualmente): minera palavras-chave com Scrapling
    e persiste os resultados, que entram no Radar Viral automaticamente."""
    kws = [k.strip() for k in (body.keywords or []) if k.strip()][:6]
    if not kws:
        raise HTTPException(400, "Informe ao menos uma palavra-chave")
    if not scrapling_sources.coleta_enabled():
        raise HTTPException(400, "Coleta Scrapling desativada")
    credits.charge(tenant["id"], "mining", units=len(kws), meta={"keywords": kws})
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
