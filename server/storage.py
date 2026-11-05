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
    "YOUTUBE_API_KEY",
    "TIKTOK_CLIENT_KEY",
    "TIKTOK_CLIENT_SECRET",
    "IG_ACCESS_TOKEN",
    "IG_USER_ID",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL",
    "SCRAPLING_ENABLED",
    "SCRAPLING_STEALTHY",
    "N8N_WEBHOOK_URL",
    "N8N_TOKEN",
    "MINERAAI_PUBLIC_URL",
    "PEXELS_API_KEY",
]


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


def secret_mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•••"
    return value[:4] + "••••" + value[-4:]
