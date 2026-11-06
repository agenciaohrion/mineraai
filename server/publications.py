"""Publicações — o passo que fecha o loop.

O ciclo do produto era *descobrir → validar → roteiro → produzir* e parava aí.
Este módulo faz os dois passos que faltavam:

    produzir  →  PUBLICAR (YouTube, via OAuth do canal)
    publicar  →  MEDIR (views/likes/comentários em série temporal)
    medir     →  REALIMENTAR (o vídeo publicado entra no corpus da mineração)

A realimentação não é simbólica: `sincronizar()` empurra o desempenho real do
nosso vídeo para `mining.ingest_videos(..., "publicado", substituir=True)`. A
partir daí ele participa do mesmo `outlier_score` que usamos para descobrir
tendências — ou seja, o baseline do nicho passa a conter o que a gente publicou,
e não só o que os outros publicaram.

Uma escolha deliberada: **privacidade padrão é `unlisted`**. Publicar em público
é decisão explícita, nunca efeito colateral de um clique.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

from . import mining, storage, youtube

PUBLICATIONS_FILE = storage.DATA_DIR / "publications.json"
MAX_PUBLICATIONS = 500
MAX_SNAPSHOTS = 200          # ~8 dias com leitura de hora em hora
JANELA_PADRAO_DIAS = 7       # por quanto tempo continuamos medindo
INTERVALO_PADRAO_H = 6.0


class PublicacaoError(Exception):
    """Falha ao publicar ou sincronizar (mensagem pronta para a UI)."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _ts(valor: str | float | None) -> Optional[float]:
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return time.mktime(time.strptime(str(valor)[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone
    except ValueError:
        return None


def _cfg() -> dict:
    c = storage.settings_get()
    try:
        janela = int(float(c.get("PUBLISH_JANELA_DIAS") or JANELA_PADRAO_DIAS))
    except (TypeError, ValueError):
        janela = JANELA_PADRAO_DIAS
    try:
        intervalo = float(c.get("PUBLISH_SYNC_INTERVALO_H") or INTERVALO_PADRAO_H)
    except (TypeError, ValueError):
        intervalo = INTERVALO_PADRAO_H
    return {"janela_dias": max(1, janela), "intervalo_h": max(0.2, intervalo)}


# ------------------------------------------------------------------ persistência
def _pubs() -> list[dict]:
    data = storage._read(PUBLICATIONS_FILE, [])
    return data if isinstance(data, list) else []


def _save(pubs: list[dict]) -> None:
    storage._write(PUBLICATIONS_FILE, pubs[:MAX_PUBLICATIONS])


def listar(tenant_id: Optional[str] = None) -> list[dict]:
    pubs = _pubs()
    if tenant_id:
        pubs = [p for p in pubs if p.get("tenant") == tenant_id]
    return pubs


def obter(pub_id: str, tenant_id: Optional[str] = None) -> Optional[dict]:
    for p in _pubs():
        if p["id"] == pub_id and (not tenant_id or p.get("tenant") == tenant_id):
            return p
    return None


def apagar(pub_id: str, tenant_id: str) -> bool:
    with storage._lock:
        pubs = _pubs()
        # apagar aqui NÃO remove o vídeo do YouTube — só o nosso registro
        kept = [p for p in pubs if not (p["id"] == pub_id and p.get("tenant") == tenant_id)]
        if len(kept) == len(pubs):
            return False
        _save(kept)
        return True


# ------------------------------------------------------------------ publicação
def publicar(tenant_id: str, job: dict, titulo: str, descricao: str = "",
             tags: Optional[list[str]] = None, privacidade: str = "unlisted",
             made_for_kids: bool = False) -> dict:
    """Sobe o arquivo local do job no canal e registra a publicação."""
    arquivo = (job.get("media") or {}).get("file")
    if not arquivo:
        raise PublicacaoError(
            "Este job não tem arquivo salvo no servidor. Publique só depois de "
            "o vídeo estar em data/media (veja media_error no job).")
    from . import media
    info = media.info_arquivo(arquivo)
    if not info:
        raise PublicacaoError("O arquivo do job desapareceu do disco — gere o vídeo de novo.")

    if not youtube.authorized():
        raise PublicacaoError(
            "Nenhum canal do YouTube autorizado. Use o botão Autorizar em "
            "APIs & Conexões → Canal do YouTube.")

    try:
        up = youtube.upload(info["path"], titulo, descricao, tags, privacidade,
                            made_for_kids)
    except youtube.YouTubeError as exc:
        raise PublicacaoError(str(exc)) from exc

    pub = {
        "id": f"pub-{uuid.uuid4().hex[:10]}",
        "tenant": tenant_id or "demo",
        "job_id": job.get("id"),
        "video_id": up["video_id"],
        "url": up["url"],
        "titulo": up["titulo"],
        "descricao": descricao,
        "tags": tags or [],
        "privacidade": up.get("privacidade") or privacidade,
        "arquivo": arquivo,
        "bytes": up.get("bytes"),
        "publicado_at": _now(),
        "status": "publicado",
        "snapshots": [],
        "ultima_leitura": None,
        "erro": None,
    }
    with storage._lock:
        pubs = _pubs()
        pubs.insert(0, pub)
        _save(pubs)

    # primeira leitura logo após publicar (o vídeo nasce com 0 views)
    try:
        sincronizar(pub["id"])
    except (PublicacaoError, youtube.YouTubeError):
        pass       # publicar funcionou; medir pode esperar o próximo ciclo
    return obter(pub["id"]) or pub


# ------------------------------------------------------------------ medição
def _idade_horas(pub: dict) -> float:
    ts = _ts(pub.get("publicado_at"))
    if not ts:
        return 0.0
    return max(0.0, (time.time() - ts) / 3600)


def _registrar_snapshot(pub: dict, dados: dict) -> dict:
    snap = {
        "at": _now(),
        "views": int(dados.get("views") or 0),
        "likes": int(dados.get("likes") or 0),
        "comments": int(dados.get("comments") or 0),
        "idade_h": round(_idade_horas(pub), 2),
    }
    serie = list(pub.get("snapshots") or [])
    serie.append(snap)
    pub["snapshots"] = serie[-MAX_SNAPSHOTS:]
    pub["ultima_leitura"] = snap["at"]
    pub["status"] = "publicado"
    pub["erro"] = None
    if dados.get("privacidade"):
        pub["privacidade"] = dados["privacidade"]
    return snap


def _realimentar_corpus(pub: dict) -> None:
    """Manda o desempenho real do vídeo para o corpus da mineração.

    `substituir=True)` faz a entrada ser atualizada em vez de duplicada — o
    mesmo vídeo medido cinco vezes é um registro com o número mais recente.
    """
    ultimo = (pub.get("snapshots") or [{}])[-1]
    if not ultimo:
        return
    canal = pub.get("canal") or (youtube.canal() or {}).get("titulo") or "canal próprio"
    item = {
        "id": pub.get("video_id"),
        "platform": "youtube",
        "title": pub.get("titulo") or "",
        "handle": f"@{str(canal).replace(' ', '').lower()}" if canal else "@canal",
        "views": ultimo.get("views", 0),
        "likes": ultimo.get("likes", 0),
        "comments": ultimo.get("comments", 0),
        "shares": 0,
        "age_hours": ultimo.get("idade_h", 0) or 0,
        "url": pub.get("url"),
        "sound": None,
        "hashtags": pub.get("tags") or [],
    }
    try:
        mining.ingest_videos([item], "publicado", substituir=True)
    except Exception:
        pass        # corpus é secundário: não pode derrubar a publicação


def sincronizar(pub_id: str, tenant_id: Optional[str] = None) -> dict:
    """Lê as métricas atuais no YouTube, empilha o snapshot e realimenta o corpus."""
    pub = obter(pub_id, tenant_id)
    if not pub:
        raise PublicacaoError("Publicação não encontrada.")
    try:
        dados = youtube.video_stats([pub["video_id"]]).get(pub["video_id"])
    except youtube.YouTubeError as exc:
        with storage._lock:
            pubs = _pubs()
            for p in pubs:
                if p["id"] == pub_id:
                    p["erro"] = str(exc)
                    p["ultima_leitura"] = _now()
            _save(pubs)
        raise PublicacaoError(str(exc)) from exc

    if not dados:
        # vídeo removido do canal (ou token sem acesso a ele)
        with storage._lock:
            pubs = _pubs()
            for p in pubs:
                if p["id"] == pub_id:
                    p["status"] = "indisponivel"
                    p["erro"] = "O YouTube não devolveu este vídeo (removido ou privado)."
                    p["ultima_leitura"] = _now()
            _save(pubs)
        raise PublicacaoError("O YouTube não devolveu este vídeo (removido ou privado).")

    with storage._lock:
        pubs = _pubs()
        alvo = next((p for p in pubs if p["id"] == pub_id), None)
        if not alvo:
            raise PublicacaoError("Publicação não encontrada.")
        _registrar_snapshot(alvo, dados)
        _save(pubs)
        atual = dict(alvo)

    _realimentar_corpus(atual)
    return obter(pub_id) or atual


def sincronizar_tudo(tenant_id: Optional[str] = None) -> dict:
    """Sincroniza as publicações dentro da janela de acompanhamento."""
    janela = _cfg()["janela_dias"]
    agora = time.time()
    alvos = []
    for p in listar(tenant_id):
        if p.get("status") == "indisponivel":
            continue
        publicado = _ts(p.get("publicado_at"))
        if publicado and (agora - publicado) > janela * 86400:
            continue        # fora da janela: o vídeo já está "estável"
        alvos.append(p)

    ok, falhas = 0, []
    for p in alvos:
        try:
            sincronizar(p["id"])
            ok += 1
        except PublicacaoError as exc:
            falhas.append({"id": p["id"], "erro": str(exc)})
    return {"ok": True, "sincronizados": ok, "falhas": falhas,
            "total": len(alvos), "janela_dias": janela, "quando": _now()}


# ------------------------------------------------------------------ resumo
def resumo(tenant_id: Optional[str] = None) -> dict:
    """Números do canal: totais, melhor vídeo e comparação com o corpus."""
    pubs = [p for p in listar(tenant_id) if p.get("status") != "indisponivel"]
    if not pubs:
        return {"publicados": 0, "views_total": 0, "likes_total": 0,
                "comentarios_total": 0, "melhor": None, "serie": [],
                "janela_dias": _cfg()["janela_dias"], "canal": youtube.canal()}

    linhas = []
    for p in pubs:
        ultimo = (p.get("snapshots") or [{}])[-1]
        linhas.append({
            "id": p["id"], "titulo": p.get("titulo"), "url": p.get("url"),
            "views": ultimo.get("views", 0), "likes": ultimo.get("likes", 0),
            "comments": ultimo.get("comments", 0),
            "idade_h": ultimo.get("idade_h", 0),
            "velocidade": round((ultimo.get("views", 0) /
                                 max(1.0, ultimo.get("idade_h", 1) or 1)), 2),
            "privacidade": p.get("privacidade"),
        })
    melhor = max(linhas, key=lambda x: x["views"])
    return {
        "publicados": len(pubs),
        "views_total": sum(l["views"] for l in linhas),
        "likes_total": sum(l["likes"] for l in linhas),
        "comentarios_total": sum(l["comments"] for l in linhas),
        "melhor": melhor,
        "serie": linhas,
        "janela_dias": _cfg()["janela_dias"],
        "canal": youtube.canal(),
        "no_corpus": sum(1 for v in mining._ingested()
                         if str(v.get("source")) == "publicado"),
    }


# ------------------------------------------------------------------ agendador
async def loop(intervalo_h: Optional[float] = None) -> None:
    """Mede as publicações em background, enquanto estiverem na janela."""
    import asyncio
    espera = (intervalo_h if intervalo_h is not None else _cfg()["intervalo_h"]) * 3600
    while True:
        await asyncio.sleep(espera)
        try:
            if storage.settings_get().get("PUBLISH_SYNC", "1") == "0" or not youtube.authorized():
                continue
            await asyncio.to_thread(sincronizar_tudo)
        except Exception:
            continue
