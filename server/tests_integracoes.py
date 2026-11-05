"""Testes offline das integrações novas — RunPod direto, Virlo, mineração e fontes.

Sem rede: todo `httpx` é substituído por dublês. Rodar com:

    .venv/bin/python -m server.tests_integracoes

Os testes escrevem chaves falsas e jobs de teste. Para não contaminar o runtime
da aplicação (que exibiria "conectado" com credencial inventada), tudo vai para
um diretório temporário descartado no fim — nunca para `data/`.
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

from server import free_sources, metrics, mining, pipeline, runpod, schema, storage, virlo

# --------------------------------------------------- isolamento do estado em disco
_TMP = Path(tempfile.mkdtemp(prefix="mineraai-tests-"))
atexit.register(shutil.rmtree, _TMP, True)

storage.DATA_DIR = _TMP
storage.SETTINGS_FILE = _TMP / "settings.json"
mining.DATA_DIR = _TMP
mining.ORBITS_FILE = _TMP / "orbits.json"
mining.COMETS_FILE = _TMP / "comets.json"
mining.INGEST_FILE = _TMP / "ingested.json"
pipeline.JOBS_FILE = _TMP / "jobs.json"


# ================================================================ dublês HTTP
class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        if self._payload is None:
            raise ValueError("sem json")
        return self._payload


class FakeClient:
    """Substitui httpx.AsyncClient/Client gravando a última chamada."""

    chamadas: list = []
    resposta = FakeResponse()

    def __init__(self, *a, **kw):
        self.kw = kw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def _registra(self, method, url, **kw):
        FakeClient.chamadas.append({"method": method, "url": str(url),
                                    "json": kw.get("json"), "params": kw.get("params"),
                                    "data": kw.get("data"), "headers": kw.get("headers"),
                                    "auth": kw.get("auth")})
        return FakeClient.resposta

    async def request(self, method, url, **kw):
        return self._registra(method, url, **kw)

    def get(self, url, **kw):
        return self._registra("GET", url, **kw)

    def post(self, url, **kw):
        return self._registra("POST", url, **kw)

    async def arequest(self, method, url, **kw):
        return self._registra(method, url, **kw)


def _patch(module, attr, fake):
    original = getattr(module, attr)
    setattr(module, attr, fake)
    return original


class cenário:
    """Context manager: troca httpx.Client/AsyncClient por dublês."""

    def __init__(self, resposta: FakeResponse = None):
        FakeClient.chamadas = []
        if resposta is not None:
            FakeClient.resposta = resposta

    def __enter__(self):
        self._sync = _patch(httpx, "Client", FakeClient)
        self._async = _patch(httpx, "AsyncClient", FakeClient)
        return self

    def __exit__(self, *a):
        httpx.Client = self._sync
        httpx.AsyncClient = self._async
        return False


def _settings(**kw):
    storage.settings_save({k: str(v) for k, v in kw.items()})


# ================================================================ RunPod
def test_runpod_config_e_payload():
    _settings(RUNPOD_API_KEY="rp_test", RUNPOD_ENDPOINT_ID="ep123",
              RUNPOD_GPU_PRICE_HORA="0.44")
    assert runpod.configured() is True
    assert runpod._base() == "https://api.runpod.ai/v2/ep123"

    payload = runpod.build_input("garrafa térmica", style="dark")
    wf = payload["input"]["workflow"]
    textos = [n["inputs"]["text"] for n in wf.values()
              if n.get("class_type") == "CLIPTextEncode"]
    assert "garrafa térmica" in textos[0]
    assert "cinematic dark" in textos[0]
    assert "watermark" in textos[1]
    print("ok runpod config + payload")


def test_runpod_aplica_template():
    template = {
        "10": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "11": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
        "12": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20}},
    }
    wf = runpod.apply_prompt(template, "prompt novo", "negativo novo", seed=42)
    assert wf["10"]["inputs"]["text"] == "prompt novo"
    assert wf["11"]["inputs"]["text"] == "negativo novo"
    assert wf["12"]["inputs"]["seed"] == 42
    # template original não pode ser mutado
    assert template["10"]["inputs"]["text"] == ""
    print("ok runpod aplica template sem mutar original")


def test_runpod_submit_sync_e_extract():
    resposta = FakeResponse(200, {
        "id": "sync-123", "status": "COMPLETED",
        "delayTime": 2000, "executionTime": 3000,
        "output": {"message": "https://s3.example/video.mp4", "status": "success"}})
    with cenário(resposta):
        res = asyncio.run(runpod.submit({"input": {}}, mode="sync"))
    assert res["mode"] == "sync"
    assert res["runpod_job_id"] == "sync-123"
    chamada = FakeClient.chamadas[-1]
    assert chamada["url"].endswith("/runsync")
    assert chamada["headers"]["Authorization"] == "Bearer rp_test"

    out = runpod.extract_outputs(resposta.json())
    assert out["urls"] == ["https://s3.example/video.mp4"]
    assert out["execution_ms"] == 3000

    custo = runpod.estimate_cost(out["execution_ms"], out["delay_ms"])
    # 5s a US$ 0,44/h ≈ US$ 0,0006
    assert 0.0005 <= custo["total_usd"] <= 0.0008, custo
    print("ok runpod submit sync + extract + custo")


def test_runpod_async_e_status():
    FakeClient.resposta = FakeResponse(200, {"id": "async-9", "status": "IN_QUEUE"})
    with cenário():
        res = asyncio.run(runpod.submit({"input": {}}, mode="async"))
    assert res["mode"] == "async" and res["runpod_job_id"] == "async-9"
    assert FakeClient.chamadas[-1]["url"].endswith("/run")

    FakeClient.resposta = FakeResponse(200, {"status": "IN_PROGRESS"})
    with cenário():
        st = asyncio.run(runpod.get_status("async-9"))
    assert st["status"] == "IN_PROGRESS"
    assert FakeClient.chamadas[-1]["url"].endswith("/status/async-9")
    print("ok runpod async + status")


def test_runpod_erros():
    FakeClient.resposta = FakeResponse(401, {"error": "unauthorized"})
    with cenário():
        try:
            asyncio.run(runpod.submit({"input": {}}))
        except runpod.RunPodError as exc:
            assert exc.status == 401 and "inválida" in str(exc)
        else:
            raise AssertionError("401 deveria levantar RunPodError")

    FakeClient.resposta = FakeResponse(404, {})
    with cenário():
        try:
            asyncio.run(runpod.health())
        except runpod.RunPodError as exc:
            assert exc.status == 404 and "Endpoint" in str(exc)
        else:
            raise AssertionError("404 deveria levantar RunPodError")
    print("ok runpod erros mapeados (401/404)")


def test_runpod_health_normalizado():
    FakeClient.resposta = FakeResponse(200, {
        "workers": {"ready": 2, "idle": 1, "running": 1, "initializing": 0},
        "jobs": {"inProgress": 1, "inQueue": 3}})
    with cenário():
        h = asyncio.run(runpod.health())
    assert h["workers"]["prontos"] == 2 and h["fila"]["na_fila"] == 3
    print("ok runpod health")


# ================================================================ Virlo
def test_virlo_config():
    _settings(VIRLO_API_KEY="virlo_tkn_teste", VIRLO_AUTO_USE="1")
    assert virlo.configured() is True
    assert virlo.auto_use() is True
    _settings(VIRLO_AUTO_USE="0")
    assert virlo.auto_use() is False
    _settings(VIRLO_AUTO_USE="0")
    print("ok virlo config/auto_use")


def test_virlo_orbit_create():
    _settings(VIRLO_API_KEY="virlo_tkn_teste")
    FakeClient.resposta = FakeResponse(200, {"data": {"id": "orb_1", "status": "queued"}})
    with cenário():
        res = asyncio.run(virlo.orbit_create("teste", ["skincare"], ["tiktok"], 1000))
    assert res["id"] == "orb_1"
    chamada = FakeClient.chamadas[-1]
    assert chamada["url"] == "https://api.virlo.ai/v1/orbit"
    assert chamada["headers"]["Authorization"].startswith("Bearer virlo_tkn_")
    assert chamada["json"]["keywords"] == ["skincare"]
    print("ok virlo orbit create")


def test_virlo_normalizacao():
    bruto = {
        "id": "vid_9", "platform": "tiktok", "caption": "teste de garrafa",
        "author": {"username": "ana.descobertas"},
        "stats": {"views": 120000, "likes": 9000, "comments": 300, "shares": 500},
        "hashtags": ["#achados"], "url": "https://tiktok.com/x", "age_hours": 12,
    }
    unificado = virlo.to_unified_video(bruto)
    assert unificado["platform"] == "tiktok"
    assert unificado["handle"] == "@ana.descobertas"
    assert unificado["views"] == 120000
    assert unificado["source"] == "virlo"
    entidade = schema.normalize_video(unificado, "tiktok")
    assert entidade["uid"].startswith("vid:tiktok:")
    print("ok virlo → esquema unificado")


def test_virlo_collect_filtra_por_termo():
    _settings(VIRLO_API_KEY="virlo_tkn_teste")
    videos = [
        {"id": "1", "platform": "tiktok", "caption": "skincare routine",
         "author": {"username": "a"}, "stats": {"views": 100}, "age_hours": 5},
        {"id": "2", "platform": "tiktok", "caption": "receita de bolo",
         "author": {"username": "b"}, "stats": {"views": 200}, "age_hours": 6},
    ]
    respostas = [FakeResponse(200, {"data": videos}),
                 FakeResponse(200, {"data": []}),
                 FakeResponse(200, {"data": []})]

    class Sequencia(FakeClient):
        def _registra(self, method, url, **kw):
            FakeClient.chamadas.append({"url": str(url), "method": method})
            return respostas.pop(0)

    original = _patch(httpx, "AsyncClient", Sequencia)
    try:
        res = asyncio.run(virlo.collect("skincare", "tiktok", 10))
    finally:
        httpx.AsyncClient = original
    assert len(res["videos"]) == 1
    assert res["filtrado_por_termo"] is True
    print("ok virlo collect filtrado por termo")


def test_virlo_erro_401():
    _settings(VIRLO_API_KEY="virlo_tkn_ruim")
    FakeClient.resposta = FakeResponse(401, {})
    with cenário():
        try:
            asyncio.run(virlo.balance())
        except virlo.VirloError as exc:
            assert exc.status == 401
        else:
            raise AssertionError("401 deveria levantar VirloError")
    print("ok virlo 401")


# ================================================================ Mineração
def test_mining_orbit_ciclo():
    _settings(YOUTUBE_API_KEY="")           # sem fonte real: orbit completa vazio
    orbit = mining.orbit_create("demo", "Teste", ["skincare"], ["tiktok"], 0)
    assert orbit["id"].startswith("orb_")
    assert orbit["status"] == "queued"
    rodado = asyncio.run(mining.orbit_run(orbit["id"], "demo"))
    assert rodado["status"] == "completed"
    assert rodado["progress"] == 100
    assert rodado["report"]["keywords"] == ["skincare"]
    assert "por_plataforma" in rodado["report"]
    lista = mining.orbit_list("demo")
    assert lista and lista[0]["id"] == orbit["id"]
    assert mining.orbit_delete(orbit["id"], "demo") is True
    print("ok mineração: orbit ciclo completo")


def test_mining_comet_serie():
    comet = mining.comet_create("demo", "Monitor", ["cozinha"], ["tiktok"], "daily", 0)
    assert comet["next_run"]
    ciclo = asyncio.run(mining.comet_run(comet["id"], "demo"))
    assert len(ciclo["series"]) == 1
    assert ciclo["series"][0]["videos"] == 0
    assert ciclo["last_run"]
    assert mining.comet_delete(comet["id"], "demo") is True
    print("ok mineração: comet empilha série")


def test_mining_ingestao_dedupe():
    titulo = f"Vídeo de teste {time.time_ns()}"
    item = {"id": "abc", "platform": "youtube", "title": titulo,
            "views": 1000, "likes": 10, "comments": 1, "shares": 0, "age_hours": 10}
    assert mining.ingest_videos([item], "teste") == 1
    # mesmo vídeo de novo não duplica
    assert mining.ingest_videos([item], "teste") == 0
    assert mining.ingested_for_query("vídeo de teste")
    print("ok mineração: ingestão com dedupe")


def test_mining_explicacao():
    d = mining.como_funciona()
    assert len(d["etapas"]) >= 5
    assert "outlier" in json.dumps(d).lower()
    print("ok mineração: explicação do pipeline")


# ================================================================ fontes
def test_parse_count():
    assert free_sources.parse_count("1.234.567") == 1234567
    assert free_sources.parse_count("1,2 mi") == 1200000
    assert free_sources.parse_count("200+") == 200
    assert free_sources.parse_count(None) == 0
    print("ok free_sources.parse_count")


def test_reddit_oauth_e_fallback():
    _settings(REDDIT_CLIENT_ID="", REDDIT_CLIENT_SECRET="")
    assert free_sources.reddit_configured() is False

    # sem credencial → tenta JSON público
    posts = {"data": {"children": [
        {"data": {"id": "1", "title": "post público", "score": 10,
                  "num_comments": 2, "author": "x", "subreddit": "Brasil",
                  "permalink": "/r/Brasil/1", "created_utc": time.time() - 3600}}]}}
    FakeClient.resposta = FakeResponse(200, posts)

    class Rota(FakeClient):
        def _registra(self, method, url, **kw):
            FakeClient.chamadas.append({"url": str(url), "auth": kw.get("auth")})
            return FakeClient.resposta

    original = _patch(httpx, "Client", Rota)
    try:
        res = free_sources.reddit_trending("Brasil", 3)
    finally:
        httpx.Client = original
    assert len(res) == 1 and res[0]["title"] == "post público"
    assert "reddit.com" in FakeClient.chamadas[-1]["url"]

    # com credencial → emite token e usa oauth.reddit.com
    _settings(REDDIT_CLIENT_ID="id", REDDIT_CLIENT_SECRET="secret",
              REDDIT_USER_AGENT="MineraAI test")
    respostas = [FakeResponse(200, {"access_token": "tok123", "expires_in": 3600,
                                    "scope": "read"}), FakeResponse(200, posts)]

    class Fluxo(FakeClient):
        def _registra(self, method, url, **kw):
            headers = {**(self.kw.get("headers") or {}), **(kw.get("headers") or {})}
            FakeClient.chamadas.append({"url": str(url), "auth": kw.get("auth"),
                                        "headers": headers})
            return respostas.pop(0)

    original = _patch(httpx, "Client", Fluxo)
    try:
        free_sources._reddit_cache.update({"token": "", "exp": 0.0})
        tok = free_sources.reddit_token(force=True)
        assert tok["token"] == "tok123"
        assert FakeClient.chamadas[-1]["auth"] == ("id", "secret")
        res = free_sources.reddit_trending("Brasil", 2)
    finally:
        httpx.Client = original
    assert len(res) == 1
    assert "oauth.reddit.com" in FakeClient.chamadas[-1]["url"]
    assert FakeClient.chamadas[-1]["headers"]["Authorization"] == "Bearer tok123"
    free_sources._reddit_cache.update({"token": "", "exp": 0.0})
    print("ok reddit: fallback público + OAuth client_credentials")


def test_meli_oauth_fluxo():
    _settings(MELI_CLIENT_ID="meli_id", MELI_CLIENT_SECRET="meli_secret",
              MELI_REDIRECT_URI="https://localhost/cb")
    assert free_sources.meli_configured() is True
    auth = free_sources.meli_authorize_url("xyz")
    assert auth["ok"] and "response_type=code" in auth["url"]
    assert "state=xyz" in auth["url"]

    FakeClient.resposta = FakeResponse(200, {
        "access_token": "APP_USR-1", "refresh_token": "TG-refresh",
        "expires_in": 21600, "scope": "offline_access read"})
    with cenário():
        res = free_sources.meli_exchange_code("TG-abc")
    assert res["ok"] is True
    chamada = FakeClient.chamadas[-1]
    assert chamada["url"] == "https://api.mercadolibre.com/oauth/token"
    assert chamada["data"]["grant_type"] == "authorization_code"
    salvo = storage.settings_get()
    assert salvo["MELI_ACCESS_TOKEN"] == "APP_USR-1"
    assert salvo["MELI_REFRESH_TOKEN"] == "TG-refresh"

    # refresh automático quando expirado
    storage.settings_save({"MELI_TOKEN_EXPIRES_AT": "1"})
    FakeClient.resposta = FakeResponse(200, {
        "access_token": "APP_USR-2", "refresh_token": "TG-2", "expires_in": 21600})
    with cenário():
        token = free_sources.meli_access_token()
        assert token == "APP_USR-2"
        assert FakeClient.chamadas[-1]["data"]["grant_type"] == "refresh_token"
    print("ok mercado livre: authorize → code → token → refresh")


def test_meli_busca():
    _settings(MELI_ACCESS_TOKEN="APP_USR-1", MELI_TOKEN_EXPIRES_AT=str(int(time.time()) + 3600))
    FakeClient.resposta = FakeResponse(200, {"results": [{
        "id": "MLB1", "title": "Garrafa térmica", "price": 79.9, "sold_quantity": 320,
        "reviews": {"rating_average": 4.8, "total": 90}, "permalink": "https://ml.com/1",
        "thumbnail": "http://http2.mlstatic.com/x.jpg", "shipping": {"free_shipping": True},
        "category_id": "MLB1234"}]})
    with cenário():
        itens = free_sources.mercadolivre_search("garrafa", 5)
    assert len(itens) == 1
    assert itens[0]["sold_quantity"] == 320
    assert itens[0]["thumbnail"].startswith("https://")
    sinal = free_sources.mercadolivre_trend_signal(itens)
    assert sinal["total_sold"] == 320
    assert sinal["autenticado"] is True
    print("ok mercado livre: busca com OAuth + sinal de mercado")


def test_trends_parse():
    xml = """<?xml version="1.0"?>
    <rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
      <item><title>Assunto Quente</title><ht:approx_traffic>200+</ht:approx_traffic>
        <ht:news><ht:newsItem><ht:source>G1</ht:source></ht:newsItem></ht:news></item>
      <item><title>Outro Tema</title><ht:approx_traffic>1.200.000+</ht:approx_traffic></item>
    </channel></rss>"""
    FakeClient.resposta = FakeResponse(200, {}, text=xml)
    with cenário():
        termos = free_sources.google_trends_br(5)
    assert len(termos) == 2
    assert termos[0]["term"] == "Assunto Quente" and termos[0]["traffic"] == 200
    assert termos[1]["traffic"] == 1200000
    print("ok google trends: parse RSS")


def test_suggest_e_oembed():
    FakeClient.resposta = FakeResponse(200, ["q", ["como ganhar dinheiro", "como investir"]])
    with cenário():
        sug = free_sources.google_suggest("como ganhar")
    assert sug[0] == "como ganhar dinheiro"

    FakeClient.resposta = FakeResponse(200, {"title": "Vídeo X", "author_name": "Canal Y",
                                             "thumbnail_url": "https://t/x.jpg"})
    with cenário():
        meta = free_sources.oembed_lookup("https://www.youtube.com/watch?v=abc")
    assert meta["title"] == "Vídeo X" and meta["platform"] == "youtube"
    assert free_sources.looks_like_video_url("https://youtu.be/abc") is True
    print("ok suggest + oembed")


def test_pexels_sem_chave():
    _settings(PEXELS_API_KEY="")
    res = free_sources.pexels_broll("produto", 3)
    assert res["ok"] is False and "Pexels" in res["message"]
    print("ok pexels: mensagem clara sem chave")



# ================================================================ busca por origem
def _video_fake(uid: str, source: str, views: int = 1000) -> dict:
    return {"uid": uid, "platform": "tiktok", "title": f"vídeo {uid}",
            "handle": "@criador", "views": views, "likes": 10, "comments": 1,
            "shares": 0, "age_hours": 6, "hashtags": ["#teste"],
            "sound": "som original", "source": source}


def _com_coleta_fake(fn):
    """Roda fn() com as camadas de coleta trocadas por respostas fixas."""
    from server import research

    orig = (research.collect_official, research.collect_virlo,
            mining.mined_for_query, mining.ingested_for_query)

    async def oficial(*a, **kw):
        return [_video_fake("vid:tiktok:oficial", "oficial")], []

    async def v(*a, **kw):
        return [_video_fake("vid:tiktok:virlo", "virlo")], []

    research.collect_official = oficial
    research.collect_virlo = v
    mining.mined_for_query = lambda q: [_video_fake("vid:tiktok:mineirado", "mineracao")]
    mining.ingested_for_query = lambda q: []
    try:
        return fn(research)
    finally:
        (research.collect_official, research.collect_virlo,
         mining.mined_for_query, mining.ingested_for_query) = orig


def test_busca_isola_origem():
    def roda(research):
        out = {}
        for src in ("oficial", "virlo", "mineracao", "demo", "all"):
            out[src] = asyncio.run(research.search_videos("teste", "tiktok", "30d",
                                                          0, 5, source=src))
        return out

    res = _com_coleta_fake(roda)

    assert res["oficial"]["source"] == "oficial"
    assert [v["source"] for v in res["oficial"]["videos"]] == ["oficial"]
    assert res["oficial"]["source_breakdown"]["demo"] == 0

    assert [v["source"] for v in res["virlo"]["videos"]] == ["virlo"]
    assert [v["source"] for v in res["mineracao"]["videos"]] == ["mineracao"]

    demo = res["demo"]["videos"]
    assert demo and all(v["source"] == "demo" for v in demo)

    todas = {v["source"] for v in res["all"]["videos"]}
    assert {"oficial", "virlo", "mineracao"} <= todas
    assert "demo" in todas
    print("ok busca: source isola oficial/virlo/mineração/demo")


def test_busca_sem_demo():
    def roda(research):
        return asyncio.run(research.search_videos("teste", "tiktok", "30d", 0, 5,
                                                  include_demo=False))

    res = _com_coleta_fake(roda)
    assert res["videos"], "deveria trazer as fontes reais"
    assert all(v["source"] != "demo" for v in res["videos"])
    assert res["source_breakdown"]["demo"] == 0
    print("ok busca: include_demo=false nunca mistura simulado")


def test_busca_origem_vazia_avisa():
    from server import research
    orig = research.collect_official

    async def vazio(*a, **kw):
        return [], []

    research.collect_official = vazio
    try:
        res = asyncio.run(research.search_videos("teste", "tiktok", "30d", 0, 5,
                                                 source="oficial"))
    finally:
        research.collect_official = orig
    assert res["videos"] == []
    assert any("isolada a pedido" in e for e in res["errors"]), res["errors"]
    print("ok busca: origem isolada e vazia explica em vez de cair no demo")


def test_facetas_vem_do_resultado():
    from server import research
    videos = [_video_fake("vid:tiktok:a", "oficial", 5000),
              _video_fake("vid:tiktok:b", "oficial", 1000)]
    f = research.facets_from(videos)
    assert f["top_hashtags"][0]["tag"] == "#teste"
    assert f["top_hashtags"][0]["reach"] == 6000
    assert f["top_creators"][0]["handle"] == "@criador"
    assert f["top_creators"][0]["videos"] == 2
    print("ok facetas: calculadas dos vídeos exibidos")


# ================================================================ OAuth Meli (GET)
def test_meli_callback_get_autoriza():
    from server import main as srv
    _settings(MELI_CLIENT_ID="meli_id", MELI_CLIENT_SECRET="meli_secret")
    FakeClient.resposta = FakeResponse(200, {
        "access_token": "APP_USR-ok", "refresh_token": "TG-r", "expires_in": 21600})
    with cenário():
        resp = asyncio.run(srv.meli_callback_get(code="TG-abc"))
    assert resp.status_code == 200
    corpo = resp.body.decode()
    assert "autorizado" in corpo.lower()
    assert "/#/apis" in corpo
    assert storage.settings_get()["MELI_ACCESS_TOKEN"] == "APP_USR-ok"
    print("ok oauth: GET de retorno do Mercado Livre conclui e volta pro app")


def test_meli_callback_get_erro():
    from server import main as srv
    FakeClient.chamadas = []
    resp = asyncio.run(srv.meli_callback_get(code="", error="access_denied",
                                             error_description="Usuário recusou"))
    assert resp.status_code == 400
    corpo = resp.body.decode()
    assert "Usuário recusou" in corpo
    assert "/#/apis" in corpo
    # sem code e sem erro → mensagem clara, não stacktrace
    resp2 = asyncio.run(srv.meli_callback_get())
    assert resp2.status_code == 400
    print("ok oauth: erro de autorização vira página legível, sem 500")


if __name__ == "__main__":
    test_runpod_config_e_payload()
    test_runpod_aplica_template()
    test_runpod_submit_sync_e_extract()
    test_runpod_async_e_status()
    test_runpod_erros()
    test_runpod_health_normalizado()
    test_virlo_config()
    test_virlo_orbit_create()
    test_virlo_normalizacao()
    test_virlo_collect_filtra_por_termo()
    test_virlo_erro_401()
    test_mining_orbit_ciclo()
    test_mining_comet_serie()
    test_mining_ingestao_dedupe()
    test_mining_explicacao()
    test_parse_count()
    test_reddit_oauth_e_fallback()
    test_meli_oauth_fluxo()
    test_meli_busca()
    test_trends_parse()
    test_suggest_e_oembed()
    test_pexels_sem_chave()
    test_busca_isola_origem()
    test_busca_sem_demo()
    test_busca_origem_vazia_avisa()
    test_facetas_vem_do_resultado()
    test_meli_callback_get_autoriza()
    test_meli_callback_get_erro()
    print("\nTODOS OS TESTES DE INTEGRAÇÃO PASSARAM ✔")
