"""Esquema unificado de entidades (o "contrato" entre todas as fontes).

Motivo: os quatro produtos que o MineraAI unifica (Virlo, Kalodata, DarkLAB e
ViralFindr) falam de coisas parecidas com nomes diferentes. Aqui existe UM
esquema por tipo de entidade, com `uid` estável — assim o mesmo vídeo coletado
pela API oficial, pela Virlo ou empurrado pela mineração é reconhecido como o
mesmo registro, e a UI nunca precisa saber de onde o dado veio.

Tipos: video · creator · product · shop · live
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable, Optional

from . import metrics
from .providers import normalize_video as _normalize_video_provider

SCHEMA_VERSION = metrics.SCHEMA_VERSION

KINDS = ("video", "creator", "product", "shop", "live")

# Quanto maior, mais confiável — define quem vence quando há conflito de campos
SOURCE_RANK = {"oficial": 4, "api": 3, "coleta": 3, "n8n": 2, "demo": 1, "estimado": 1}

PREFIX = {"video": "vid", "creator": "cr", "product": "prod", "shop": "shop", "live": "live"}


# ------------------------------------------------------------------ identidade
def uid(kind: str, platform: str, native_id: str) -> str:
    """Identificador global estável: `vid:tiktok:7231...`."""
    prefix = PREFIX.get(kind, kind)
    return f"{prefix}:{(platform or 'multi').lower()}:{native_id}"


def hash_uid(kind: str, *parts: str) -> str:
    """UID determinístico quando a fonte não fornece id nativo."""
    raw = "|".join(str(p).lower().strip() for p in parts if p)
    return f"{PREFIX.get(kind, kind)}:h:{hashlib.md5(raw.encode()).hexdigest()[:12]}"


def _preserve(out: dict, raw: dict) -> dict:
    """Campos extras da fonte (catálogo, contatos, thumbs…) não são descartados."""
    for k, v in raw.items():
        out.setdefault(k, v)
    return out


def _base(kind: str, entity: dict, platform: str, source: str) -> dict:
    out = dict(entity)
    out["kind"] = kind
    out["schema_version"] = SCHEMA_VERSION
    out["platform"] = platform or entity.get("platform") or "multi"
    out["source"] = source or entity.get("source") or "demo"
    out["uid"] = entity.get("uid") or out["id"]
    return out


# ------------------------------------------------------------------ normalizadores
def normalize_video(raw: dict, platform: str) -> dict:
    """Vídeo: herda a normalização do conector e ganha uid global (idempotente)."""
    if raw.get("kind") == "video" and raw.get("uid"):
        return raw
    # some fontes devolvem o id já prefixado pela plataforma ("youtube-123")
    native = re.sub(rf"^{re.escape(str(platform))}-", "", str(raw.get("id") or ""))
    v = _normalize_video_provider({**raw, "id": native}, platform)
    v = _base("video", v, platform, v.get("source", "api"))
    v["uid"] = uid("video", platform, native or v["id"])
    return v


def normalize_creator(raw: dict) -> dict:
    handle = (raw.get("handle") or raw.get("author") or "desconhecido").lower()
    platform = raw.get("platform") or "multi"
    out = {
        "id": raw.get("id") or hash_uid("creator", platform, handle),
        "handle": handle if handle.startswith("@") else f"@{handle.lstrip('@')}",
        "platform": platform,
        "niche": raw.get("niche", ""),
        "followers": int(raw.get("followers") or 0),
        "engagement_rate": float(raw.get("engagement_rate") or 0),
        "videos_30d": int(raw.get("videos_30d") or 0),
        "gmv_est": int(raw.get("gmv_est") or 0),
        "gmv_range": raw.get("gmv_range"),
        "top_product": raw.get("top_product", ""),
        "verified": bool(raw.get("verified")),
        "contact": raw.get("contact"),
        "source": raw.get("source", "demo"),
    }
    out = _base("creator", _preserve(out, raw), platform, out["source"])
    out["uid"] = uid("creator", platform, out["id"])
    return out


def normalize_product(raw: dict) -> dict:
    platform = raw.get("platform") or "tiktok_shop"
    price = float(raw.get("price") or 0)
    units = int(raw.get("units") or 0)
    est = raw.get("gmv_range")
    if not est and units and price:
        est = metrics.gmv_estimate(units, price, raw.get("confidence", "media"))
    out = {
        "id": raw.get("id") or hash_uid("product", raw.get("name", "")),
        "name": raw.get("name", ""),
        "category": raw.get("category", ""),
        "price": price,
        "units": units,
        "gmv": int(raw.get("gmv") or (est or {}).get("gmv") or 0),
        "gmv_range": est,
        "growth": float(raw.get("growth") or 0),
        "curve": raw.get("curve") or [],
        "trend_score": raw.get("trend_score") or metrics.trend_score(raw.get("curve") or []),
        "momentum": raw.get("momentum") or metrics.momentum(raw.get("curve") or []),
        "creators_promoting": int(raw.get("creators_promoting") or 0),
        "shops": int(raw.get("shops") or 0),
        "rating": float(raw.get("rating") or 0),
        "commission": float(raw.get("commission") or 0),
        "source": raw.get("source", "demo"),
        "platform": platform,
    }
    out = _base("product", _preserve(out, raw), platform, out["source"])
    out["uid"] = uid("product", platform, out["id"])
    return out


def normalize_shop(raw: dict) -> dict:
    platform = raw.get("platform") or "tiktok_shop"
    out = {
        "id": raw.get("id") or hash_uid("shop", raw.get("name", "")),
        "name": raw.get("name", ""),
        "category": raw.get("category", ""),
        "products": int(raw.get("products") or 0),
        "units": int(raw.get("units") or 0),
        "gmv": int(raw.get("gmv") or 0),
        "gmv_range": raw.get("gmv_range"),
        "growth": float(raw.get("growth") or 0),
        "rating": float(raw.get("rating") or 0),
        "creators_affiliated": int(raw.get("creators_affiliated") or 0),
        "live_share": float(raw.get("live_share") or 0),
        "curve": raw.get("curve") or [],
        "source": raw.get("source", "demo"),
        "platform": platform,
    }
    out = _base("shop", _preserve(out, raw), platform, out["source"])
    out["uid"] = uid("shop", platform, out["id"])
    return out


def normalize_live(raw: dict) -> dict:
    platform = raw.get("platform") or "tiktok"
    est = raw.get("gmv_range")
    if not est and raw.get("units") and raw.get("price"):
        est = metrics.gmv_estimate(int(raw["units"]), float(raw["price"]), "baixa")
    out = {
        "id": raw.get("id") or hash_uid("live", platform, raw.get("host", "")),
        "host": raw.get("host", ""),
        "platform": platform,
        "product": raw.get("product", ""),
        "viewers_peak": int(raw.get("viewers_peak") or 0),
        "units": int(raw.get("units") or 0),
        "gmv": int(raw.get("gmv") or (est or {}).get("gmv") or 0),
        "gmv_range": est,
        "started_min_ago": int(raw.get("started_min_ago") or 0),
        "live_now": bool(raw.get("live_now")),
        "source": raw.get("source", "demo"),
    }
    out = _base("live", _preserve(out, raw), platform, out["source"])
    out["uid"] = uid("live", platform, out["id"])
    return out


# ------------------------------------------------------------------ merge / dedupe
def source_rank(source: str) -> int:
    return SOURCE_RANK.get((source or "").lower(), 0)


def merge(a: dict, b: dict) -> dict:
    """Mescla duas versões da mesma entidade, campo a campo.

    O vencedor é a fonte mais confiável (oficial > coleta > n8n > demo), mas
    nenhum campo preenchido é perdido: só sobrescreve quando o perdedor traz
    valor e o vencedor está vazio.
    """
    win, lose = (a, b) if source_rank(a.get("source")) >= source_rank(b.get("source")) else (b, a)
    out = dict(win)
    for k, v in lose.items():
        if out.get(k) in (None, "", 0, [], {}) and v not in (None, "", [], {}):
            out[k] = v
    return out


def dedupe(items: Iterable[dict], key_fields: tuple[str, ...] = ("uid",)) -> list[dict]:
    """Remove duplicatas mantendo a melhor versão de cada entidade."""
    index: dict[str, dict] = {}
    order: list[str] = []
    for item in items:
        key = "|".join(str(item.get(f, "")) for f in key_fields) or str(item.get("id"))
        if key in index:
            index[key] = merge(index[key], item)
        else:
            index[key] = item
            order.append(key)
    return [index[k] for k in order]


def sort_by(items: Iterable[dict], field: str, reverse: bool = True) -> list[dict]:
    return sorted(items, key=lambda x: x.get(field) or 0, reverse=reverse)


# ------------------------------------------------------------------ validação leve
def validate(entity: dict) -> tuple[bool, list[str]]:
    """Sanidade mínima antes de persistir/entregar (não é um validador de schema)."""
    errors = []
    if entity.get("kind") not in KINDS:
        errors.append(f"kind inválido: {entity.get('kind')!r}")
    if not entity.get("uid"):
        errors.append("uid ausente")
    if entity.get("kind") == "video":
        if int(entity.get("views") or 0) < 0:
            errors.append("views negativas")
        if not entity.get("title") and not entity.get("url"):
            errors.append("vídeo sem título e sem url")
    return (not errors), errors


def to_unified(raw: dict, kind: str, platform: Optional[str] = None) -> dict:
    """Dispatcher único: qualquer dict bruto → entidade unificada."""
    kind = kind.lower()
    if kind == "video":
        return normalize_video(raw, platform or raw.get("platform") or "tiktok")
    if kind == "creator":
        return normalize_creator({**raw, "platform": platform or raw.get("platform")})
    if kind == "product":
        return normalize_product(raw)
    if kind == "shop":
        return normalize_shop(raw)
    if kind == "live":
        return normalize_live(raw)
    raise ValueError(f"kind desconhecido: {kind}")
