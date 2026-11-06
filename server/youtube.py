"""Canal do YouTube — OAuth do dono, upload de vídeo e leitura de métricas.

Separação importante em relação a `providers.py`: lá a chave de **API** (pública)
serve para *ler* o YouTube de qualquer um; aqui é o **OAuth** do dono do canal
que permite *escrever* (upload) e ler as estatísticas privadas do próprio vídeo.

Fluxo (authorization_code com refresh):

    GET  /api/integrations/youtube/authorize     -> URL de consentimento
    GET  /api/integrations/youtube/callback      -> Google devolve o navegador
                                                    com ?code= -> troca por tokens
    POST /api/integrations/youtube/refresh       -> renovação manual

Upload usa o protocolo **resumable** em duas chamadas:

    1. POST .../upload/youtube/v3/videos?uploadType=resumable&part=snippet,status
       -> 200, header `Location` = URL de sessão
    2. PUT  <Location>  (bytes do arquivo)
       -> 200, corpo com o `id` do vídeo criado

O passo 2 é feito com `httpx.Client` (síncrono) dentro de uma thread — mandar um
arquivo de centenas de MB por cliente assíncrono exigiria iterar o arquivo em
pedaços na mão, e o ganho seria nulo porque quem espera é a GPU do Google.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import httpx

from . import storage

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

TIMEOUT = 60.0
REDIRECT_PADRAO = "http://localhost:8000/api/integrations/youtube/callback"
PRIVACIDADES = ("private", "unlisted", "public")


class YouTubeError(Exception):
    """Falha no OAuth, no upload ou na leitura de métricas."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


# ------------------------------------------------------------------ config
def _cfg() -> dict:
    return storage.settings_get()


def redirect_uri() -> str:
    return (_cfg().get("YOUTUBE_REDIRECT_URI") or REDIRECT_PADRAO).strip()


def configured() -> bool:
    """Tem app OAuth (client id + secret) para iniciar o consentimento?"""
    c = _cfg()
    return bool(c.get("YOUTUBE_CLIENT_ID") and c.get("YOUTUBE_CLIENT_SECRET"))


def authorized() -> bool:
    """Já temos refresh token de um canal?"""
    return bool(_cfg().get("YOUTUBE_REFRESH_TOKEN"))


def canal() -> dict:
    """Info do canal conectado (guardada no momento da autorização)."""
    c = _cfg()
    return {"id": c.get("YOUTUBE_CHANNEL_ID") or "",
            "titulo": c.get("YOUTUBE_CHANNEL_TITLE") or "",
            "conectado": authorized()}


def status_resumo() -> dict:
    c = canal()
    return {
        "grupo": "producao",
        "oficial": "YouTube — upload (OAuth do canal)",
        "conectado": authorized(),
        "custo": "Gratuita · 1 upload ≈ 1.600 unidades das 10.000/dia",
        "canal": c["titulo"] or None,
        "redirect_uri": redirect_uri(),
    }


# ------------------------------------------------------------------ OAuth
def authorize_url(state: str = "mineraai") -> dict:
    """URL de consentimento. `access_type=offline` é o que devolve refresh token."""
    if not configured():
        return {"ok": False,
                "message": "Preencha Client ID e Client Secret do app OAuth do Google."}
    from urllib.parse import urlencode
    params = {
        "client_id": _cfg()["YOUTUBE_CLIENT_ID"],
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",      # sem isto não vem refresh token
        "prompt": "consent",           # força reconsentimento -> refresh token novo
        "include_granted_scopes": "true",
        "state": state,
    }
    return {"ok": True, "url": f"{AUTH_URL}?{urlencode(params)}",
            "redirect_uri": redirect_uri(), "scopes": SCOPES}


def _guardar_token(payload: dict) -> dict:
    """Persiste os tokens e a validade. O refresh token só vem na 1ª autorização."""
    agora = int(time.time())
    expira = agora + int(payload.get("expires_in") or 3600)
    patch = {"YOUTUBE_ACCESS_TOKEN": payload.get("access_token", ""),
             "YOUTUBE_TOKEN_EXPIRES_AT": str(expira)}
    if payload.get("refresh_token"):
        patch["YOUTUBE_REFRESH_TOKEN"] = payload["refresh_token"]
    storage.settings_save(patch)
    return {"expira_em": expira, "escopo": payload.get("scope", ""),
            "tem_refresh": bool(payload.get("refresh_token"))}


def _token_request(data: dict) -> dict:
    """Chamada ao endpoint de token (código por autorização ou refresh)."""
    if not configured():
        raise YouTubeError("Configure Client ID e Client Secret do app OAuth do Google.")
    data = {**data, "client_id": _cfg()["YOUTUBE_CLIENT_ID"],
            "client_secret": _cfg()["YOUTUBE_CLIENT_SECRET"]}
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            r = cli.post(TOKEN_URL, data=data)
    except httpx.HTTPError as exc:
        raise YouTubeError(f"falha de rede ao falar com o Google: {exc}") from exc

    if r.status_code >= 400:
        detalhe = ""
        try:
            detalhe = (r.json().get("error_description")
                       or r.json().get("error") or "")
        except Exception:
            detalhe = r.text[:160]
        if r.status_code in (400, 401):
            raise YouTubeError(
                f"Google recusou a autorização: {detalhe or 'código inválido ou expirado'}. "
                "Autorize novamente pelo botão do app.", r.status_code)
        raise YouTubeError(f"Google respondeu {r.status_code}: {detalhe}", r.status_code)
    return r.json()


def exchange_code(code: str) -> dict:
    """Troca o `?code` do redirect por access + refresh token e lê o canal."""
    if not code:
        raise YouTubeError("Código de autorização vazio.")
    payload = _token_request({"code": code, "grant_type": "authorization_code",
                              "redirect_uri": redirect_uri()})
    info = _guardar_token(payload)
    try:
        c = channel_info()
        storage.settings_save({"YOUTUBE_CHANNEL_ID": c.get("id", ""),
                               "YOUTUBE_CHANNEL_TITLE": c.get("titulo", "")})
        info["canal"] = c
    except YouTubeError:
        info["canal"] = None      # token serve, mas o canal não pôde ser lido
    return {"ok": True, **info}


def refresh() -> dict:
    """Renova o access token com o refresh token salvo."""
    refresh_token = _cfg().get("YOUTUBE_REFRESH_TOKEN")
    if not refresh_token:
        raise YouTubeError("Nenhum canal autorizado — use o botão Autorizar.")
    payload = _token_request({"refresh_token": refresh_token,
                              "grant_type": "refresh_token"})
    return _guardar_token(payload)


def access_token(force: bool = False) -> str:
    """Token de acesso válido, renovando quando faltam 60 s."""
    c = _cfg()
    token = c.get("YOUTUBE_ACCESS_TOKEN") or ""
    try:
        expira = int(float(c.get("YOUTUBE_TOKEN_EXPIRES_AT") or 0))
    except (TypeError, ValueError):
        expira = 0
    if token and not force and expira - 60 > time.time():
        return token
    if not c.get("YOUTUBE_REFRESH_TOKEN"):
        if token and not force:
            return token
        raise YouTubeError("Nenhum canal autorizado — use o botão Autorizar.")
    refresh()
    return _cfg().get("YOUTUBE_ACCESS_TOKEN", "")


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {access_token()}"}


def _erro_api(r: httpx.Response, acao: str) -> YouTubeError:
    detalhe = ""
    try:
        err = (r.json() or {}).get("error") or {}
        detalhe = err.get("message") or ""
    except Exception:
        detalhe = r.text[:200]
    if r.status_code == 401:
        return YouTubeError(
            f"{acao}: token recusado ({detalhe or 'expirado'}). "
            "Renove a autorização do canal.", 401)
    if r.status_code == 403 and "quota" in detalhe.lower():
        return YouTubeError(
            f"{acao}: cota diária do YouTube esgotada ({detalhe}). "
            "Reseta à meia-noite no horário do Pacífico.", 403)
    return YouTubeError(f"{acao}: HTTP {r.status_code} — {detalhe[:200]}", r.status_code)


def channel_info() -> dict:
    """Canal dono do token: id, título, inscritos e views totais."""
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            r = cli.get(f"{API}/channels",
                        params={"part": "snippet,statistics", "mine": "true"},
                        headers=_auth_headers())
    except httpx.HTTPError as exc:
        raise YouTubeError(f"falha de rede ao ler o canal: {exc}") from exc
    if r.status_code >= 400:
        raise _erro_api(r, "Ler canal")
    itens = (r.json() or {}).get("items") or []
    if not itens:
        raise YouTubeError("O token não deu acesso a nenhum canal do YouTube.")
    it = itens[0]
    st = it.get("statistics") or {}
    return {
        "id": it.get("id", ""),
        "titulo": (it.get("snippet") or {}).get("title", ""),
        "inscritos": int(st.get("subscriberCount") or 0),
        "videos": int(st.get("videoCount") or 0),
        "views": int(st.get("viewCount") or 0),
    }


# ------------------------------------------------------------------ upload
def upload(file_path: str | Path, title: str, description: str = "",
           tags: Optional[list[str]] = None, privacy: str = "unlisted",
           made_for_kids: bool = False, categoria: str = "22") -> dict:
    """Sobe o arquivo local e devolve os dados do vídeo criado.

    `privacy` padrão é `unlisted` de propósito: publicar em público é decisão
    explícita do usuário, nunca efeito colateral de um clique em "publicar".
    """
    caminho = Path(file_path)
    if not caminho.is_file():
        raise YouTubeError("Arquivo do vídeo não encontrado no servidor.")
    if privacy not in PRIVACIDADES:
        raise YouTubeError(f"Privacidade inválida: use {', '.join(PRIVACIDADES)}.")
    if not title.strip():
        raise YouTubeError("O título é obrigatório.")

    corpo = {
        "snippet": {
            "title": title.strip()[:100],
            "description": (description or "")[:5000],
            "tags": [t for t in (tags or []) if t][:30],
            "categoryId": str(categoria),
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }

    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            # 1) abre a sessão resumable
            r = cli.post(f"{UPLOAD}?uploadType=resumable&part=snippet,status",
                         json=corpo,
                         headers={**_auth_headers(),
                                  "X-Upload-Content-Type": "video/*",
                                  "X-Upload-Content-Length": str(caminho.stat().st_size)})
            if r.status_code >= 400:
                raise _erro_api(r, "Iniciar upload")
            location = r.headers.get("location") or r.headers.get("Location")
            if not location:
                raise YouTubeError("O Google não devolveu a URL de upload "
                                   "(resposta sem header Location).")

            # 2) envia os bytes na sessão aberta
            with caminho.open("rb") as fh:
                r2 = cli.put(location, content=fh,
                             headers={"Content-Type": "video/*"},
                             timeout=None)
    except httpx.HTTPError as exc:
        raise YouTubeError(f"falha de rede durante o upload: {exc}") from exc

    if r2.status_code >= 400:
        raise _erro_api(r2, "Enviar vídeo")

    dados = r2.json() or {}
    vid = dados.get("id")
    if not vid:
        raise YouTubeError("O upload terminou sem id de vídeo na resposta.")
    status = dados.get("status") or {}
    return {
        "video_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "titulo": (dados.get("snippet") or {}).get("title", title),
        "privacidade": status.get("privacyStatus", privacy),
        "upload_status": status.get("uploadStatus"),
        "bytes": caminho.stat().st_size,
    }


# ------------------------------------------------------------------ métricas
def video_stats(video_ids: list[str]) -> dict[str, dict]:
    """Estatísticas atuais dos vídeos (até 50 por chamada)."""
    ids = [v for v in dict.fromkeys(video_ids) if v][:50]
    if not ids:
        return {}
    try:
        with httpx.Client(timeout=TIMEOUT) as cli:
            r = cli.get(f"{API}/videos",
                        params={"part": "statistics,snippet,status",
                                "id": ",".join(ids)},
                        headers=_auth_headers())
    except httpx.HTTPError as exc:
        raise YouTubeError(f"falha de rede ao ler métricas: {exc}") from exc
    if r.status_code >= 400:
        raise _erro_api(r, "Ler métricas")

    out: dict[str, dict] = {}
    for it in (r.json() or {}).get("items") or []:
        st = it.get("statistics") or {}
        out[it.get("id", "")] = {
            "views": int(st.get("viewCount") or 0),
            "likes": int(st.get("likeCount") or 0),
            "comments": int(st.get("commentCount") or 0),
            "titulo": (it.get("snippet") or {}).get("title", ""),
            "canal": (it.get("snippet") or {}).get("channelTitle", ""),
            "publicado_em": (it.get("snippet") or {}).get("publishedAt", ""),
            "privacidade": (it.get("status") or {}).get("privacyStatus", ""),
        }
    return out
