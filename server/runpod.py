"""Cliente DIRETO do RunPod serverless (ComfyUI) — sem n8n no meio.

Antes: MineraAI → webhook n8n → n8n monta o payload → ComfyUI no RunPod → callback.
Agora: MineraAI → `api.runpod.ai/v2/{endpoint}` direto. Uma chamada HTTP, sem
intermediário, sem `PUBLIC_URL` para callback, sem workflow de terceiro para
manter.

Endpoints oficiais usados (RunPod Serverless API v2):

  POST /v2/{endpoint_id}/runsync      aguarda e devolve o resultado (≤ ~5 min)
  POST /v2/{endpoint_id}/run          enfileira e devolve job id (para vídeo longo)
  GET  /v2/{endpoint_id}/status/{id}  IN_QUEUE | IN_PROGRESS | COMPLETED | FAILED
  POST /v2/{endpoint_id}/cancel/{id}  cancela
  GET  /v2/{endpoint_id}/health       workers prontos / fila

Autenticação: `Authorization: Bearer {RUNPOD_API_KEY}`.
Payload: `{"input": {"workflow": {...grafo ComfyUI API...}, "images": [...]}}`.
Saída: `output.message` (URL S3) ou base64 — normalizada em `extract_outputs()`.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import httpx

from . import storage

TIMEOUT_PADRAO = 120.0
POLL_INTERVALO = 2.0
POLL_MAX_SEGUNDOS = 900           # 15 min — teto para vídeo longo


class RunPodError(RuntimeError):
    """Falha de comunicação/execução no RunPod, com diagnóstico legível."""

    def __init__(self, message: str, status: Optional[int] = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


# ------------------------------------------------------------------ config
def _cfg() -> dict:
    return storage.settings_get()


def configured() -> bool:
    cfg = _cfg()
    return bool(cfg.get("RUNPOD_API_KEY") and cfg.get("RUNPOD_ENDPOINT_ID"))


def _base() -> str:
    cfg = _cfg()
    base = (cfg.get("RUNPOD_BASE_URL") or "https://api.runpod.ai/v2").rstrip("/")
    return f"{base}/{cfg.get('RUNPOD_ENDPOINT_ID', '').strip()}"


def _timeout() -> float:
    try:
        return float(_cfg().get("RUNPOD_TIMEOUT") or TIMEOUT_PADRAO)
    except (TypeError, ValueError):
        return TIMEOUT_PADRAO


def gpu_price_hora() -> float:
    try:
        return float(_cfg().get("RUNPOD_GPU_PRICE_HORA") or 0.44)
    except (TypeError, ValueError):
        return 0.44


def status_resumo() -> dict:
    """Estado para a UI (sem chamar a rede)."""
    cfg = _cfg()
    return {
        "oficial": "RunPod Serverless (ComfyUI direto)",
        "conectado": configured(),
        "endpoint_id": cfg.get("RUNPOD_ENDPOINT_ID", ""),
        "custo": f"US$ {gpu_price_hora():.2f}/h de GPU · cobrado por segundo de execução",
    }


# ------------------------------------------------------------------ HTTP
async def _request(method: str, path: str, payload: Optional[dict] = None,
                   timeout: Optional[float] = None) -> dict:
    if not configured():
        raise RunPodError("RunPod não configurado: informe API key e endpoint id")
    cfg = _cfg()
    url = _base() + path
    headers = {
        "Authorization": f"Bearer {cfg.get('RUNPOD_API_KEY', '')}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout or _timeout()) as client:
            resp = await client.request(method, url, headers=headers, json=payload)
    except httpx.TimeoutException:
        raise RunPodError("Tempo esgotado falando com o RunPod")
    except httpx.HTTPError as exc:
        raise RunPodError(f"Falha de rede com o RunPod: {type(exc).__name__}")

    if resp.status_code == 401:
        raise RunPodError("API key do RunPod inválida (HTTP 401)", 401)
    if resp.status_code == 404:
        raise RunPodError("Endpoint não encontrado — confira o endpoint id (HTTP 404)", 404)
    if resp.status_code == 429:
        raise RunPodError("RunPod limitou a requisição (HTTP 429) — tente novamente", 429)
    if resp.status_code >= 400:
        raise RunPodError(f"RunPod respondeu HTTP {resp.status_code}",
                          resp.status_code, resp.text[:300])
    try:
        return resp.json()
    except ValueError:
        raise RunPodError("RunPod devolveu uma resposta que não é JSON")


async def health() -> dict:
    """`/health` — mostra workers prontos, em execução e na fila."""
    data = await _request("GET", "/health")
    return {
        "ok": True,
        "workers": {
            "prontos": data.get("workers", {}).get("ready", 0),
            "ociosos": data.get("workers", {}).get("idle", 0),
            "executando": data.get("workers", {}).get("running", 0),
            "iniciais": data.get("workers", {}).get("initializing", 0),
        },
        "fila": {
            "em_execucao": data.get("jobs", {}).get("inProgress", 0),
            "na_fila": data.get("jobs", {}).get("inQueue", 0),
        },
        "raw": data,
    }


async def submit(payload: dict, mode: str = "sync") -> dict:
    """Envia um job. `sync` espera o resultado; `async` devolve o id para polling."""
    if mode == "async":
        data = await _request("POST", "/run", payload)
        return {"mode": "async", "runpod_job_id": data.get("id"),
                "status": data.get("status", "IN_QUEUE"), "raw": data}
    data = await _request("POST", "/runsync", payload, timeout=max(_timeout(), 300))
    return {"mode": "sync", "runpod_job_id": data.get("id"),
            "status": data.get("status"), "raw": data}


async def get_status(job_id: str) -> dict:
    return await _request("GET", f"/status/{job_id}")


async def cancel(job_id: str) -> dict:
    return await _request("POST", f"/cancel/{job_id}")


async def poll(job_id: str, intervalo: float = POLL_INTERVALO,
               max_segundos: float = POLL_MAX_SEGUNDOS) -> dict:
    """Acompanha um job assíncrono até COMPLETED/FAILED ou estourar o teto."""
    inicio = time.time()
    while True:
        data = await get_status(job_id)
        state = data.get("status")
        if state in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            return data
        if time.time() - inicio > max_segundos:
            raise RunPodError(f"Job {job_id} não terminou em {int(max_segundos)}s "
                              f"(estado atual: {state})")
        import asyncio
        await asyncio.sleep(intervalo)


# ------------------------------------------------------------------ workflows
ESTILOS = {
    "dark": "cinematic dark moody lighting, high contrast, dramatic shadows, film grain",
    "ugc": "authentic user generated content, handheld phone camera, natural light, slightly imperfect",
    "produto": "clean product shot, studio lighting, softbox, high detail, commercial photography",
    "cinematic": "cinematic composition, anamorphic lens, shallow depth of field, color graded",
}

# Grafo mínimo (SDXL txt2img) — usado quando não há template salvo
WORKFLOW_PADRAO = {
    "3": {"class_type": "KSampler",
          "inputs": {"seed": 1337, "steps": 28, "cfg": 7.0,
                     "sampler_name": "euler", "scheduler": "normal", "denoise": 1,
                     "model": ["4", 0], "positive": ["6", 0],
                     "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple",
          "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
    "5": {"class_type": "EmptyLatentImage",
          "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    "6": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "", "clip": ["4", 1]}},
    "7": {"class_type": "CLIPTextEncode",
          "inputs": {"text": "text, watermark, logo, deformed", "clip": ["4", 1]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage",
          "inputs": {"filename_prefix": "MineraAI", "images": ["8", 0]}},
}


def load_template() -> Optional[dict]:
    """Template ComfyUI salvo nas configurações (JSON exportado via 'Save (API)')."""
    raw = _cfg().get("RUNPOD_WORKFLOW_TEMPLATE", "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    # aceita tanto o grafo puro quanto {"workflow": {...}}
    if isinstance(data, dict) and "workflow" in data and isinstance(data["workflow"], dict):
        return data["workflow"]
    return data if isinstance(data, dict) and data else None


def apply_prompt(workflow: dict, prompt: str, negative: str = "",
                 seed: Optional[int] = None) -> dict:
    """Injeta prompt/negativo/seed no grafo, seja ele padrão ou template do usuário."""
    wf = json.loads(json.dumps(workflow))  # deep copy
    positivos = [k for k, v in wf.items()
                 if v.get("class_type") in ("CLIPTextEncode", "CLIPTextEncodeSDXL")
                 and isinstance(v.get("inputs", {}).get("text"), str)]
    if positivos:
        wf[positivos[0]]["inputs"]["text"] = prompt
        if len(positivos) > 1 and negative:
            wf[positivos[1]]["inputs"]["text"] = negative
    if seed is not None:
        for node in wf.values():
            if "seed" in node.get("inputs", {}):
                node["inputs"]["seed"] = int(seed)
    return wf


def build_input(prompt: str, negative: str = "", style: str = "dark",
                seed: Optional[int] = None, images: Optional[list] = None,
                template: Optional[dict] = None) -> dict:
    """Monta o `input` do RunPod a partir do estilo + template."""
    estilo = ESTILOS.get(style, ESTILOS["dark"])
    full_prompt = f"{prompt}, {estilo}" if prompt else estilo
    base = template or load_template() or WORKFLOW_PADRAO
    workflow = apply_prompt(base, full_prompt,
                            negative or "text, watermark, logo, deformed, low quality",
                            seed if seed is not None else int(time.time()) % 100000)
    payload: dict = {"input": {"workflow": workflow}}
    if images:
        payload["input"]["images"] = images
    return payload


def extract_outputs(result: dict) -> dict:
    """Normaliza a saída do worker (URL S3, base64, lista de arquivos)."""
    output = (result or {}).get("output") or {}
    mensagem = output.get("message") if isinstance(output, dict) else None
    urls: list[str] = []

    def coletar(valor):
        if isinstance(valor, str):
            if valor.startswith(("http://", "https://")):
                urls.append(valor)
        elif isinstance(valor, list):
            for v in valor:
                coletar(v)
        elif isinstance(valor, dict):
            for v in valor.values():
                coletar(v)

    coletar(mensagem)
    coletar(output.get("images"))
    return {
        "status": (result or {}).get("status"),
        "urls": urls,
        "mensagem_base64": mensagem if isinstance(mensagem, str)
                           and not mensagem.startswith(("http://", "https://")) else None,
        "delay_ms": (result or {}).get("delayTime"),
        "execution_ms": (result or {}).get("executionTime"),
        "erro": output.get("error") if isinstance(output, dict) else None,
        "raw": output,
    }


def estimate_cost(execution_ms: Optional[int], delay_ms: Optional[int] = None) -> dict:
    """Custo estimado em US$ (GPU/hora) — execução + fila fria (cold start)."""
    exec_s = (int(execution_ms or 0)) / 1000
    cold_s = (int(delay_ms or 0)) / 1000
    preco = gpu_price_hora() / 3600
    return {"execution_usd": round(exec_s * preco, 4),
            "cold_start_usd": round(cold_s * preco, 4),
            "total_usd": round((exec_s + cold_s) * preco, 4),
            "gpu_price_hora": gpu_price_hora()}
