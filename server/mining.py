"""Mineração própria — o modelo Orbit/Comet do Virlo, reconstruído.

Como o Virlo minera (e como fazemos o mesmo, sem depender do n8n):

  1. ORBIT — busca por palavra-chave em FILA, não em tempo real.
     POST cria o job com keywords + plataformas + min_views; um worker pega da
     fila, consulta as fontes, normaliza, deduplica, calcula outliers e grava o
     resultado. A consulta é assíncrona porque cada fonte tem limite de taxa:
     enfileirar é o que permite aguentar centenas de buscas sem estourar cota.

  2. COMET — o mesmo pipeline, mas AGENDADO por nicho.
     Uma configuração (keywords + plataformas + frequência) roda a cada ciclo e
     vai empilhando observações. É o que transforma "uma busca" em série
     temporal — a base para detectar tendência em vez de foto do momento.

  3. OUTLIER — em ambos, o valor não está no vídeo: está no desvio.
     views ÷ baseline do criador (mediana dos vídeos dele no corpus). É o que
     separa "vídeo grande" de "vídeo que furou a curva" — e é o sinal que o
     TikTok/Instagram não entrega no painel nativo.

Diferença de implementação: em vez de scraping proprietário, usamos fontes
legítimas — APIs oficiais (YouTube/TikTok/Instagram), a própria Virlo API quando
configurada e ingestão externa. O que é copiado é a ARQUITETURA (fila, agente,
agendamento, outlier), não o mecanismo de coleta deles.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from datetime import datetime, timezone
from typing import Optional

from . import metrics, pipeline, providers, schema, storage, virlo
from .storage import DATA_DIR, _lock, _read, _write

ORBITS_FILE = DATA_DIR / "orbits.json"
COMETS_FILE = DATA_DIR / "comets.json"
INGEST_FILE = DATA_DIR / "ingested.json"

MAX_ORBITS = 100
MAX_VIDEOS_POR_ORBIT = 400
PLATAFORMAS = ("tiktok", "instagram", "youtube")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ts() -> int:
    return int(time.time())


# ================================================================== ORBIT
def _orbits() -> list[dict]:
    data = _read(ORBITS_FILE, [])
    return data if isinstance(data, list) else []


def _save_orbits(orbits: list[dict]) -> None:
    _write(ORBITS_FILE, orbits[:MAX_ORBITS])


def orbit_create(tenant_id: str, name: str, keywords: list[str],
                 platforms: Optional[list[str]] = None, min_views: int = 0) -> dict:
    kws = [k.strip() for k in keywords if k and k.strip()][:12]
    if not kws:
        raise ValueError("Informe ao menos uma palavra-chave")
    plats = [p for p in (platforms or PLATAFORMAS) if p in PLATAFORMAS] or list(PLATAFORMAS)
    orbit = {
        "id": "orb_" + secrets.token_hex(6),
        "tenant": tenant_id,
        "name": (name or kws[0])[:120],
        "keywords": kws,
        "platforms": plats,
        "min_views": int(min_views),
        "status": "queued",
        "progress": 0,
        "created_at": _now(),
        "started_at": None,
        "finished_at": None,
        "videos": [],
        "report": None,
        "errors": [],
        "fontes": {},
    }
    with _lock:
        orbits = _orbits()
        orbits.insert(0, orbit)
        _save_orbits(orbits)
    return orbit


def orbit_list(tenant_id: str) -> list[dict]:
    return [{k: v for k, v in o.items() if k != "videos"}
            for o in _orbits() if o.get("tenant") == tenant_id]


def orbit_get(orbit_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
    for o in _orbits():
        if o.get("id") == orbit_id and (tenant_id is None or o.get("tenant") == tenant_id):
            return o
    return None


def _orbit_update(orbit_id: str, patch: dict) -> Optional[dict]:
    with _lock:
        orbits = _orbits()
        for o in orbits:
            if o.get("id") == orbit_id:
                o.update(patch)
                _save_orbits(orbits)
                return o
    return None


def orbit_videos(orbit_id: str, limit: int = 50, order_by: str = "outlier_score",
                 tenant_id: Optional[str] = None) -> list[dict]:
    orbit = orbit_get(orbit_id, tenant_id)
    if not orbit:
        return []
    videos = orbit.get("videos") or []
    campo = order_by if order_by in ("outlier_score", "views", "viral_score",
                                    "engagement", "age_hours") else "outlier_score"
    return sorted(videos, key=lambda v: v.get(campo) or 0,
                  reverse=(campo != "age_hours"))[:limit]


def orbit_outliers(orbit_id: str, limit: int = 20,
                   tenant_id: Optional[str] = None) -> list[dict]:
    videos = orbit_videos(orbit_id, 200, "outlier_score", tenant_id)
    return [v for v in videos if (v.get("outlier_score") or 0) >= 30][:limit]


async def _coletar_keyword(keyword: str, platforms: list[str],
                           min_views: int) -> tuple[list[dict], list[str], dict]:
    """Consulta oficial + Virlo para UMA palavra-chave. Nunca levanta exceção."""
    coletados: list[dict] = []
    erros: list[str] = []
    fontes = {"oficial": 0, "virlo": 0}

    if "youtube" in platforms and providers.storage.settings_get().get("YOUTUBE_API_KEY"):
        try:
            vids = await providers.youtube_search(keyword, max_results=25, order="viewCount")
            coletados += vids
            fontes["oficial"] += len(vids)
        except Exception as exc:
            erros.append(f"youtube: {type(exc).__name__}")

    if virlo.configured():
        try:
            res = await virlo.collect(keyword, "all", 25)
            coletados += res["videos"]
            fontes["virlo"] += len(res["videos"])
            erros += res.get("erros", [])
        except Exception as exc:
            erros.append(f"virlo: {type(exc).__name__}")

    if min_views:
        coletados = [v for v in coletados if int(v.get("views") or 0) >= min_views]
    return coletados, erros, fontes


async def orbit_run(orbit_id: str, tenant_id: Optional[str] = None) -> dict:
    """Executa o job: coleta todas as keywords, normaliza, pontua e grava."""
    orbit = orbit_get(orbit_id, tenant_id)
    if not orbit:
        raise ValueError("Orbit não encontrado")
    if orbit.get("status") == "running":
        return orbit

    _orbit_update(orbit_id, {"status": "running", "started_at": _now(), "progress": 0})
    todos: list[dict] = []
    erros: list[str] = []
    fontes_total = {"oficial": 0, "virlo": 0}
    total_kw = max(1, len(orbit["keywords"]))

    for i, kw in enumerate(orbit["keywords"], start=1):
        try:
            vids, errs, fontes = await _coletar_keyword(kw, orbit["platforms"],
                                                        orbit.get("min_views", 0))
            for v in vids:
                v["_keyword"] = kw
            todos += vids
            erros += errs
            for k, n in fontes.items():
                fontes_total[k] = fontes_total.get(k, 0) + n
        except Exception as exc:
            erros.append(f"{kw}: {type(exc).__name__}")
        _orbit_update(orbit_id, {"progress": int(100 * i / total_kw)})

    # normaliza → deduplica → métricas
    unificados = [v if v.get("uid") else schema.normalize_video(v, v.get("platform", "tiktok"))
                  for v in todos]
    dedup = schema.dedupe(unificados, key_fields=("platform", "title", "handle"))
    videos = metrics.enrich_videos(dedup)[:MAX_VIDEOS_POR_ORBIT]

    com_outlier = [v for v in videos if (v.get("outlier_score") or 0) >= 30]
    report = {
        "keywords": orbit["keywords"],
        "platforms": orbit["platforms"],
        "videos_brutos": len(todos),
        "videos_unicos": len(videos),
        "outliers": len(com_outlier),
        "melhor_outlier": (max(com_outlier, key=lambda v: v["outlier_score"])
                           if com_outlier else None),
        "por_plataforma": {p: sum(1 for v in videos if v["platform"] == p)
                           for p in ("tiktok", "instagram", "youtube")},
        "mediana_views": int(metrics.corpus_baseline(videos)),
        "fontes": fontes_total,
        "gerado_em": _now(),
    }
    if sum(fontes_total.values()) == 0:
        erros.append("Nenhuma fonte real conectada: configure YouTube Data API "
                     "ou a Virlo API em APIs & Conexões para minerar dados reais.")

    return _orbit_update(orbit_id, {
        "status": "completed",
        "progress": 100,
        "finished_at": _now(),
        "videos": videos,
        "report": report,
        "errors": erros[:20],
        "fontes": fontes_total,
    }) or orbit


def orbit_delete(orbit_id: str, tenant_id: str) -> bool:
    with _lock:
        orbits = _orbits()
        kept = [o for o in orbits if not (o.get("id") == orbit_id and o.get("tenant") == tenant_id)]
        if len(kept) == len(orbits):
            return False
        _save_orbits(kept)
    return True


# ================================================================== COMET
FREQUENCIAS = {"6h": 6 * 3600, "daily": 86400, "weekly": 7 * 86400}


def _comets() -> list[dict]:
    data = _read(COMETS_FILE, [])
    return data if isinstance(data, list) else []


def _save_comets(comets: list[dict]) -> None:
    _write(COMETS_FILE, comets[:60])


def comet_create(tenant_id: str, name: str, keywords: list[str],
                 platforms: Optional[list[str]], frequency: str = "daily",
                 min_views: int = 0) -> dict:
    kws = [k.strip() for k in keywords if k and k.strip()][:12]
    if not kws:
        raise ValueError("Informe ao menos uma palavra-chave")
    if frequency not in FREQUENCIAS:
        raise ValueError(f"Frequência inválida. Use: {', '.join(FREQUENCIAS)}")
    comet = {
        "id": "cmt_" + secrets.token_hex(6),
        "tenant": tenant_id,
        "name": (name or kws[0])[:120],
        "keywords": kws,
        "platforms": [p for p in (platforms or PLATAFORMAS) if p in PLATAFORMAS],
        "frequency": frequency,
        "min_views": int(min_views),
        "status": "ativo",
        "created_at": _now(),
        "last_run": None,
        "next_run": datetime.fromtimestamp(_now_ts() + FREQUENCIAS[frequency],
                                           tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "series": [],          # cada ciclo: {at, videos, outliers, mediana_views}
        "videos": [],
    }
    with _lock:
        comets = _comets()
        comets.insert(0, comet)
        _save_comets(comets)
    return comet


def comet_list(tenant_id: str) -> list[dict]:
    return [{k: v for k, v in c.items() if k != "videos"}
            for c in _comets() if c.get("tenant") == tenant_id]


def comet_get(comet_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
    for c in _comets():
        if c.get("id") == comet_id and (tenant_id is None or c.get("tenant") == tenant_id):
            return c
    return None


def comet_delete(comet_id: str, tenant_id: str) -> bool:
    with _lock:
        comets = _comets()
        kept = [c for c in comets if not (c.get("id") == comet_id and c.get("tenant") == tenant_id)]
        if len(kept) == len(comets):
            return False
        _save_comets(kept)
    return True


async def comet_run(comet_id: str, tenant_id: Optional[str] = None) -> dict:
    """Um ciclo do monitor: coleta, pontua e empilha na série temporal."""
    comet = comet_get(comet_id, tenant_id)
    if not comet:
        raise ValueError("Comet não encontrado")

    todos: list[dict] = []
    erros: list[str] = []
    for kw in comet["keywords"]:
        try:
            vids, errs, _ = await _coletar_keyword(kw, comet["platforms"],
                                                   comet.get("min_views", 0))
            todos += vids
            erros += errs
        except Exception as exc:
            erros.append(f"{kw}: {type(exc).__name__}")

    unificados = [v if v.get("uid") else schema.normalize_video(v, v.get("platform", "tiktok"))
                  for v in todos]
    dedup = schema.dedupe(unificados, key_fields=("platform", "title", "handle"))
    videos = metrics.enrich_videos(dedup)[:MAX_VIDEOS_POR_ORBIT]

    ciclo = {
        "at": _now(),
        "videos": len(videos),
        "outliers": sum(1 for v in videos if (v.get("outlier_score") or 0) >= 30),
        "mediana_views": int(metrics.corpus_baseline(videos)),
        "top_outlier_score": max([v.get("outlier_score") or 0 for v in videos] or [0]),
    }
    frequencia = FREQUENCIAS.get(comet["frequency"], 86400)
    with _lock:
        comets = _comets()
        for c in comets:
            if c.get("id") == comet_id:
                c["series"] = (c.get("series") or [])[-59:] + [ciclo]
                c["videos"] = videos
                c["last_run"] = ciclo["at"]
                c["next_run"] = datetime.fromtimestamp(_now_ts() + frequencia,
                                                       tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                c["errors"] = erros[:10]
                _save_comets(comets)
                return c
    return comet


def comets_vencidos() -> list[dict]:
    agora = _now()
    return [c for c in _comets()
            if c.get("status") == "ativo" and (c.get("next_run") or "") <= agora]


async def scheduler_tick() -> list[dict]:
    """Roda os Comets vencidos (chamado pelo loop de background)."""
    out = []
    for comet in comets_vencidos():
        try:
            c = await comet_run(comet["id"])
            out.append({"comet": comet["id"], "videos": len(c.get("videos") or [])})
        except Exception as exc:
            out.append({"comet": comet.get("id"), "error": type(exc).__name__})
    return out


async def scheduler_loop(interval: int = 120) -> None:
    while True:
        try:
            await scheduler_tick()
        except Exception:
            pass
        await asyncio.sleep(interval)


# ================================================================== INGESTÃO
def _ingested() -> list[dict]:
    data = _read(INGEST_FILE, [])
    return data if isinstance(data, list) else []


def ingest_videos(items: list[dict], source_name: str = "ingestao") -> int:
    """Qualquer integração externa (script, planilha, agente) empurra vídeos aqui."""
    if not items:
        return 0
    novos = []
    for raw in items[:500]:
        try:
            v = schema.normalize_video(raw, raw.get("platform", "tiktok"))
        except Exception:
            continue
        v["source"] = source_name if source_name else "ingestao"
        v["ingested_at"] = _now()
        novos.append(v)

    with _lock:
        atuais = _ingested()
        existentes = {(v.get("platform"), (v.get("title") or "")[:60].lower())
                      for v in atuais}
        filtrados = [v for v in novos
                     if (v.get("platform"), (v.get("title") or "")[:60].lower()) not in existentes]
        _write(INGEST_FILE, (filtrados + atuais)[:2000])
    return len(filtrados)


def ingested_for_query(q: str) -> list[dict]:
    termos = [t for t in (q or "").lower().split() if len(t) > 2]
    if not termos:
        return []
    out = []
    for v in _ingested():
        texto = ((v.get("title") or "") + " " + " ".join(v.get("hashtags") or [])).lower()
        if any(t in texto for t in termos):
            out.append(v)
    return out[:60]


def mined_for_query(q: str) -> list[dict]:
    """Vídeos já minerados (Orbits concluídos) que casam com a busca do Radar."""
    termos = [t for t in (q or "").lower().split() if len(t) > 2]
    if not termos:
        return []
    out = []
    for orbit in _orbits():
        if orbit.get("status") != "completed":
            continue
        palavras = " ".join(orbit.get("keywords") or []).lower()
        if not any(t in palavras for t in termos):
            continue
        out += orbit.get("videos") or []
    # devolve no máximo 80, priorizando outliers
    out.sort(key=lambda v: -(v.get("outlier_score") or 0))
    return out[:80]


# ================================================================== EXPLICAÇÃO
def como_funciona() -> dict:
    """Transparência do pipeline — o que copiamos da arquitetura do Virlo."""
    return {
        "resumo": ("Mineração em arquitetura de fila (Orbit) + monitor agendado (Comet), "
                   "com detecção de outlier por baseline de criador."),
        "etapas": [
            {"etapa": "1. Enfileirar", "orbit": "POST /api/mining/orbits",
             "comet": "POST /api/mining/comets",
             "detalhe": "keywords + plataformas + min_views viram um job persistido."},
            {"etapa": "2. Coletar",
             "detalhe": "worker consulta APIs oficiais e a Virlo (quando configurada), "
                        "uma keyword por vez, com erro isolado por fonte."},
            {"etapa": "3. Normalizar", "detalhe":
                "todo resultado passa por schema.normalize_video → uid global."},
            {"etapa": "4. Deduplicar", "detalhe":
                "mesmo vídeo em duas fontes vira um registro, com a fonte mais "
                "confiável vencendo campo a campo."},
            {"etapa": "5. Pontuar", "detalhe":
                "metrics.enrich_videos calcula viral_score, velocity, outlier_score "
                "(views ÷ baseline do criador) e tier."},
            {"etapa": "6. Persistir série", "detalhe":
                "o Comet empilha cada ciclo (videos, outliers, mediana) — é o que "
                "permite ver tendência em vez de foto."},
        ],
        "diferenca": ("Não copiamos o mecanismo de coleta proprietário da Virlo; "
                      "copiamos a arquitetura e usamos fontes legítimas: APIs oficiais, "
                      "Virlo API (paga, opcional) e ingestão externa."),
        "custos": {"orbit": "10 créditos", "comet_ciclo": "10 créditos",
                   "ingest": "grátis"},
    }
