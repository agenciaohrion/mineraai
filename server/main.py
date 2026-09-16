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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import ai_engine, data as demo, providers, storage

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
    videos = list(demo_set["videos"])
    official = []

    # APIs oficiais (quando conectadas) entram na frente
    jobs = []
    if "youtube" in plats and provider_status()["youtube"]["conectado"]:
        jobs.append(providers.youtube_search(q, max_results=limit,
                                             order="viewCount"))
    if "tiktok" in plats and provider_status()["tiktok"]["conectado"]:
        jobs.append(providers.tiktok_search(q, max_results=limit))
    if "instagram" in plats and provider_status()["instagram"]["conectado"]:
        jobs.append(providers.instagram_hashtag_search(q, max_results=limit))
    if jobs:
        results = await asyncio.gather(*jobs, return_exceptions=True)
        for res in results:
            if isinstance(res, list):
                official += res

    if official:
        videos = official + videos
    if min_views:
        videos = [v for v in videos if v["views"] >= min_views]

    sort_key = {"viral_score": "viral_score", "views": "views", "likes": "likes",
                "engagement": "engagement", "recent": "age_hours"}.get(sort, "viral_score")
    videos.sort(key=lambda v: v[sort_key], reverse=(sort != "recent"))

    return {
        "query": q, "period": period, "sort": sort,
        "source_breakdown": {
            "oficial": sum(1 for v in videos if v["source"] == "oficial"),
            "demo": sum(1 for v in videos if v["source"] == "demo"),
        },
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
    return {"products": items, "total_gmv": total_gmv,
            "categories": list(demo.NICHOS.keys()),
            "note": "Estimativas baseadas em modelo público de GMV (views × conversão × ticket)."}


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
    return await ai_engine.analyze_video(body.subject)


@app.post("/api/ai/narration")
async def ai_narration(body: NarrationIn):
    tone = body.tone if body.tone in {"suspense", "energetico", "documental",
                                      "jornalistico"} else "suspense"
    return ai_engine.prepare_narration(body.text, tone)


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
