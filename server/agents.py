"""Research Agents — o pesquisador que trabalha sozinho.

É o recurso que o Virlo chama de "Content Research Agents": você descreve o que
quer saber ("quais hooks funcionam em skincare no TikTok?"), escolhe a
frequência, e o agente executa o pipeline completo — busca unificada, outlier
detection, facetas e recomendação de formato — entregando um dossiê pronto, sem
você abrir a plataforma.

Cada execução custa `agent_run` créditos (100, igual ao concorrente) e pode
entregar o relatório por webhook genérico, Slack ou Discord.

O agendador é um loop asyncio iniciado no startup da aplicação: sem Celery,
sem infra extra. Para volume alto, trocar por cron/worker é uma linha.
"""
from __future__ import annotations

import asyncio
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from fastapi import HTTPException

from . import ai_engine, metrics, research
from .storage import DATA_DIR, _lock, _read, _write

AGENTS_FILE = DATA_DIR / "agents.json"

SCHEDULES = {"manual": 0, "daily": 86400, "weekly": 7 * 86400}
MAX_RUNS_KEPT = 20
MAX_AGENTS_PER_TENANT = 20


# ------------------------------------------------------------------ helpers
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_ts() -> int:
    return int(time.time())


def _load() -> list[dict]:
    data = _read(AGENTS_FILE, [])
    return data if isinstance(data, list) else []


def _save(agents: list[dict]) -> None:
    _write(AGENTS_FILE, agents)


def _next_run(agent: dict, from_ts: Optional[int] = None) -> Optional[str]:
    seconds = SCHEDULES.get(agent.get("schedule", "manual"), 0)
    if not seconds:
        return None
    base = from_ts or _now_ts()
    return datetime.fromtimestamp(base + seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ CRUD
def create_agent(tenant_id: str, data: dict) -> dict:
    name = (data.get("name") or data.get("query") or "Agente").strip()[:80]
    query = (data.get("query") or "").strip()[:160]
    if not query:
        raise HTTPException(400, "Informe o que o agente deve pesquisar (campo 'query')")

    schedule = data.get("schedule", "manual")
    if schedule not in SCHEDULES:
        raise HTTPException(400, f"Frequência inválida. Use: {', '.join(SCHEDULES)}")

    with _lock:
        agents = _load()
        if sum(1 for a in agents if a.get("tenant") == tenant_id) >= MAX_AGENTS_PER_TENANT:
            raise HTTPException(400, f"Limite de {MAX_AGENTS_PER_TENANT} agentes por workspace")
        agent = {
            "id": "ag_" + secrets.token_hex(5),
            "tenant": tenant_id,
            "name": name,
            "query": query,
            "platform": data.get("platform", "all"),
            "period": data.get("period", "30d"),
            "niche": (data.get("niche") or "")[:60],
            "objective": data.get("objective", "hooks"),
            "schedule": schedule,
            "deliver": {
                "webhook": (data.get("webhook") or "")[:400],
                "slack": (data.get("slack") or "")[:400],
                "discord": (data.get("discord") or "")[:400],
            },
            "status": "ativo",
            "created_at": _now(),
            "last_run": None,
            "next_run": _next_run({"schedule": schedule}),
            "runs": [],
        }
        agents.insert(0, agent)
        _save(agents)
    return agent


def list_agents(tenant_id: str) -> list[dict]:
    """Lista sem o payload completo dos relatórios (só o resumo da última run)."""
    out = []
    for a in _load():
        if a.get("tenant") != tenant_id:
            continue
        item = {k: v for k, v in a.items() if k != "runs"}
        last = (a.get("runs") or [None])[0]
        item["last_report"] = ({
            "at": last.get("at"),
            "outliers": len((last.get("report") or {}).get("outliers") or []),
            "videos": (last.get("report") or {}).get("corpus", {}).get("videos"),
        } if last else None)
        item["runs_count"] = len(a.get("runs") or [])
        out.append(item)
    return out


def get_agent(agent_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
    for a in _load():
        if a.get("id") == agent_id and (tenant_id is None or a.get("tenant") == tenant_id):
            return a
    return None


def update_agent(agent_id: str, tenant_id: str, patch: dict) -> dict:
    with _lock:
        agents = _load()
        for a in agents:
            if a.get("id") == agent_id and a.get("tenant") == tenant_id:
                for field in ("name", "query", "platform", "period", "niche",
                              "objective", "schedule", "status"):
                    if field in patch and patch[field] is not None:
                        a[field] = patch[field]
                if "schedule" in patch:
                    a["next_run"] = _next_run(a)
                if any(k in patch for k in ("webhook", "slack", "discord")):
                    a["deliver"] = {**a.get("deliver", {}),
                                    **{k: patch[k] for k in ("webhook", "slack", "discord")
                                       if patch.get(k) is not None}}
                _save(agents)
                return a
    raise HTTPException(404, "Agente não encontrado")


def delete_agent(agent_id: str, tenant_id: str) -> bool:
    with _lock:
        agents = _load()
        kept = [a for a in agents if not (a.get("id") == agent_id and a.get("tenant") == tenant_id)]
        if len(kept) == len(agents):
            return False
        _save(kept)
    return True


# ------------------------------------------------------------------ execução
RECIPE_BY_OBJECTIVE = {
    "hooks": ("Hooks que estão funcionando", "hook"),
    "formato": ("Formato/estrutura vencedora", "estrutura"),
    "produto": ("Produto/oferta em alta", "oferta"),
    "criador": ("Criadores furando a curva", "criador"),
}


def _recommendations(report: dict) -> list[dict]:
    """Transforma dado em ação — o que o usuário faz amanhã de manhã."""
    recs = []
    top = (report.get("outliers") or [])[:3]
    for i, v in enumerate(top, 1):
        recs.append({
            "prioridade": i,
            "acao": f"Replicar o formato de '{v.get('title', '')[:70]}'",
            "porque": (f"{v.get('outlier_ratio')}x acima do baseline "
                       f"({v.get('creator_baseline')} views) em {v.get('platform')}"),
            "como": (f"Abrir o vídeo ({v.get('url') or 'sem url'}), identificar o hook dos "
                     f"3 primeiros segundos e regravar com o mesmo ângulo para o seu nicho."),
            "score": v.get("outlier_score"),
        })
    tags = report.get("facetas", {}).get("top_hashtags") or []
    if tags:
        recs.append({"prioridade": len(recs) + 1,
                     "acao": f"Publicar usando {tags[0]['tag']}",
                     "porque": "hashtag com maior alcance acumulado na pesquisa",
                     "como": "Usar no primeiro bloco de texto e em 2 comentários fixados.",
                     "score": None})
    return recs


async def run_agent(agent: dict, tenant_id: Optional[str] = None) -> dict:
    """Executa a pesquisa completa e persiste o dossiê no histórico do agente."""
    started = _now_ts()
    result = await research.search_videos(
        agent["query"], agent.get("platform", "all"),
        agent.get("period", "30d"), 0, 18)
    videos = research.sort_videos(result["videos"], "outlier_score")

    outliers = [v for v in videos if v.get("outlier_score", 0) >= 30][:8]
    hooks: list[str] = []
    if outliers:
        try:
            generated = await ai_engine.generate_hooks(
                outliers[0].get("title", agent["query"])[:80],
                agent.get("niche", ""), "", "direto", 5)
            hooks = generated.get("hooks", []) if isinstance(generated, dict) else []
        except Exception:
            hooks = []

    report = {
        "query": agent["query"],
        "objective": agent.get("objective", "hooks"),
        "objective_label": RECIPE_BY_OBJECTIVE.get(
            agent.get("objective", "hooks"), ("Pesquisa", "insight"))[0],
        "generated_at": _now(),
        "corpus": {"videos": len(videos),
                   "mediana_views": int(metrics.corpus_baseline(videos)),
                   "fonte": result["source_breakdown"]},
        "outliers": outliers,
        "facetas": result["facets"],
        "hooks_sugeridos": hooks,
        "por_plataforma": {p: sum(1 for v in videos if v["platform"] == p)
                           for p in ("tiktok", "instagram", "youtube")},
        "erros_coleta": result.get("coleta_errors", []),
    }
    report["recomendacoes"] = _recommendations(report)

    run = {"at": report["generated_at"], "duration_ms": int((_now_ts() - started) * 1000),
           "report": report, "delivery": []}

    # entrega externa (best-effort; nunca invalida a execução)
    run["delivery"] = await deliver(report, agent.get("deliver") or {})

    with _lock:
        agents = _load()
        for a in agents:
            if a.get("id") == agent["id"]:
                a["runs"] = [run] + (a.get("runs") or [])[: MAX_RUNS_KEPT - 1]
                a["last_run"] = run["at"]
                a["next_run"] = _next_run(a, started)
                _save(agents)
                break
    return {"agent_id": agent["id"], "run": run}


# ------------------------------------------------------------------ entrega
def _slack_payload(report: dict) -> dict:
    lines = [f"*{report['objective_label']}* — `{report['query']}`",
             f"{report['corpus']['videos']} vídeos analisados · "
             f"{len(report['outliers'])} outliers"]
    for r in report["recomendacoes"][:3]:
        lines.append(f"• {r['acao']} ({r['porque']})")
    return {"text": "\n".join(lines)}


def _discord_payload(report: dict) -> dict:
    embed = {
        "title": f"Radar: {report['query']}",
        "description": f"{report['corpus']['videos']} vídeos · {len(report['outliers'])} outliers",
        "fields": [{"name": f"#{r['prioridade']} {r['acao'][:100]}",
                    "value": r["porque"][:200], "inline": False}
                   for r in report["recomendacoes"][:4]],
        "color": 0xF0B429,
    }
    return {"embeds": [embed]}


async def deliver(report: dict, channels: dict) -> list[dict]:
    """POST do relatório nos canais configurados. Retorna o status de cada um."""
    targets = []
    if channels.get("webhook"):
        targets.append(("webhook", channels["webhook"], report))
    if channels.get("slack"):
        targets.append(("slack", channels["slack"], _slack_payload(report)))
    if channels.get("discord"):
        targets.append(("discord", channels["discord"], _discord_payload(report)))
    if not targets:
        return []

    async def send(name: str, url: str, payload: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.post(url, json=payload)
            return {"canal": name, "status": r.status_code, "ok": r.status_code < 400}
        except Exception as exc:
            return {"canal": name, "status": None, "ok": False, "erro": type(exc).__name__}

    return list(await asyncio.gather(*(send(n, u, p) for n, u, p in targets)))


# ------------------------------------------------------------------ agendador
def due_agents() -> list[dict]:
    now = _now()
    out = []
    for a in _load():
        if a.get("status") != "ativo":
            continue
        nxt = a.get("next_run")
        if nxt and nxt <= now:
            out.append(a)
    return out


async def scheduler_tick() -> list[dict]:
    """Roda todo agente vencido. O consumo de créditos é responsabilidade do
    endpoint/worker que chama (aqui só executamos)."""
    results = []
    for agent in due_agents():
        try:
            results.append(await run_agent(agent))
        except Exception as exc:  # agente com erro não pode parar a fila
            results.append({"agent_id": agent.get("id"), "error": type(exc).__name__})
    return results


async def scheduler_loop(interval: int = 60, max_ticks: Optional[int] = None) -> None:
    """Loop de background iniciado no startup (desligável por env)."""
    ticks = 0
    while max_ticks is None or ticks < max_ticks:
        try:
            await scheduler_tick()
        except Exception:
            pass
        ticks += 1
        await asyncio.sleep(interval)


def stats(tenant_id: str) -> dict:
    agents = [a for a in _load() if a.get("tenant") == tenant_id]
    runs = [r for a in agents for r in (a.get("runs") or [])]
    next_runs = sorted([a["next_run"] for a in agents if a.get("next_run")])
    return {
        "agentes": len(agents),
        "ativos": sum(1 for a in agents if a.get("status") == "ativo"),
        "execucoes": len(runs),
        "ultima_execucao": max((r.get("at") for r in runs), default=None),
        "proxima_execucao": next_runs[0] if next_runs else None,
    }
