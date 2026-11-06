"""Armazenamento simples em JSON para biblioteca e configurações."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

_lock = threading.Lock()


def _read(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write(path: Path, content) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------- biblioteca
LIBRARY_FILE = DATA_DIR / "library.json"


def library_list() -> list[dict]:
    with _lock:
        return _read(LIBRARY_FILE, [])


def library_add(item: dict) -> dict:
    item = dict(item)
    item.setdefault("id", f"lib-{int(time.time() * 1000)}")
    item["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _lock:
        items = _read(LIBRARY_FILE, [])
        # evita duplicatas pelo mesmo conteúdo de origem
        key = item.get("ref") or item.get("title")
        if key and any((i.get("ref") or i.get("title")) == key for i in items):
            return next(i for i in items if (i.get("ref") or i.get("title")) == key)
        items.insert(0, item)
        _write(LIBRARY_FILE, items)
    return item


def library_remove(item_id: str) -> bool:
    with _lock:
        items = _read(LIBRARY_FILE, [])
        kept = [i for i in items if i.get("id") != item_id]
        if len(kept) == len(items):
            return False
        _write(LIBRARY_FILE, kept)
    return True


# ------------------------------------------------------------------ settings
SETTINGS_FILE = DATA_DIR / "settings.json"

ENV_KEYS = [
    # ---- plataformas oficiais
    "YOUTUBE_API_KEY",
    # OAuth do CANAL (upload) — separado da API key de leitura
    "YOUTUBE_CLIENT_ID",
    "YOUTUBE_CLIENT_SECRET",
    "YOUTUBE_REDIRECT_URI",
    "YOUTUBE_ACCESS_TOKEN",
    "YOUTUBE_REFRESH_TOKEN",
    "YOUTUBE_TOKEN_EXPIRES_AT",
    "YOUTUBE_CHANNEL_ID",
    "YOUTUBE_CHANNEL_TITLE",
    "TIKTOK_CLIENT_KEY",
    "TIKTOK_CLIENT_SECRET",
    "IG_ACCESS_TOKEN",
    "IG_USER_ID",
    # ---- IA (OpenAI e Gemini SEPARADOS)
    "AI_PROVIDER",              # openai | gemini | internal
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    # ---- dados pagos: Virlo API (Orbit / Comet / Satellite)
    "VIRLO_API_KEY",
    "VIRLO_BASE_URL",
    "VIRLO_AUTO_USE",           # 1 = usa Virlo como fonte no Radar
    # ---- fonte gratuita: Reddit (OAuth client_credentials)
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT",
    "REDDIT_DEFAULT_SUB",
    # ---- fonte gratuita: Mercado Livre (OAuth authorization_code)
    "MELI_CLIENT_ID",
    "MELI_CLIENT_SECRET",
    "MELI_REDIRECT_URI",
    "MELI_SITE_ID",
    "MELI_ACCESS_TOKEN",
    "MELI_REFRESH_TOKEN",
    "MELI_TOKEN_EXPIRES_AT",
    # ---- fonte gratuita: Google Suggest (+ CSE opcional)
    "GOOGLE_SUGGEST_HL",
    "GOOGLE_SUGGEST_GL",
    "GOOGLE_CSE_API_KEY",
    "GOOGLE_CSE_CX",
    # ---- fonte gratuita: oEmbed
    "OEMBED_TIMEOUT",
    "OEMBED_PROXY",
    # ---- fonte gratuita: Google Trends
    "TRENDS_GEO",
    "TRENDS_LANGUAGE",
    # ---- fonte gratuita: Pexels
    "PEXELS_API_KEY",
    # ---- produção direta: RunPod serverless (ComfyUI)
    "RUNPOD_API_KEY",
    "RUNPOD_ENDPOINT_ID",
    "RUNPOD_BASE_URL",
    "RUNPOD_TIMEOUT",
    "RUNPOD_WORKFLOW_TEMPLATE",
    "RUNPOD_GPU_PRICE_HORA",    # US$/hora da GPU, para estimar custo
    # ---- mídia e retenção (disco)
    "MEDIA_MAX_MB",             # teto por arquivo baixado do worker (0 = não baixa)
    "RETENTION_ENABLED",        # 1 = poda automática ligada
    "RETENTION_DIAS",           # janela de retenção dos JSONs
    "RETENTION_INTERVALO_H",    # de quanto em quanto tempo a poda roda
    # ---- publicação e realimentação
    "PUBLISH_SYNC",             # 1 = mede as publicações em background
    "PUBLISH_JANELA_DIAS",      # por quantos dias continua medindo cada vídeo
    "PUBLISH_SYNC_INTERVALO_H", # intervalo entre leituras de métricas
]

# Chaves sensíveis (mascaradas na leitura pública)
SECRET_KEYS = {k for k in ENV_KEYS if any(t in k for t in
               ("KEY", "SECRET", "TOKEN", "PASSWORD"))}



def settings_get() -> dict:
    """Mescla: valor salvo em disco > variável de ambiente > vazio."""
    with _lock:
        saved = _read(SETTINGS_FILE, {})
    out = {}
    for k in ENV_KEYS:
        v = saved.get(k)
        if v in (None, ""):
            v = os.environ.get(k, "")
        out[k] = v
    return out


def settings_save(patch: dict) -> dict:
    with _lock:
        saved = _read(SETTINGS_FILE, {})
        for k, v in (patch or {}).items():
            if k in ENV_KEYS:
                saved[k] = (v or "").strip()
        _write(SETTINGS_FILE, saved)
    return settings_get()


def is_secret(name: str) -> bool:
    return name in SECRET_KEYS


def secret_mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•••"
    return value[:4] + "••••" + value[-4:]
