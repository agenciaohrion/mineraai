"""Fábrica de Vídeos — jobs persistidos e disparo DIRETO no RunPod serverless.

O n8n saiu do caminho. O fluxo agora tem um salto só:

    MineraAI  ──HTTP──▶  api.runpod.ai/v2/{endpoint}  ──▶  ComfyUI (worker)

Duas modalidades:
  sync   → /runsync devolve o MP4 (ou a imagem) na própria requisição
  async  → /run devolve job id; `poll_job()` acompanha até COMPLETED

O job é persistido antes do disparo (se a chamada falhar, nada se perde) e o
custo é estimado por GPU-segundo a partir de `delayTime` + `executionTime`.

**O arquivo fica com a gente.** A URL que o RunPod devolve é do S3 deles e
expira; por isso, ao concluir, o vídeo é baixado para `data/media/<tenant>/` e o
job passa a apontar para um caminho local servido por
`GET /api/fabrica/jobs/{id}/file`. Se o download falhar, o job continua
"pronto" com a URL original e o motivo em `media_error` — a Fábrica não perde o
resultado por causa do armazenamento.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from . import media, runpod, storage
from .storage import DATA_DIR, _lock, _read, _write

JOBS_FILE = DATA_DIR / "jobs.json"
MAX_JOBS = 200


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ================================================================== jobs
def jobs_list() -> list[dict]:
    with _lock:
        return _read(JOBS_FILE, [])


def job_get(job_id: str) -> Optional[dict]:
    return next((j for j in jobs_list() if j["id"] == job_id), None)


def job_create(product: str, prompt: str, style: str, duration: int,
               extra: dict | None = None, tenant_id: str = "demo") -> dict:
    job = {
        "id": f"job-{uuid.uuid4().hex[:10]}",
        "tenant_id": tenant_id or "demo",
        "status": "fila",
        "product": product,
        "prompt": prompt,
        "style": style,
        "duration": duration,
        "extra": extra or {},
        "mode": "sync",
        "runpod_job_id": None,
        "created_at": _now(),
        "updated_at": _now(),
        "video_url": None,
        "thumb_url": None,
        "media": None,          # {"file", "bytes", "content_type", "origem"}
        "media_url": None,      # rota local que serve o arquivo
        "media_error": None,
        "cost_usd": None,
        "execution_ms": None,
        "delay_ms": None,
        "error": None,
    }
    with _lock:
        jobs = _read(JOBS_FILE, [])
        jobs.insert(0, job)
        _write(JOBS_FILE, jobs[:MAX_JOBS])
    return job


def job_update(job_id: str, patch: dict) -> Optional[dict]:
    with _lock:
        jobs = _read(JOBS_FILE, [])
        job = next((j for j in jobs if j["id"] == job_id), None)
        if not job:
            return None
        for k, v in patch.items():
            if v is not None:
                job[k] = v
        job["updated_at"] = _now()
        _write(JOBS_FILE, jobs)
        return dict(job)


def job_delete(job_id: str) -> bool:
    with _lock:
        jobs = _read(JOBS_FILE, [])
        kept = [j for j in jobs if j["id"] != job_id]
        if len(kept) == len(jobs):
            return False
        _write(JOBS_FILE, kept)
        return True


# ================================================================== dispatch
async def dispatch_to_runpod(job: dict, mode: str = "sync") -> dict:
    """Monta o payload ComfyUI e chama o RunPod direto.

    `mode="sync"` bloqueia até o resultado (bom para imagem/clipe curto).
    `mode="async"` devolve imediatamente e o job fica em `processando`.
    """
    if not runpod.configured():
        return job_update(job["id"], {
            "status": "erro",
            "error": "RunPod não configurado — informe API key e endpoint id "
                     "em APIs & Conexões.",
        }) or job

    payload = runpod.build_input(
        prompt=job["prompt"] or job["product"],
        style=job["style"],
        images=job.get("extra", {}).get("images"),
    )
    job_update(job["id"], {"status": "enviado", "mode": mode, "error": None})

    try:
        res = await runpod.submit(payload, mode=mode)
    except runpod.RunPodError as exc:
        return job_update(job["id"], {"status": "erro", "error": str(exc)}) or job

    if mode == "async":
        return job_update(job["id"], {
            "status": "processando",
            "runpod_job_id": res.get("runpod_job_id"),
        }) or job

    return await _apply_result(job["id"], res.get("raw") or {})


async def _guardar_midia(job: dict, out: dict) -> dict:
    """Traz o resultado do worker para o disco local.

    Devolve o patch a aplicar no job. Nunca levanta: se o armazenamento falhar,
    o job mantém a URL do worker e o motivo vai em `media_error`.
    """
    tenant = job.get("tenant_id") or "demo"
    job_id = job["id"]
    urls = out.get("urls") or []
    try:
        if urls:
            info = await media.save_from_url(urls[0], tenant, job_id)
        else:
            info = media.save_base64(out.get("mensagem_base64") or "", tenant, job_id)
    except media.MediaError as exc:
        return {"media_error": str(exc)}
    except Exception as exc:                      # disco cheio, permissão, etc.
        return {"media_error": f"falha ao salvar mídia: {exc}"}

    patch = {
        "media": info,
        "media_url": f"/api/fabrica/jobs/{job_id}/file",
        "media_error": None,
    }
    # o arquivo entra na Biblioteca com o mesmo `ref` do job (sem duplicar)
    storage.library_add({
        "kind": "video" if media.is_video(info["ext"]) else "imagem",
        "ref": f"job:{job_id}",
        "title": f"{job.get('product') or 'Sem título'} — {job_id}",
        "payload": {
            "job_id": job_id,
            "file": info["file"],
            "bytes": info["bytes"],
            "url": patch["media_url"],
            "prompt": (job.get("prompt") or "")[:300],
            "style": job.get("style"),
            "origem": info["origem"],
        },
    })
    return patch


async def _apply_result(job_id: str, raw: dict) -> dict:
    """Traduz a resposta do worker em campos do job (arquivo, custo, erro)."""
    out = runpod.extract_outputs(raw)
    custo = runpod.estimate_cost(out.get("execution_ms"), out.get("delay_ms"))
    urls = out.get("urls") or []

    if out.get("status") == "COMPLETED" and (urls or out.get("mensagem_base64")):
        patch = {
            "status": "pronto",
            "video_url": urls[0] if urls else None,
            "cost_usd": custo["total_usd"],
            "execution_ms": out.get("execution_ms"),
            "delay_ms": out.get("delay_ms"),
            "outputs": urls,
            "error": None,
        }
        job = job_get(job_id) or {"id": job_id, "tenant_id": "demo", "product": ""}
        patch.update(await _guardar_midia(job, out))
    else:
        patch = {
            "status": "erro",
            "error": out.get("erro") or f"Worker terminou com status {out.get('status')}",
            "execution_ms": out.get("execution_ms"),
            "delay_ms": out.get("delay_ms"),
            "cost_usd": custo["total_usd"],
        }
    return job_update(job_id, patch) or {}


def job_media_file(job_id: str, tenant_id: str) -> dict | None:
    """Metadados do arquivo do job, com checagem de dono.

    Job sem `tenant_id` é legado (anterior ao multi-tenant na Fábrica) e
    pertence ao workspace `demo`.
    """
    job = job_get(job_id)
    if not job:
        return None
    dono = job.get("tenant_id") or "demo"
    if dono != (tenant_id or "demo"):
        raise PermissionError("Este job pertence a outro workspace")
    rel = (job.get("media") or {}).get("file")
    return media.info_arquivo(rel) if rel else None


async def poll_job(job_id: str) -> dict:
    """Atualiza um job assíncrono consultando o RunPod (uma vez, sob demanda)."""
    job = job_get(job_id)
    if not job:
        raise ValueError("Job não encontrado")
    runpod_id = job.get("runpod_job_id")
    if not runpod_id:
        return job
    raw = await runpod.get_status(runpod_id)
    estado = raw.get("status")
    if estado in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
        return await _apply_result(job_id, raw)
    return job_update(job_id, {"status": "processando"}) or job


async def wait_job(job_id: str) -> dict:
    """Acompanha até o fim (usado por scripts/testes; a UI usa poll sob demanda)."""
    job = job_get(job_id)
    if not job or not job.get("runpod_job_id"):
        return job or {}
    raw = await runpod.poll(job["runpod_job_id"])
    return await _apply_result(job_id, raw)


async def cancel_job(job_id: str) -> dict:
    job = job_get(job_id)
    if not job:
        raise ValueError("Job não encontrado")
    if job.get("runpod_job_id"):
        try:
            await runpod.cancel(job["runpod_job_id"])
        except runpod.RunPodError:
            pass
    return job_update(job_id, {"status": "cancelado"}) or job
