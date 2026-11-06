"""Testes offline da publicação no YouTube e da realimentação do corpus.

Sem rede: `httpx.Client` é substituído por um dublê que responde em sequência
(token → canal → upload → métricas), exercitando os mesmos payloads e headers
que o Google recebe.

    .venv/bin/python -m server.tests_publicacao
"""
from __future__ import annotations

import asyncio
import atexit
import json
import shutil
import tempfile
import time
from pathlib import Path

import httpx

from server import media, mining, pipeline, publications, retention, storage, youtube

# --------------------------------------------------- isolamento do estado em disco
_TMP = Path(tempfile.mkdtemp(prefix="mineraai-pub-"))
atexit.register(shutil.rmtree, _TMP, True)

storage.DATA_DIR = _TMP
storage.SETTINGS_FILE = _TMP / "settings.json"
storage.LIBRARY_FILE = _TMP / "library.json"
media.MEDIA_DIR = _TMP / "media"
pipeline.JOBS_FILE = _TMP / "jobs.json"
mining.INGEST_FILE = _TMP / "ingested.json"
mining.ORBITS_FILE = _TMP / "orbits.json"
mining.COMETS_FILE = _TMP / "comets.json"
publications.PUBLICATIONS_FILE = _TMP / "publications.json"

MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 512


def _cfg(**kw):
    storage.settings_save({k: str(v) for k, v in kw.items()})


# ================================================================ dublê HTTP (sync)
class R:
    def __init__(self, status_code: int = 200, payload=None, headers=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text or json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("sem json")
        return self._payload


class Cliente:
    """Substitui httpx.Client: consome uma fila de respostas e grava as chamadas."""

    respostas: list = []
    chamadas: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def _prox(self, method, url, **kw):
        Cliente.chamadas.append({"method": method, "url": str(url), **{
            k: v for k, v in kw.items() if k in ("json", "data", "params", "headers", "content")
        }})
        if not Cliente.respostas:
            return R(500, {"error": {"message": "sem resposta programada"}})
        return Cliente.respostas.pop(0)

    def get(self, url, **kw):
        return self._prox("GET", url, **kw)

    def post(self, url, **kw):
        return self._prox("POST", url, **kw)

    def put(self, url, **kw):
        return self._prox("PUT", url, **kw)


class cenário:
    def __init__(self, *respostas):
        Cliente.chamadas = []
        Cliente.respostas = list(respostas)

    def __enter__(self):
        self._orig = httpx.Client
        httpx.Client = Cliente
        return self

    def __exit__(self, *a):
        httpx.Client = self._orig
        return False


def _autorizado():
    _cfg(YOUTUBE_CLIENT_ID="cid.apps.googleusercontent.com",
         YOUTUBE_CLIENT_SECRET="segredo",
         YOUTUBE_REDIRECT_URI="https://app.example/api/integrations/youtube/callback",
         YOUTUBE_REFRESH_TOKEN="1//refresh",
         YOUTUBE_ACCESS_TOKEN="ya29.acesso",
         YOUTUBE_TOKEN_EXPIRES_AT=str(int(time.time()) + 3600),
         YOUTUBE_CHANNEL_ID="UC123", YOUTUBE_CHANNEL_TITLE="Canal Teste")


# ================================================================ OAuth
def test_authorize_url():
    _cfg(YOUTUBE_CLIENT_ID="", YOUTUBE_CLIENT_SECRET="")
    r = youtube.authorize_url()
    assert r["ok"] is False and "Client ID" in r["message"]

    _cfg(YOUTUBE_CLIENT_ID="cid.apps", YOUTUBE_CLIENT_SECRET="s3cr3t",
         YOUTUBE_REDIRECT_URI="https://app.example/api/integrations/youtube/callback")
    r = youtube.authorize_url("xyz")
    assert r["ok"] is True
    url = r["url"]
    assert "client_id=cid.apps" in url
    assert "access_type=offline" in url, "sem offline não vem refresh token"
    assert "prompt=consent" in url
    assert "youtube.upload" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example" in url
    assert "state=xyz" in url
    print("ok oauth: URL de consentimento com escopo de upload e offline")


def test_exchange_code_guarda_tokens_e_canal():
    _cfg(YOUTUBE_CLIENT_ID="cid", YOUTUBE_CLIENT_SECRET="sec",
         YOUTUBE_REDIRECT_URI="https://app/cb")
    token = R(200, {"access_token": "ya29.novo", "refresh_token": "1//tok",
                    "expires_in": 3600, "scope": " ".join(youtube.SCOPES)})
    canal = R(200, {"items": [{"id": "UC999",
                               "snippet": {"title": "Meu Canal"},
                               "statistics": {"subscriberCount": "1234",
                                              "videoCount": "56", "viewCount": "78900"}}]})
    with cenário(token, canal):
        res = youtube.exchange_code("4/codigo")

    assert res["ok"] is True and res["tem_refresh"] is True
    assert res["canal"]["titulo"] == "Meu Canal"
    cfg = storage.settings_get()
    assert cfg["YOUTUBE_REFRESH_TOKEN"] == "1//tok"
    assert cfg["YOUTUBE_CHANNEL_ID"] == "UC999"
    assert cfg["YOUTUBE_CHANNEL_TITLE"] == "Meu Canal"
    # o POST de token leva o código e o redirect_uri exato da autorização
    chamada = [c for c in Cliente.chamadas if "oauth2" in c["url"]][0]
    assert chamada["data"]["grant_type"] == "authorization_code"
    assert chamada["data"]["redirect_uri"] == "https://app/cb"
    assert chamada["data"]["client_secret"] == "sec"
    print("ok oauth: code vira refresh token + dados do canal salvos")


def test_exchange_code_recusado():
    _cfg(YOUTUBE_CLIENT_ID="cid", YOUTUBE_CLIENT_SECRET="sec")
    with cenário(R(400, {"error": "invalid_grant",
                         "error_description": "Bad Request"})):
        try:
            youtube.exchange_code("codigo-velho")
        except youtube.YouTubeError as exc:
            assert "invalid_grant" in str(exc) or "Bad Request" in str(exc)
            assert "Autorize novamente" in str(exc)
        else:
            raise AssertionError("código inválido deveria levantar YouTubeError")
    print("ok oauth: código expirado explica o que fazer")


def test_access_token_renova_sozinho():
    _cfg(YOUTUBE_CLIENT_ID="cid", YOUTUBE_CLIENT_SECRET="sec",
         YOUTUBE_REFRESH_TOKEN="1//r", YOUTUBE_ACCESS_TOKEN="velho",
         YOUTUBE_TOKEN_EXPIRES_AT="1")
    with cenário(R(200, {"access_token": "ya29.fresco", "expires_in": 3600})):
        token = youtube.access_token()
    assert token == "ya29.fresco"
    assert storage.settings_get()["YOUTUBE_ACCESS_TOKEN"] == "ya29.fresco"
    print("ok oauth: token expirado é renovado com o refresh token")


# ================================================================ upload
def _job_com_arquivo():
    job = pipeline.job_create("garrafa térmica", "cena 1", "dark", 6, tenant_id="demo")
    info = media.save_base64(__import__("base64").b64encode(MP4).decode(), "demo", job["id"])
    return pipeline.job_update(job["id"], {"status": "pronto", "media": info})


def test_upload_resumable():
    _autorizado()
    job = _job_com_arquivo()
    inicio = R(200, {}, headers={"Location": "https://upload.example/sessao/123"})
    fim = R(200, {"id": "abc123XYZ", "snippet": {"title": "Garrafa"},
                  "status": {"privacyStatus": "unlisted", "uploadStatus": "uploaded"}})
    with cenário(inicio, fim):
        up = youtube.upload(media.resolve(job["media"]["file"]), "Garrafa térmica 24h",
                            "descrição", ["garrafa", "skincare"], "unlisted", False)

    assert up["video_id"] == "abc123XYZ"
    assert up["url"].endswith("watch?v=abc123XYZ")
    assert up["privacidade"] == "unlisted"

    abertura = Cliente.chamadas[0]
    assert "uploadType=resumable" in abertura["url"]
    assert abertura["json"]["snippet"]["title"] == "Garrafa térmica 24h"
    assert abertura["json"]["status"]["privacyStatus"] == "unlisted"
    assert abertura["headers"]["Authorization"] == "Bearer ya29.acesso"
    # o PUT foi para a URL de sessão devolvida pelo Google
    envio = Cliente.chamadas[1]
    assert envio["method"] == "PUT" and envio["url"] == "https://upload.example/sessao/123"
    print("ok upload: sessão resumable aberta e bytes enviados para o Location")


def test_upload_privacidade_padrao_unlisted():
    _autorizado()
    job = _job_com_arquivo()
    with cenário(R(200, {}, headers={"Location": "https://u/x"}),
                 R(200, {"id": "v1", "snippet": {"title": "t"}, "status": {}})):
        youtube.upload(media.resolve(job["media"]["file"]), "título")
    assert Cliente.chamadas[0]["json"]["status"]["privacyStatus"] == "unlisted"
    print("ok upload: padrão é unlisted (público só por escolha explícita)")


def test_upload_erros():
    _autorizado()
    job = _job_com_arquivo()
    caminho = media.resolve(job["media"]["file"])

    try:
        youtube.upload("/caminho/que/nao/existe.mp4", "t")
    except youtube.YouTubeError as exc:
        assert "não encontrado" in str(exc)
    else:
        raise AssertionError("arquivo inexistente deveria falhar")

    try:
        youtube.upload(caminho, "t", privacy="público")
    except youtube.YouTubeError as exc:
        assert "Privacidade inválida" in str(exc)
    else:
        raise AssertionError("privacidade inválida deveria falhar")

    with cenário(R(401, {"error": {"message": "Invalid Credentials"}})):
        try:
            youtube.upload(caminho, "t")
        except youtube.YouTubeError as exc:
            assert exc.status == 401 and "Renove" in str(exc)
        else:
            raise AssertionError("401 deveria levantar YouTubeError")

    with cenário(R(403, {"error": {"message": "The request cannot be completed because "
                                            "you have exceeded your quota"}})):
        try:
            youtube.upload(caminho, "t")
        except youtube.YouTubeError as exc:
            assert "cota" in str(exc).lower()
        else:
            raise AssertionError("estouro de cota deveria ser explicado")
    print("ok upload: arquivo ausente, privacidade, 401 e cota com mensagens claras")


def test_upload_sem_location():
    _autorizado()
    job = _job_com_arquivo()
    with cenário(R(200, {})):     # 200 sem header Location
        try:
            youtube.upload(media.resolve(job["media"]["file"]), "t")
        except youtube.YouTubeError as exc:
            assert "Location" in str(exc)
        else:
            raise AssertionError("resposta sem Location deveria falhar")
    print("ok upload: resposta sem Location é tratada")


# ================================================================ publicações
def test_publicar_exige_arquivo_e_canal():
    _cfg(YOUTUBE_REFRESH_TOKEN="", YOUTUBE_CLIENT_ID="cid", YOUTUBE_CLIENT_SECRET="s")
    job = pipeline.job_create("sem arquivo", "cena", "dark", 4, tenant_id="demo")
    try:
        publications.publicar("demo", job, "Título")
    except publications.PublicacaoError as exc:
        assert "arquivo salvo" in str(exc)
    else:
        raise AssertionError("job sem mídia não pode publicar")

    job2 = _job_com_arquivo()
    try:
        publications.publicar("demo", job2, "Título")
    except publications.PublicacaoError as exc:
        assert "Autorizar" in str(exc)
    else:
        raise AssertionError("sem canal autorizado não pode publicar")
    print("ok publicação: exige arquivo local e canal autorizado")


def test_publicar_e_medir():
    _autorizado()
    job = _job_com_arquivo()
    cenario = cenário(
        R(200, {}, headers={"Location": "https://upload.example/s"}),
        R(200, {"id": "vid001", "snippet": {"title": "Garrafa"}, "status": {}}),
        # sincronizar() logo após publicar
        R(200, {"items": [{"id": "vid001", "statistics": {"viewCount": "0"},
                           "snippet": {"title": "Garrafa", "channelTitle": "Canal Teste"},
                           "status": {"privacyStatus": "unlisted"}}]}),
    )
    with cenario:
        pub = publications.publicar("demo", job, "Garrafa térmica 24h",
                                    "descrição", ["garrafa"], "unlisted")

    assert pub["video_id"] == "vid001"
    assert pub["status"] == "publicado"
    assert pub["privacidade"] == "unlisted"
    assert len(pub["snapshots"]) == 1, "deve medir logo após publicar"
    assert pub["snapshots"][0]["views"] == 0

    # corpus recebeu o vídeo publicado
    ing = [v for v in mining._ingested() if v.get("source") == "publicado"]
    assert len(ing) == 1 and "garrafa" in ing[0]["title"].lower()
    print("ok publicação: upload, registro, primeira medição e entrada no corpus")


def test_sincronizar_atualiza_corpus_sem_duplicar():
    _autorizado()
    pub = publications.listar("demo")[0]
    with cenário(R(200, {"items": [{"id": pub["video_id"],
                                    "statistics": {"viewCount": "1500",
                                                   "likeCount": "90", "commentCount": "7"},
                                    "snippet": {"title": "Garrafa", "channelTitle": "Canal Teste"},
                                    "status": {"privacyStatus": "unlisted"}}]})):
        publications.sincronizar(pub["id"])

    atual = publications.obter(pub["id"])
    assert len(atual["snapshots"]) == 2
    ultimo = atual["snapshots"][-1]
    assert ultimo["views"] == 1500 and ultimo["likes"] == 90

    ing = [v for v in mining._ingested() if v.get("source") == "publicado"]
    assert len(ing) == 1, "medir de novo não pode duplicar o vídeo no corpus"
    assert ing[0]["views"] == 1500, "o corpus tem que ver o número mais recente"
    print("ok medição: nova leitura empilha snapshot e atualiza o corpus (sem duplicar)")


def test_sincronizar_video_removido():
    _autorizado()
    pub = publications.listar("demo")[0]
    with cenário(R(200, {"items": []})):
        try:
            publications.sincronizar(pub["id"])
        except publications.PublicacaoError as exc:
            assert "não devolveu" in str(exc)
        else:
            raise AssertionError("vídeo ausente deveria falhar")
    atual = publications.obter(pub["id"])
    assert atual["status"] == "indisponivel" and atual["erro"]
    print("ok medição: vídeo removido do canal é marcado como indisponível")


def test_sync_em_lote_respeita_janela():
    _autorizado()
    agora = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    antiga = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 40 * 86400))
    base = {"tenant": "demo", "job_id": "job-x", "titulo": "Garrafa",
            "snapshots": [], "privacidade": "unlisted", "status": "publicado"}
    publications._save([
        {**base, "id": "pub-nova", "video_id": "vid001", "publicado_at": agora},
        {**base, "id": "pub-velha", "video_id": "velho", "publicado_at": antiga},
    ])
    _cfg(PUBLISH_JANELA_DIAS="7")

    with cenário(R(200, {"items": [{"id": "vid001",
                                    "statistics": {"viewCount": "2000"},
                                    "snippet": {"title": "Garrafa"},
                                    "status": {}}]})):
        res = publications.sincronizar_tudo("demo")
    assert res["sincronizados"] == 1
    assert all("pub-velha" not in (f.get("id") or "") for f in res["falhas"])
    print("ok medição: lote ignora publicação fora da janela de acompanhamento")


def test_resumo():
    r = publications.resumo("demo")
    assert r["publicados"] >= 1
    assert r["views_total"] >= 2000
    assert r["melhor"]["views"] == max(l["views"] for l in r["serie"])
    assert r["canal"]["titulo"] == "Canal Teste"
    print("ok resumo: totais, melhor vídeo e canal")


def test_apagar_nao_apaga_no_youtube():
    pub = publications.listar("demo")[0]
    assert publications.apagar(pub["id"], "demo") is True
    assert publications.obter(pub["id"]) is None
    assert publications.apagar(pub["id"], "demo") is False
    print("ok publicação: apagar remove só o registro local")


def test_retencao_poda_publicacoes_antigas():
    antigas = [{"id": f"pub-old-{i}", "tenant": "demo",
                "publicado_at": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                              time.gmtime(time.time() - (200 + i) * 86400))}
               for i in range(8)]
    storage._write(publications.PUBLICATIONS_FILE, antigas)
    _cfg(RETENTION_DIAS="90", RETENTION_ENABLED="1")
    rel = retention.run(force=True)
    assert rel["removidos"]["publicacoes"] >= 1, rel["removidos"]
    assert len(publications.listar()) <= publications.MAX_PUBLICATIONS
    print("ok retenção: publicações antigas entram na poda")


def test_rota_de_callback_do_youtube():
    from server import main as srv
    _cfg(YOUTUBE_CLIENT_ID="cid", YOUTUBE_CLIENT_SECRET="sec",
         YOUTUBE_REDIRECT_URI="https://app/cb")
    token = R(200, {"access_token": "ya29.a", "refresh_token": "1//r", "expires_in": 3600})
    canal = R(200, {"items": [{"id": "UC1", "snippet": {"title": "Canal Callback"},
                               "statistics": {}}]})
    with cenário(token, canal):
        resp = asyncio.run(srv.youtube_callback_get(code="4/abc"))
    assert resp.status_code == 200
    corpo = resp.body.decode()
    assert "YouTube autorizado" in corpo and "Canal Callback" in corpo
    assert "/#/apis" in corpo

    resp2 = asyncio.run(srv.youtube_callback_get(code="", error="access_denied"))
    assert resp2.status_code == 400
    assert "access_denied" in resp2.body.decode()
    print("ok rota: callback do Google conclui e volta para o app")


if __name__ == "__main__":
    test_authorize_url()
    test_exchange_code_guarda_tokens_e_canal()
    test_exchange_code_recusado()
    test_access_token_renova_sozinho()
    test_upload_resumable()
    test_upload_privacidade_padrao_unlisted()
    test_upload_erros()
    test_upload_sem_location()
    test_publicar_exige_arquivo_e_canal()
    test_publicar_e_medir()
    test_sincronizar_atualiza_corpus_sem_duplicar()
    test_sincronizar_video_removido()
    test_sync_em_lote_respeita_janela()
    test_resumo()
    test_apagar_nao_apaga_no_youtube()
    test_retencao_poda_publicacoes_antigas()
    test_rota_de_callback_do_youtube()
    print("\nTODOS OS TESTES DE PUBLICAÇÃO PASSARAM ✔")
