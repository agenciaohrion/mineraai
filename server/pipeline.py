"""Pipeline de produção de vídeos + ingestão de minerações (n8n / RunPod).

Fluxos suportados:
  1. Fábrica de Vídeos: MineraAI cria um job → dispara webhook do n8n →
     n8n orquestra o ComfyUI no RunPod → devolve o MP4 por callback.
  2. Mineração automática: n8n (ou o próprio MineraAI) dispara coletas por
     palavra-chave; os resultados ficam persistidos e entram no Radar Viral.
  3. Ingestão livre: qualquer workflow n8n pode empurrar vídeos minerados
     de qualquer fonte via /api/ingest/videos (selo "n8n" no Radar).
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

import httpx

from . import storage
from .storage import DATA_DIR, _read, _write, _lock

JOBS_FILE = DATA_DIR / "jobs.json"
MINED_FILE = DATA_DIR / "mined.json"
INGEST_FILE = DATA_DIR / "ingested.json"

MINED_TTL_DAYS = 7


# ================================================================== jobs
def jobs_list() -> list[dict]:
    with _lock:
        return _read(JOBS_FILE, [])


def job_get(job_id: str) -> Optional[dict]:
    return next((j for j in jobs_list() if j["id"] == job_id), None)


def job_create(product: str, prompt: str, style: str, duration: int,
               extra: dict | None = None, tipo: str = "video",
               roteiro: dict | None = None, prompts: list | None = None) -> dict:
    tipo = tipo if tipo in ("imagem", "video", "misto") else "video"
    job = {
        "id": f"job-{uuid.uuid4().hex[:10]}",
        "status": "fila",
        "tipo": tipo,  # imagem | video | misto
        "product": product,
        "prompt": prompt,
        "style": style,
        "duration": duration,
        "roteiro": roteiro or {},  # {hook, cenas: [{nome, descricao, prompt, duracao}], narracao}
        "prompts": prompts or [],  # lista de prompts extras para imagens
        "extra": extra or {},
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "video_url": None,
        "images": [],  # [{url, prompt, cena, thumb}]
        "thumb_url": None,
        "cost_usd": None,
        "error": None,
    }
    with _lock:
        jobs = _read(JOBS_FILE, [])
        jobs.insert(0, job)
        _write(JOBS_FILE, jobs[:200])
    return job


def job_update(job_id: str, patch: dict) -> Optional[dict]:
    with _lock:
        jobs = _read(JOBS_FILE, [])
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            return None
        for k in ("status", "video_url", "thumb_url", "cost_usd", "error", "images", "tipo", "roteiro", "prompts"):
            if k in patch:
                job[k] = patch[k]
        job["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _write(JOBS_FILE, jobs)
        return dict(job)


def job_update_tipo(job_id: str, tipo: str):
    return job_update(job_id, {"tipo": tipo})


def job_delete(job_id: str) -> bool:
    with _lock:
        jobs = _read(JOBS_FILE, [])
        kept = [j for j in jobs if j["id"] != job_id]
        if len(kept) == len(jobs):
            return False
        _write(JOBS_FILE, kept)
        return True


async def dispatch_to_n8n(job: dict) -> dict:
    """Envia o job para o webhook do n8n. Retorna o estado atualizado."""
    cfg = storage.settings_get()
    url = cfg.get("N8N_WEBHOOK_URL", "")
    if not url:
        return job_update(job["id"], {"status": "fila",
                                      "error": "Webhook do n8n não configurado "
                                               "(aba APIs & Conexões)."})
    public_url = cfg.get("MINERAAI_PUBLIC_URL", "") or "http://localhost:8000"
    payload = {
        "job_id": job["id"],
        "tipo": job.get("tipo", "video"),
        "product": job["product"],
        "prompt": job["prompt"],
        "style": job["style"],
        "duration": job["duration"],
        "roteiro": job.get("roteiro", {}),
        "prompts": job.get("prompts", []),
        "extra": job["extra"],
        "token": cfg.get("N8N_TOKEN", ""),
        "callback_url": f"{public_url.rstrip('/')}/api/fabrica/jobs/{job['id']}/result",
    }
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        return job_update(job["id"], {"status": "enviado", "error": None})
    except Exception as e:
        return job_update(job["id"], {"status": "erro",
                                      "error": f"Falha ao chamar o n8n: {type(e).__name__}: "
                                               f"{str(e)[:120]}"})


def check_token(provided: str) -> bool:
    """Validação simples de token do callback (opcional)."""
    expected = storage.settings_get().get("N8N_TOKEN", "")
    if not expected:
        return True  # token não configurado = sem verificação
    return provided == expected


# ================================================================== mineração persistida
def mined_save(query: str, videos: list[dict], errors: list[str]) -> dict:
    with _lock:
        store = _read(MINED_FILE, {})
        store[query.lower().strip()] = {
            "query": query,
            "collected_at": time.time(),
            "errors": errors,
            "videos": videos[:60],
        }
        # poda entradas velhas
        cutoff = time.time() - MINED_TTL_DAYS * 86400
        store = {k: v for k, v in store.items() if v["collected_at"] > cutoff}
        _write(MINED_FILE, store)
    return {"query": query, "videos": len(videos), "errors": errors}


def mined_for_query(q: str) -> list[dict]:
    """Vídeos minerados persistidos que casam com a busca atual."""
    ql = (q or "").lower().strip()
    if not ql:
        return []
    store = _read(MINED_FILE, {})
    cutoff = time.time() - MINED_TTL_DAYS * 86400
    out = []
    for key, entry in store.items():
        if entry["collected_at"] < cutoff:
            continue
        if key in ql or ql in key or any(w in ql for w in key.split() if len(w) > 3):
            for v in entry["videos"]:
                v = dict(v)
                v["source"] = "coleta"
                out.append(v)
    return out


def mined_summary() -> list[dict]:
    store = _read(MINED_FILE, {})
    cutoff = time.time() - MINED_TTL_DAYS * 86400
    return [{"query": v["query"], "videos": len(v["videos"]),
             "when": time.strftime("%d/%m %H:%M", time.localtime(v["collected_at"]))}
            for v in store.values() if v["collected_at"] > cutoff]


# ================================================================== ingestão n8n
def ingest_videos(items: list[dict], source_name: str = "n8n") -> int:
    """Aceita vídeos minerados por qualquer workflow (esquema flexível)."""
    from .providers import normalize_video
    cleaned = []
    for it in items:
        try:
            v = normalize_video({
                "id": it.get("id") or uuid.uuid4().hex[:8],
                "title": it.get("title", ""),
                "author": it.get("author", ""),
                "handle": it.get("handle", ""),
                "views": it.get("views", 0),
                "likes": it.get("likes", 0),
                "comments": it.get("comments", 0),
                "shares": it.get("shares", 0),
                "age_hours": it.get("age_hours", 24),
                "hashtags": it.get("hashtags") or [],
                "duration": it.get("duration"),
                "url": it.get("url", ""),
                "thumb": it.get("thumb"),
            }, it.get("platform", "tiktok"))
            v["source"] = "n8n"
            v["ingest_tag"] = (it.get("query") or source_name).lower()
            cleaned.append(v)
        except Exception:
            continue
    if not cleaned:
        return 0
    with _lock:
        store = _read(INGEST_FILE, [])
        store = [s for s in store
                 if s.get("_ts", 0) > time.time() - MINED_TTL_DAYS * 86400]
        for v in cleaned:
            v["_ts"] = time.time()
        store = cleaned + store
        _write(INGEST_FILE, store[:1500])
    return len(cleaned)


def ingested_for_query(q: str) -> list[dict]:
    ql = (q or "").lower().strip()
    store = _read(INGEST_FILE, [])
    cutoff = time.time() - MINED_TTL_DAYS * 86400
    out = []
    for v in store:
        if v.get("_ts", 0) < cutoff:
            continue
        tag = v.get("ingest_tag", "")
        if not ql or tag in ql or ql in tag or \
                any(w in ql for w in tag.split() if len(w) > 3) or \
                ql in (v.get("title") or "").lower():
            v2 = {k: val for k, val in v.items() if not k.startswith("_")}
            out.append(v2)
    return out
