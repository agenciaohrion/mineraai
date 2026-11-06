"""Retenção de dados — nada em disco cresce sem teto.

O MineraAI guarda tudo em JSON: cada busca no ledger, cada job da Fábrica, cada
Orbit minerado. Os tetos por arquivo já existiam na escrita (`MAX_JOBS = 200`,
`MAX_USAGE_EVENTS = 5000`…), mas nenhum deles tinha **prazo**: um job de três
meses atrás e um de hoje valiam o mesmo, e o vídeo em `data/media/` ficava para
sempre, mesmo depois de o job sair da lista.

Três regras, nesta ordem:

1. **Sempre manter os N mais recentes** de cada arquivo. Um teto por idade que
   apaga o que acabou de ser criado seria pior que não ter retenção.
2. **Fora isso, respeitar a janela** (`RETENTION_DIAS`, padrão 90).
3. **Item sem data nunca é apagado.** Não dá para afirmar que está velho.

**O que não é podado, de propósito:**

- **Comets** são *configuração* de monitoramento que o usuário criou — apagar por
  idade desligaria monitores sozinho. Só saem por ação explícita (`DELETE`).
- **Biblioteca** é curadoria do usuário: é ele quem remove.
- **Agents** e **tenants** são configuração comercial, não log.

Depois da poda dos JSONs vem a varredura da mídia: arquivo que não é referenciado
por nenhum job nem pela Biblioteca, e que tem mais de 24h, é órfão — sai. Como a
Biblioteca guarda a referência do arquivo, podar um job antigo **não** apaga o
vídeo que o usuário salvou.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Optional

from . import credits, media, mining, pipeline, storage

DIAS_PADRAO = 90
INTERVALO_H_PADRAO = 6
#: quantos itens sobrevivem independentemente da idade, por arquivo
MANTER = {"jobs": 5, "usage": 100, "orbits": 2, "ingested": 50}

_ultimo: dict = {}


# ------------------------------------------------------------------ config
def _cfg() -> dict:
    cfg = storage.settings_get()
    try:
        dias = int(float(cfg.get("RETENTION_DIAS") or DIAS_PADRAO))
    except (TypeError, ValueError):
        dias = DIAS_PADRAO
    try:
        intervalo = float(cfg.get("RETENTION_INTERVALO_H") or INTERVALO_H_PADRAO)
    except (TypeError, ValueError):
        intervalo = INTERVALO_H_PADRAO
    bruto = str(cfg.get("RETENTION_ENABLED") or "1").strip().lower()
    ativo = bruto not in ("0", "false", "no", "off")
    return {"ativo": ativo, "dias": max(1, dias), "intervalo_h": max(0.2, intervalo)}


def _agora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------ utilidades
def _ts(valor) -> Optional[float]:
    """Converte epoch ou ISO-8601 (`2026-11-06T12:00:00Z`) em epoch."""
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("Z", "+00:00")
    try:
        return time.mktime(time.strptime(texto[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except ValueError:
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(texto).timestamp()
    except ValueError:
        return None


def _ts_item(item: dict, campos: Iterable[str]) -> Optional[float]:
    for campo in campos:
        ts = _ts(item.get(campo))
        if ts is not None:
            return ts
    return None


def _poda(path: Path, *, dias: int, manter: int,
          campos: Iterable[str], truncar: Optional[int] = None) -> dict:
    """Aplica as três regras a um arquivo JSON em lista.

    A lista é sempre escrita do mais novo para o mais velho — a mesma ordem que
    `_read`/`insert(0, …)` usam no resto do projeto.
    """
    campos = tuple(campos)
    with storage._lock:
        itens = storage._read(path, [])
        if not isinstance(itens, list) or not itens:
            return {"removidos": 0, "restantes": 0, "bytes_livres": 0}

        try:
            antes = path.stat().st_size
        except OSError:
            antes = 0

        # mais novo primeiro; o que não tem data vai para o fim (nunca expira)
        def chave_ordem(item: dict):
            ts = _ts_item(item, campos)
            # maior ts primeiro; sem data vai para o fim da fila
            return -ts if ts is not None else float("inf")

        ordenados = sorted(itens, key=chave_ordem)
        corte = time.time() - dias * 86400
        mantidos: list[dict] = []
        removidos = 0
        for idx, item in enumerate(ordenados):
            if idx < manter:
                mantidos.append(item)
                continue
            ts = _ts_item(item, campos)
            if ts is None or ts >= corte:
                mantidos.append(item)
            else:
                removidos += 1

        if truncar is not None and len(mantidos) > truncar:
            removidos += len(mantidos) - truncar
            mantidos = mantidos[:truncar]

        if removidos:
            storage._write(path, mantidos)

        try:
            depois = path.stat().st_size if path.exists() else 0
        except OSError:
            depois = 0

    return {"removidos": removidos, "restantes": len(mantidos),
            "bytes_livres": max(0, antes - depois)}


def _referencias_de_midia() -> set[str]:
    """Todo arquivo que ainda tem dono (job ou item da Biblioteca)."""
    refs: set[str] = set()
    for job in pipeline.jobs_list():
        arq = (job.get("media") or {}).get("file")
        if arq:
            refs.add(arq)
    for item in storage.library_list():
        arq = (item.get("payload") or {}).get("file")
        if arq:
            refs.add(arq)
    return refs


# ------------------------------------------------------------------ execução
def run(force: bool = False) -> dict:
    """Executa a manutenção. `force=True` ignora `RETENTION_ENABLED`."""
    global _ultimo
    cfg = _cfg()
    if not cfg["ativo"] and not force:
        return {"ok": True, "executado": False,
                "motivo": "retenção desligada (RETENTION_ENABLED=0)",
                "quando": _agora()}

    dias = cfg["dias"]
    relatorio: dict = {"executado": True, "dias": dias, "removidos": {},
                       "bytes_livres": 0, "quando": _agora()}

    alvos = [
        ("jobs", pipeline.JOBS_FILE, ("created_at", "updated_at"), pipeline.MAX_JOBS),
        ("usage", credits.USAGE_FILE, ("ts",), credits.MAX_USAGE_EVENTS),
        ("orbits", mining.ORBITS_FILE, ("created_at",), mining.MAX_ORBITS),
        # comets ficam de fora: são configuração de monitor, não log
        ("ingested", mining.INGEST_FILE, ("ingested_at", "observed_at"), 2000),
    ]
    for nome, arquivo, campos, teto in alvos:
        try:
            r = _poda(arquivo, dias=dias, manter=MANTER.get(nome, 5),
                      campos=campos, truncar=teto)
        except Exception as exc:                      # um arquivo corrompido não trava o resto
            r = {"removidos": 0, "restantes": 0, "bytes_livres": 0, "erro": str(exc)}
        relatorio["removidos"][nome] = r["removidos"]
        relatorio["bytes_livres"] += r.get("bytes_livres", 0)

    try:
        orfaos = media.prune_orphans(_referencias_de_midia())
    except Exception as exc:
        orfaos = {"removidos": 0, "bytes_livres": 0, "erro": str(exc)}

    relatorio["removidos"]["arquivos"] = orfaos["removidos"]
    relatorio["bytes_livres"] += orfaos["bytes_livres"]
    relatorio["total_removidos"] = sum(relatorio["removidos"].values())
    relatorio["mb_livres"] = round(relatorio["bytes_livres"] / (1024 * 1024), 2)
    relatorio["midia"] = media.usage()
    _ultimo = relatorio
    return relatorio


def status() -> dict:
    """Estado atual: configuração, último relatório e uso de disco."""
    cfg = _cfg()
    return {
        "config": cfg,
        "ultimo": _ultimo or None,
        "midia": media.usage(),
        "contagens": {
            "jobs": len(pipeline.jobs_list()),
            "orbits": len(mining._orbits()),
            "comets": len(mining._comets()),
            "ingeridos": len(mining._ingested()),
            "eventos_de_uso": len(storage._read(credits.USAGE_FILE, [])),
            "biblioteca": len(storage.library_list()),
        },
    }


async def loop(intervalo_h: Optional[float] = None) -> None:
    """Roda a manutenção em background (chamado no startup do app)."""
    import asyncio
    espera = (intervalo_h if intervalo_h is not None else _cfg()["intervalo_h"]) * 3600
    # primeira passada logo no boot: instalação antiga já entra limpa
    await asyncio.to_thread(run)
    while True:
        await asyncio.sleep(espera)
        try:
            await asyncio.to_thread(run)
        except Exception:                             # nunca derruba o app
            continue
