"""Planos, créditos, cotas e chaves de API — a camada de billing do SaaS.

Por que isso existe desde o primeiro dia: os quatro produtos que o MineraAI
unifica cobram por CRÉDITO (Virlo: 100 por research run; Kalodata: cotas
diárias de busca + créditos de IA; ViralFindr: 200 créditos/semana). Crédito
não é só monetização: é o disjuntor que impede um cliente em loop de queimar a
cota de scraping da operação inteira.

Modelo:
  tenant  → workspace (id, plano, chaves de API, consumo)
  plano   → créditos/mês + limite diário + assentos
  ação    → custo em créditos (tabela ACTIONS)
  ledger  → todo consumo é registrado (auditável e reembolsável)
"""
from __future__ import annotations

import hashlib
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException

from .storage import DATA_DIR, _lock, _read, _write

TENANTS_FILE = DATA_DIR / "tenants.json"
USAGE_FILE = DATA_DIR / "usage.json"

DEFAULT_TENANT = "demo"
MAX_USAGE_EVENTS = 5000

# ------------------------------------------------------------------ planos
PLANS: dict[str, dict] = {
    "free": {
        "name": "Free",
        "price_brl": 0,
        "credits": 600,
        "daily_queries": 60,
        "seats": 1,
        "history_days": 30,
        "features": ["radar", "outliers", "estudio", "biblioteca"],
    },
    "starter": {
        "name": "Starter",
        "price_brl": 49,
        "credits": 2000,
        "daily_queries": 250,
        "seats": 1,
        "history_days": 90,
        "features": ["radar", "outliers", "commerce", "estudio", "biblioteca", "agents"],
    },
    "pro": {
        "name": "Pro",
        "price_brl": 199,
        "credits": 12000,
        "daily_queries": 1200,
        "seats": 3,
        "history_days": 365,
        "features": ["radar", "outliers", "commerce", "estudio", "biblioteca",
                     "agents", "api", "alertas"],
    },
    "enterprise": {
        "name": "Enterprise",
        "price_brl": None,
        "credits": 40000,
        "daily_queries": 6000,
        "seats": 10,
        "history_days": 1000,
        "features": ["radar", "outliers", "commerce", "estudio", "biblioteca",
                     "agents", "api", "alertas", "mcp", "sso"],
    },
}

# ------------------------------------------------------------------ custos
# Cada ação que toca rede externa, modelo de IA ou GPU custa crédito.
ACTIONS: dict[str, int] = {
    "search": 2,          # busca no Radar Viral (1 fan-out de fontes)
    "outliers": 3,        # busca + cálculo de baseline por criador
    "products": 2,
    "creators": 2,
    "lives": 1,
    "niches": 2,
    "trends": 1,
    "ideas": 2,
    "ai_hooks": 5,
    "ai_script": 20,
    "ai_caption": 4,
    "ai_titles": 4,
    "ai_analyze": 15,
    "ai_narration": 30,
    "agent_run": 100,     # research agent completo (o mesmo preço do Virlo)
    "fabrica_job": 250,   # geração de vídeo (GPU no RunPod)
    # --- publicação (upload consome ~1.600 unidades da cota diária do YouTube)
    "publish": 40,
    "publish_sync": 1,    # leitura de métricas do vídeo publicado
    # --- Virlo API (US$ 0,50 por chamada paga ≈ 60 créditos; leitura ~grátis)
    "virlo_read": 1,
    "virlo_orbit": 60,
    "virlo_satellite": 60,
    "virlo_comet": 60,
    # --- mineração própria (fila Orbit / monitor Comet)
    "mining_orbit": 10,
    "mining_comet": 10,
    "broll": 3,
    "export": 5,
    "ingest": 0,          # entrada de dados externos não é cobrada
    "mining": 10,
}

FREE_ACTIONS = {"ingest", "library", "runpod_health"}


# ------------------------------------------------------------------ erros
class QuotaExceeded(HTTPException):
    """402 — sem créditos. A resposta diz exatamente quanto falta e como resolver."""

    def __init__(self, message: str, detail: dict):
        super().__init__(status_code=402, detail={"error": message,
                                                  "code": "quota_exceeded", **detail})


class RateLimited(HTTPException):
    def __init__(self, detail: dict):
        super().__init__(status_code=429, detail={"error": "Limite diário do plano atingido",
                                                  "code": "rate_limited", **detail})


# ------------------------------------------------------------------ persistência
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _month_key(ts: Optional[float] = None) -> str:
    d = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return d.strftime("%Y-%m")


def _day_key(ts: Optional[float] = None) -> str:
    d = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return d.strftime("%Y-%m-%d")


def _load() -> dict:
    data = _read(TENANTS_FILE, {})
    return data if isinstance(data, dict) and "tenants" in data else {"tenants": {}}


def _save(data: dict) -> None:
    _write(TENANTS_FILE, data)


def _new_key() -> str:
    return "mka_" + secrets.token_urlsafe(24).replace("-", "").replace("_", "")[:32]


def _key_id(key: str) -> str:
    return "key_" + hashlib.md5(key.encode()).hexdigest()[:10]


def _new_tenant(name: str, plan: str, tenant_id: Optional[str] = None) -> dict:
    plan = plan if plan in PLANS else "free"
    tid = tenant_id or ("t_" + secrets.token_hex(5))
    key = _new_key()
    return {
        "id": tid,
        "name": name,
        "plan": plan,
        "created_at": _now_iso(),
        "cycle_start": _month_key(),
        "credits_used": 0,
        "credits_bonus": 0,
        "daily_used": 0,
        "daily_date": _day_key(),
        "status": "active",
        "api_keys": [{"id": _key_id(key), "key": key, "label": "default",
                      "created_at": _now_iso(), "last_used": None}],
    }


def ensure_default() -> dict:
    """Garante o workspace de demonstração (sem chave = plano free)."""
    with _lock:
        data = _load()
        if DEFAULT_TENANT not in data["tenants"]:
            data["tenants"][DEFAULT_TENANT] = _new_tenant(
                "Workspace demo", "free", DEFAULT_TENANT)
            _save(data)
        tenant = data["tenants"][DEFAULT_TENANT]
    return tenant


# ------------------------------------------------------------------ ciclo / limites
def _roll_cycle(tenant: dict) -> dict:
    """Zera consumo quando virou o mês (ou o dia)."""
    changed = False
    if tenant.get("cycle_start") != _month_key():
        tenant["cycle_start"] = _month_key()
        tenant["credits_used"] = 0
        changed = True
    if tenant.get("daily_date") != _day_key():
        tenant["daily_date"] = _day_key()
        tenant["daily_used"] = 0
        changed = True
    if changed:
        tenant["rolled_at"] = _now_iso()
    return tenant


def plan_of(tenant: dict) -> dict:
    return PLANS.get(tenant.get("plan", "free"), PLANS["free"])


def limits(tenant: dict) -> dict:
    tenant = _roll_cycle(dict(tenant))
    plan = plan_of(tenant)
    total = plan["credits"] + int(tenant.get("credits_bonus") or 0)
    used = int(tenant.get("credits_used") or 0)
    return {
        "plan": tenant.get("plan", "free"),
        "plan_name": plan["name"],
        "price_brl": plan["price_brl"],
        "credits_total": total,
        "credits_used": used,
        "credits_remaining": max(0, total - used),
        "credits_pct": round(100 * used / total, 1) if total else 100.0,
        "daily_limit": plan["daily_queries"],
        "daily_used": int(tenant.get("daily_used") or 0),
        "daily_remaining": max(0, plan["daily_queries"] - int(tenant.get("daily_used") or 0)),
        "seats": plan["seats"],
        "history_days": plan["history_days"],
        "features": plan["features"],
        "cycle_start": tenant.get("cycle_start"),
    }


# ------------------------------------------------------------------ resolução de tenant
def get_tenant(tenant_id: str) -> Optional[dict]:
    with _lock:
        tenant = _load()["tenants"].get(tenant_id)
    return _roll_cycle(tenant) if tenant else None


def resolve_key(key: str) -> Optional[dict]:
    """Encontra o tenant dono da chave de API (e marca o último uso)."""
    if not key:
        return None
    with _lock:
        data = _load()
        for tenant in data["tenants"].values():
            for k in tenant.get("api_keys", []):
                if secrets.compare_digest(k.get("key", ""), key):
                    k["last_used"] = _now_iso()
                    _save(data)
                    return _roll_cycle(tenant)
    return None


def create_tenant(name: str, plan: str = "free") -> dict:
    with _lock:
        data = _load()
        tenant = _new_tenant(name, plan)
        data["tenants"][tenant["id"]] = tenant
        _save(data)
    return tenant


def list_tenants() -> list[dict]:
    with _lock:
        tenants = list(_load()["tenants"].values())
    return [{**{k: v for k, v in t.items() if k != "api_keys"},
             "keys": len(t.get("api_keys", []))} for t in tenants]


def set_plan(tenant_id: str, plan: str) -> dict:
    if plan not in PLANS:
        raise HTTPException(400, f"Plano inválido. Opções: {', '.join(PLANS)}")
    with _lock:
        data = _load()
        tenant = data["tenants"].get(tenant_id)
        if not tenant:
            raise HTTPException(404, "Workspace não encontrado")
        tenant["plan"] = plan
        tenant["plan_changed_at"] = _now_iso()
        _save(data)
    return tenant


def grant_credits(tenant_id: str, amount: int, reason: str = "ajuste manual") -> dict:
    if amount == 0:
        raise HTTPException(400, "Informe uma quantidade diferente de zero")
    with _lock:
        data = _load()
        tenant = data["tenants"].get(tenant_id)
        if not tenant:
            raise HTTPException(404, "Workspace não encontrado")
        bonus = int(tenant.get("credits_bonus") or 0) + int(amount)
        tenant["credits_bonus"] = max(0, bonus)
        tenant.setdefault("grants", []).insert(0, {
            "amount": int(amount), "reason": reason, "at": _now_iso()})
        tenant["grants"] = tenant["grants"][:20]
        _save(data)
        tenant = dict(tenant)
    return tenant


# ------------------------------------------------------------------ chaves de API
def create_key(tenant_id: str, label: str = "nova chave") -> dict:
    key = _new_key()
    with _lock:
        data = _load()
        tenant = data["tenants"].get(tenant_id)
        if not tenant:
            raise HTTPException(404, "Workspace não encontrado")
        entry = {"id": _key_id(key), "key": key, "label": label,
                 "created_at": _now_iso(), "last_used": None}
        tenant.setdefault("api_keys", []).append(entry)
        _save(data)
    return entry


def revoke_key(tenant_id: str, key_id: str) -> bool:
    with _lock:
        data = _load()
        tenant = data["tenants"].get(tenant_id)
        if not tenant:
            return False
        keys = tenant.get("api_keys", [])
        kept = [k for k in keys if k.get("id") != key_id]
        if len(kept) == len(keys):
            return False
        tenant["api_keys"] = kept
        _save(data)
    return True


def masked_keys(tenant: dict) -> list[dict]:
    out = []
    for k in tenant.get("api_keys", []):
        raw = k.get("key", "")
        out.append({**{f: v for f, v in k.items() if f != "key"},
                    "masked": raw[:8] + "••••••••" + raw[-4:] if len(raw) > 14 else "•••"})
    return out


# ------------------------------------------------------------------ ledger
def _append_usage(event: dict) -> None:
    data = _read(USAGE_FILE, [])
    if not isinstance(data, list):
        data = []
    data.insert(0, event)
    _write(USAGE_FILE, data[:MAX_USAGE_EVENTS])


def charge(tenant_id: str, action: str, units: int = 1,
           meta: Optional[dict] = None) -> dict:
    """Cobra a ação em créditos. Levanta 402/429 se estourar o plano.

    Toda ação que custa crédito TAMBÉM conta como query do dia, exceto as
    marcadas em FREE_ACTIONS.
    """
    cost = ACTIONS.get(action, 1) * max(1, int(units))
    with _lock:
        data = _load()
        tenant = data["tenants"].get(tenant_id)
        if not tenant:
            raise HTTPException(401, "Workspace inválido")
        tenant = _roll_cycle(tenant)
        plan = plan_of(tenant)
        total = plan["credits"] + int(tenant.get("credits_bonus") or 0)
        used = int(tenant.get("credits_used") or 0)
        daily_used = int(tenant.get("daily_used") or 0)

        if action not in FREE_ACTIONS:
            if daily_used + 1 > plan["daily_queries"]:
                raise RateLimited({"daily_limit": plan["daily_queries"],
                                   "plan": tenant["plan"],
                                   "upgrade": "Aumente o plano para mais consultas por dia."})
            if used + cost > total:
                raise QuotaExceeded(
                    "Créditos insuficientes para esta ação",
                    {"credits_needed": cost,
                     "credits_remaining": max(0, total - used),
                     "plan": tenant["plan"],
                     "action": action,
                     "upgrade": "Mude de plano ou adicione créditos em Uso & Plano."})

        tenant["credits_used"] = used + cost
        if action not in FREE_ACTIONS:
            tenant["daily_used"] = daily_used + 1
        data["tenants"][tenant_id] = tenant
        _save(data)
        remaining = max(0, total - tenant["credits_used"])

    _append_usage({"at": _now_iso(), "ts": int(time.time()), "tenant": tenant_id,
                   "action": action, "credits": cost, "units": units,
                   "meta": meta or {}})
    return {"action": action, "charged": cost, "credits_remaining": remaining}


def usage_summary(tenant_id: str, days: int = 14) -> dict:
    with _lock:
        events = [e for e in _read(USAGE_FILE, [])
                  if isinstance(e, dict) and e.get("tenant") == tenant_id]
    cutoff = time.time() - days * 86400
    recent = [e for e in events if e.get("ts", 0) >= cutoff]

    by_action: dict[str, dict] = {}
    by_day: dict[str, int] = {}
    total = 0
    for e in recent:
        a = e.get("action", "?")
        c = int(e.get("credits") or 0)
        total += c
        slot = by_action.setdefault(a, {"action": a, "calls": 0, "credits": 0})
        slot["calls"] += 1
        slot["credits"] += c
        day = e.get("at", "")[:10]
        by_day[day] = by_day.get(day, 0) + c

    series = []
    for i in range(days - 1, -1, -1):
        day = _day_key(time.time() - i * 86400)
        series.append({"day": day, "credits": by_day.get(day, 0)})

    tenant = get_tenant(tenant_id) or {}
    return {
        "tenant": tenant_id,
        "days": days,
        "credits_total_periodo": total,
        "chamadas": len(recent),
        "por_acao": sorted(by_action.values(), key=lambda x: -x["credits"]),
        "serie_diaria": series,
        "limites": limits(tenant) if tenant else {},
        "eventos_recentes": recent[:25],
    }


def plan_catalog() -> list[dict]:
    """Catálogo formatado para a tela de planos."""
    return [{"id": pid, "action_costs": ACTIONS, **plan} for pid, plan in PLANS.items()]


def price_action(action: str) -> int:
    return ACTIONS.get(action, 1)
