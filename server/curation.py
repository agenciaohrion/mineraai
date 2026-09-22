"""MineraAI — Módulo de Curadoria de Conteúdo

Pipeline de curadoria em 5 etapas:
  1. COLETA → vídeos entram via Radar, Mineração, Ingestão ou importação manual
  2. FILTRAGEM AUTOMÁTICA → regras de score, views, idade, blacklist, plataforma
  3. ENRIQUECIMENTO IA → Viral Lab, hooks, insights, tags sugeridas
  4. DECISÃO HUMANA → kanban: novo → em_analise → aprovado/rejeitado → arquivado/publicado
  5. AÇÃO → Biblioteca, Fábrica de Vídeos, webhook externo (publicação)

Persistência: data/curation.json + data/curation_rules.json
"""
from __future__ import annotations

import time
import uuid
import re
from typing import Optional

from .storage import DATA_DIR, _read, _write, _lock
from .providers import normalize_video

CURATION_FILE = DATA_DIR / "curation.json"
RULES_FILE = DATA_DIR / "curation_rules.json"

# Estados do kanban de curadoria
STATUSES = ["novo", "em_analise", "aprovado", "rejeitado", "arquivado", "publicado"]
VALID_DECISIONS = set(STATUSES)

DEFAULT_RULES = {
    "min_viral_score": 35,
    "min_views": 1000,
    "min_engagement": 1.0,
    "max_age_hours": 720,  # 30 dias
    "platforms": ["tiktok", "instagram", "youtube", "all"],
    "required_platform": "all",
    "blacklist_keywords": ["golpe", "aposta", "cassino", "bet", "onlyfans"],
    "whitelist_keywords": [],
    "blacklist_authors": [],
    "auto_approve_score": 85,  # >= vira aprovado automaticamente
    "auto_reject_score": 15,   # <= vira rejeitado automaticamente
    "auto_approve_enabled": False,
    "tags_prioritarias": ["viral", "achadinhos", "review", "teste"],
    "updated_at": None,
}


# ------------------------------------------------------------------ regras
def rules_get() -> dict:
    with _lock:
        saved = _read(RULES_FILE, {})
    # merge com defaults
    out = dict(DEFAULT_RULES)
    out.update(saved or {})
    return out


def rules_save(patch: dict) -> dict:
    with _lock:
        saved = _read(RULES_FILE, {})
        for k, v in (patch or {}).items():
            if k in DEFAULT_RULES or k in ("blacklist_keywords", "whitelist_keywords",
                                            "blacklist_authors", "tags_prioritarias"):
                saved[k] = v
        saved["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        _write(RULES_FILE, saved)
    return rules_get()


# ------------------------------------------------------------------ scoring / filtragem
def _contains_blacklist(text: str, blacklist: list[str]) -> Optional[str]:
    t = (text or "").lower()
    for kw in blacklist:
        kw = kw.lower().strip()
        if not kw:
            continue
        if kw in t:
            return kw
    return None


def evaluate_item(video: dict, rules: dict | None = None) -> dict:
    """Aplica regras de curadoria e retorna diagnóstico."""
    rules = rules or rules_get()
    reasons = []
    score_mod = 0
    blocked = False

    title = (video.get("title") or "") + " " + " ".join(video.get("hashtags") or [])

    # blacklist
    hit = _contains_blacklist(title + " " + video.get("author", ""), rules.get("blacklist_keywords", []))
    if hit:
        reasons.append(f"blacklist: '{hit}'")
        blocked = True
        score_mod -= 50

    # blacklist author
    hit_author = _contains_blacklist(video.get("author", "") + " " + video.get("handle", ""),
                                     rules.get("blacklist_authors", []))
    if hit_author:
        reasons.append(f"autor bloqueado: '{hit_author}'")
        blocked = True

    # whitelist boost
    if rules.get("whitelist_keywords"):
        for kw in rules["whitelist_keywords"]:
            if kw.lower() in title.lower():
                reasons.append(f"whitelist: '{kw}' (+10)")
                score_mod += 10
                break

    # thresholds
    vs = video.get("viral_score", 0)
    if vs < rules.get("min_viral_score", 0):
        reasons.append(f"viral_score {vs} < mínimo {rules['min_viral_score']}")
        if not blocked:
            blocked = vs < 10  # só bloqueia se muito baixo
    else:
        reasons.append(f"viral_score ok ({vs})")

    views = video.get("views", 0)
    if views < rules.get("min_views", 0):
        reasons.append(f"views {views} < mínimo {rules['min_views']}")
    else:
        reasons.append(f"views ok ({views})")

    eng = video.get("engagement", 0)
    if eng < rules.get("min_engagement", 0):
        reasons.append(f"engajamento {eng}% < mínimo {rules['min_engagement']}%")

    age = video.get("age_hours", 0)
    if age > rules.get("max_age_hours", 720):
        reasons.append(f"muito antigo: {age}h > {rules['max_age_hours']}h")
        score_mod -= 15

    # platform filter
    req_pf = rules.get("required_platform", "all")
    if req_pf != "all" and video.get("platform") != req_pf:
        reasons.append(f"plataforma {video.get('platform')} != {req_pf} exigida")
        blocked = True

    # tag prioritária boost
    tags = [t.lower().lstrip("#") for t in (video.get("hashtags") or [])]
    pri = [t.lower().lstrip("#") for t in rules.get("tags_prioritarias", [])]
    if any(p in tags for p in pri):
        score_mod += 8
        reasons.append("tag prioritária (+8)")

    # final
    final_score = max(0, min(100, vs + score_mod))
    auto_decision = None
    if rules.get("auto_approve_enabled"):
        if final_score >= rules.get("auto_approve_score", 85):
            auto_decision = "aprovado"
            reasons.append(f"auto-aprovado (score {final_score} >= {rules['auto_approve_score']})")
        elif final_score <= rules.get("auto_reject_score", 15):
            auto_decision = "rejeitado"
            reasons.append(f"auto-rejeitado (score {final_score} <= {rules['auto_reject_score']})")

    return {
        "blocked": blocked,
        "score_original": vs,
        "score_curadoria": final_score,
        "score_mod": score_mod,
        "reasons": reasons,
        "auto_decision": auto_decision,
    }


# ------------------------------------------------------------------ CRUD da fila
def _load_all() -> list[dict]:
    with _lock:
        return _read(CURATION_FILE, [])


def _save_all(items: list[dict]):
    with _lock:
        _write(CURATION_FILE, items[:5000])  # limite de segurança


def curation_list(status: str = "", platform: str = "", min_score: int = 0,
                  q: str = "", limit: int = 50, sort: str = "score") -> list[dict]:
    items = _load_all()
    # expira arquivados antigos? não, mantém

    if status and status in VALID_DECISIONS:
        items = [i for i in items if i.get("status") == status]
    if platform and platform != "all":
        items = [i for i in items if i.get("video", {}).get("platform") == platform]
    if min_score:
        items = [i for i in items if (i.get("curadoria", {}).get("score_curadoria", 0) >= min_score)]
    if q:
        ql = q.lower()
        items = [i for i in items if ql in (i.get("video", {}).get("title") or "").lower()
                 or ql in (i.get("video", {}).get("author") or "").lower()
                 or ql in " ".join(i.get("video", {}).get("hashtags") or []).lower()
                 or ql in (i.get("query_origem") or "").lower()]

    # ordenação
    if sort == "recent":
        items.sort(key=lambda x: x.get("created_at_ts", 0), reverse=True)
    elif sort == "views":
        items.sort(key=lambda x: x.get("video", {}).get("views", 0), reverse=True)
    elif sort == "oldest":
        items.sort(key=lambda x: x.get("created_at_ts", 0))
    else:  # score
        items.sort(key=lambda x: x.get("curadoria", {}).get("score_curadoria", 0), reverse=True)

    return items[:max(1, min(limit, 200))]


def curation_get(item_id: str) -> Optional[dict]:
    return next((i for i in _load_all() if i.get("id") == item_id), None)


def curation_create_from_video(video: dict, query_origem: str = "", source: str = "radar",
                               extra: dict | None = None) -> dict:
    """Cria item de curadoria a partir de um vídeo normalizado."""
    rules = rules_get()
    # normaliza se vier cru
    if "viral_score" not in video:
        video = normalize_video(video, video.get("platform", "tiktok"))

    eval_res = evaluate_item(video, rules)

    # dedupe por video id + platform
    existing = _load_all()
    key = (video.get("platform"), video.get("id"))
    if any((it.get("video", {}).get("platform"), it.get("video", {}).get("id")) == key for it in existing):
        # atualiza score se já existe
        for it in existing:
            if (it.get("video", {}).get("platform"), it.get("video", {}).get("id")) == key:
                it["curadoria"] = eval_res
                it["video"] = video
                it["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if eval_res.get("auto_decision") and it.get("status") == "novo":
                    it["status"] = eval_res["auto_decision"]
                _save_all(existing)
                return it
        # fallback

    now = time.time()
    item = {
        "id": f"cur-{uuid.uuid4().hex[:10]}",
        "status": eval_res.get("auto_decision") or "novo",
        "video": video,
        "query_origem": query_origem,
        "source": source,  # radar, mineracao, ingestao, manual, n8n
        "curadoria": eval_res,
        "enriquecimento": {},  # preenchido por IA depois
        "decisao": {
            "por": None,
            "em": None,
            "notas": "",
            "historico": [],
        },
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "created_at_ts": now,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "extra": extra or {},
    }
    if eval_res.get("blocked") and item["status"] == "novo":
        item["status"] = "rejeitado"
        item["decisao"]["notas"] = "Bloqueado automaticamente: " + "; ".join(eval_res["reasons"][:3])

    with _lock:
        items = _read(CURATION_FILE, [])
        items.insert(0, item)
        _write(CURATION_FILE, items[:5000])
    return item


def curation_bulk_create(videos: list[dict], query_origem: str = "", source: str = "radar") -> dict:
    created, skipped, blocked = 0, 0, 0
    rules = rules_get()
    existing_keys = set((it.get("video", {}).get("platform"), it.get("video", {}).get("id"))
                        for it in _load_all())

    batch = []
    for v in videos[:100]:  # limite por lote
        key = (v.get("platform"), v.get("id"))
        if key in existing_keys:
            skipped += 1
            continue
        # avalia rápido
        ev = evaluate_item(v, rules)
        if ev.get("blocked") and rules.get("min_viral_score", 0) > 0:
            # ainda cria mas como rejeitado para auditoria
            blocked += 1

        now = time.time()
        item = {
            "id": f"cur-{uuid.uuid4().hex[:10]}",
            "status": ev.get("auto_decision") or ("rejeitado" if ev.get("blocked") else "novo"),
            "video": v,
            "query_origem": query_origem,
            "source": source,
            "curadoria": ev,
            "enriquecimento": {},
            "decisao": {"por": "sistema" if ev.get("auto_decision") or ev.get("blocked") else None,
                        "em": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) if ev.get("blocked") else None,
                        "notas": "; ".join(ev["reasons"][:2]) if ev.get("blocked") else "",
                        "historico": []},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "created_at_ts": now,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "extra": {},
        }
        batch.append(item)
        existing_keys.add(key)
        created += 1

    if batch:
        with _lock:
            items = _read(CURATION_FILE, [])
            items = batch + items
            _write(CURATION_FILE, items[:5000])

    return {"criados": created, "ignorados_duplicados": skipped, "bloqueados": blocked, "total": len(batch)}


def curation_decide(item_id: str, decision: str, notas: str = "", por: str = "humano") -> Optional[dict]:
    if decision not in VALID_DECISIONS:
        return None
    with _lock:
        items = _read(CURATION_FILE, [])
        it = next((x for x in items if x.get("id") == item_id), None)
        if not it:
            return None
        old = it.get("status")
        it["status"] = decision
        it["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        it["decisao"]["por"] = por
        it["decisao"]["em"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        it["decisao"]["notas"] = notas or it["decisao"].get("notas", "")
        it["decisao"]["historico"].append({
            "de": old,
            "para": decision,
            "em": it["decisao"]["em"],
            "por": por,
        })
        _write(CURATION_FILE, items)
        return dict(it)


def curation_bulk_decide(ids: list[str], decision: str, notas: str = "") -> dict:
    if decision not in VALID_DECISIONS:
        return {"ok": False, "erro": "decisão inválida"}
    with _lock:
        items = _read(CURATION_FILE, [])
        count = 0
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for it in items:
            if it.get("id") in ids:
                old = it.get("status")
                it["status"] = decision
                it["updated_at"] = now_str
                it["decisao"]["por"] = "humano"
                it["decisao"]["em"] = now_str
                if notas:
                    it["decisao"]["notas"] = notas
                it["decisao"]["historico"].append({"de": old, "para": decision, "em": now_str, "por": "humano"})
                count += 1
        _write(CURATION_FILE, items)
    return {"ok": True, "alterados": count}


def curation_enrich(item_id: str, enrich_data: dict) -> Optional[dict]:
    """Salva enriquecimento de IA (hooks, análise, tags, etc)."""
    with _lock:
        items = _read(CURATION_FILE, [])
        it = next((x for x in items if x.get("id") == item_id), None)
        if not it:
            return None
        it["enriquecimento"].update(enrich_data or {})
        it["enriquecimento"]["enriquecido_em"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        it["updated_at"] = it["enriquecimento"]["enriquecido_em"]
        # se não tem decisão, move para em_analise
        if it["status"] == "novo":
            it["status"] = "em_analise"
        _write(CURATION_FILE, items)
        return dict(it)


def curation_delete(item_id: str) -> bool:
    with _lock:
        items = _read(CURATION_FILE, [])
        kept = [i for i in items if i.get("id") != item_id]
        if len(kept) == len(items):
            return False
        _write(CURATION_FILE, kept)
        return True


def curation_stats() -> dict:
    items = _load_all()
    by_status = {s: 0 for s in STATUSES}
    by_platform = {}
    by_source = {}
    scores = []
    for it in items:
        by_status[it.get("status", "novo")] = by_status.get(it.get("status"), 0) + 1
        pf = it.get("video", {}).get("platform", "unknown")
        by_platform[pf] = by_platform.get(pf, 0) + 1
        src = it.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1
        scores.append(it.get("curadoria", {}).get("score_curadoria", 0))

    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    outliers = sum(1 for s in scores if s >= 75)
    cutoff = time.time() - 24 * 3600
    novos_24h = sum(1 for it in items if it.get("created_at_ts", 0) > cutoff)

    return {
        "total": len(items),
        "por_status": by_status,
        "por_plataforma": by_platform,
        "por_origem": by_source,
        "media_score": avg_score,
        "outliers_75": outliers,
        "novos_24h": novos_24h,
    }


def curation_outliers(min_score: int = 75, limit: int = 20) -> list[dict]:
    items = _load_all()
    filtered = [it for it in items
                if it.get("curadoria", {}).get("score_curadoria", 0) >= min_score
                and it.get("status") in ("novo", "em_analise")]
    filtered.sort(key=lambda x: x.get("curadoria", {}).get("score_curadoria", 0), reverse=True)
    return filtered[:limit]


def curation_auto_from_search(query: str, videos: list[dict], source: str = "auto") -> dict:
    """Fluxo usado pelo endpoint auto-curate e pelo n8n."""
    return curation_bulk_create(videos, query_origem=query, source=source)
