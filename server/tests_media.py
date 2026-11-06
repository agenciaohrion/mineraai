"""Testes offline de mídia local e retenção.

Sem rede: `httpx.AsyncClient` é substituído por um dublê que "transmite" bytes
em pedaços, exercitando o mesmo caminho do download real (streaming, corte por
tamanho, sniff de extensão).

    .venv/bin/python -m server.tests_media

Tudo roda num diretório temporário — o `data/` do runtime não é tocado.
"""
from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

import httpx

from server import credits, media, mining, pipeline, retention, storage

# --------------------------------------------------- isolamento do estado em disco
_TMP = Path(tempfile.mkdtemp(prefix="mineraai-media-"))
atexit.register(shutil.rmtree, _TMP, True)

storage.DATA_DIR = _TMP
storage.SETTINGS_FILE = _TMP / "settings.json"
storage.LIBRARY_FILE = _TMP / "library.json"
media.MEDIA_DIR = _TMP / "media"
pipeline.JOBS_FILE = _TMP / "jobs.json"
credits.USAGE_FILE = _TMP / "usage.json"
mining.ORBITS_FILE = _TMP / "orbits.json"
mining.COMETS_FILE = _TMP / "comets.json"
mining.INGEST_FILE = _TMP / "ingested.json"

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 40


def _cfg(**kw):
    storage.settings_save({k: str(v) for k, v in kw.items()})


# ================================================================ dublê de streaming
class _Resposta:
    def __init__(self, pedacos: list[bytes], status_code: int = 200,
                 headers: dict | None = None):
        self._pedacos = pedacos
        self.status_code = status_code
        self.headers = headers or {}

    async def aiter_bytes(self, n: int = 65536):
        for p in self._pedacos:
            yield p

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Cliente:
    """Substitui httpx.AsyncClient no media.save_from_url."""
    resposta: _Resposta = _Resposta([MP4])
    chamadas: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, **kw):
        _Cliente.chamadas.append({"method": method, "url": str(url)})
        return _Cliente.resposta


class com_cliente_fake:
    def __init__(self, resposta: _Resposta):
        _Cliente.chamadas = []
        _Cliente.resposta = resposta

    def __enter__(self):
        self._orig = httpx.AsyncClient
        httpx.AsyncClient = _Cliente
        return self

    def __exit__(self, *a):
        httpx.AsyncClient = self._orig
        return False


# ================================================================ mídia
def test_salva_base64_png():
    info = media.save_base64("data:image/png;base64," + __import__("base64").b64encode(PNG).decode(),
                             "demo", "job-b64")
    assert info["ext"] == ".png", info
    assert info["file"] == "media/demo/job-b64.png"
    caminho = media.resolve(info["file"])
    assert caminho and caminho.read_bytes() == PNG
    assert info["content_type"].startswith("image/")
    assert media.info_arquivo(info["file"])["media_type"] == "image/png"
    print("ok mídia: base64 vira arquivo com extensão detectada pelos bytes")


def test_salva_url_com_streaming():
    with com_cliente_fake(_Resposta([MP4[:8], MP4[8:]])):
        info = asyncio.run(media.save_from_url("https://s3.example/v.mp4", "demo", "job-url"))
    assert info["file"] == "media/demo/job-url.mp4"
    assert info["bytes"] == len(MP4)
    assert info["origem"] == "url"
    assert _Cliente.chamadas[0]["url"] == "https://s3.example/v.mp4"
    assert media.resolve(info["file"]).read_bytes() == MP4
    print("ok mídia: download em streaming grava os bytes do worker")


def test_extensao_vem_dos_bytes_nao_da_url():
    # URL sem extensão e content-type genérico: só os bytes dizem o que é
    with com_cliente_fake(_Resposta([PNG], headers={"content-type": "application/octet-stream"})):
        info = asyncio.run(media.save_from_url("https://s3.example/abc123", "demo", "job-ext"))
    assert info["ext"] == ".png" and info["file"].endswith(".png")
    print("ok mídia: extensão detectada pelos primeiros bytes (não pela URL)")


def test_limite_de_tamanho():
    _cfg(MEDIA_MAX_MB="1")
    grande = b"\x00" * (1024 * 1024 + 10)
    with com_cliente_fake(_Resposta([MP4, grande])):
        try:
            asyncio.run(media.save_from_url("https://s3.example/g.mp4", "demo", "job-big"))
        except media.MediaError as exc:
            assert "limite" in str(exc)
        else:
            raise AssertionError("deveria recusar arquivo acima do teto")
    assert not media.resolve("media/demo/job-big.mp4"), "arquivo parcial não pode sobrar"
    _cfg(MEDIA_MAX_MB="200")
    print("ok mídia: teto de tamanho corta durante a escrita e não deixa resto")


def test_download_desligado():
    _cfg(MEDIA_MAX_MB="0")
    try:
        asyncio.run(media.save_from_url("https://s3.example/x.mp4", "demo", "job-off"))
    except media.MediaError as exc:
        assert "desativado" in str(exc)
    else:
        raise AssertionError("MEDIA_MAX_MB=0 deve recusar o download")
    _cfg(MEDIA_MAX_MB="200")
    print("ok mídia: MEDIA_MAX_MB=0 desliga o download")


def test_erro_http():
    with com_cliente_fake(_Resposta([b""], status_code=403)):
        try:
            asyncio.run(media.save_from_url("https://s3.example/x.mp4", "demo", "job-403"))
        except media.MediaError as exc:
            assert "403" in str(exc)
        else:
            raise AssertionError("HTTP 403 deveria virar MediaError")
    print("ok mídia: erro do S3 vira MediaError legível")


def test_path_traversal_bloqueado():
    assert media.resolve("../../etc/passwd") is None
    assert media.resolve("jobs.json") is None          # fora de media/
    assert media.resolve("") is None
    print("ok mídia: resolve() recusa caminho fora de media/")


# ================================================================ pipeline → disco
def test_job_concluido_guarda_arquivo_e_biblioteca():
    job = pipeline.job_create("garrafa térmica", "cena 1", "dark", 6, tenant_id="demo")
    raw = {"status": "COMPLETED", "delayTime": 100, "executionTime": 2000,
           "output": {"message": "https://s3.example/out.mp4"}}
    with com_cliente_fake(_Resposta([MP4])):
        atualizado = asyncio.run(pipeline._apply_result(job["id"], raw))

    assert atualizado["status"] == "pronto"
    assert atualizado["media"]["file"] == f"media/demo/{job['id']}.mp4"
    assert atualizado["media_url"] == f"/api/fabrica/jobs/{job['id']}/file"
    assert atualizado["media_error"] is None
    assert atualizado["video_url"] == "https://s3.example/out.mp4"   # referência original
    assert media.resolve(atualizado["media"]["file"]).is_file()

    itens = [i for i in storage.library_list() if i.get("ref") == f"job:{job['id']}"]
    assert len(itens) == 1
    assert itens[0]["payload"]["file"] == atualizado["media"]["file"]

    # servir: o dono acessa, outro workspace não
    info = pipeline.job_media_file(job["id"], "demo")
    assert info["media_type"] == "video/mp4" and info["bytes"] == len(MP4)
    try:
        pipeline.job_media_file(job["id"], "outro")
    except PermissionError:
        pass
    else:
        raise AssertionError("job de outro tenant não pode ser servido")
    print("ok pipeline: job pronto guarda arquivo local, Biblioteca e dono")


def test_job_com_base64():
    job = pipeline.job_create("luminária", "cena única", "ugc", 4, tenant_id="demo")
    import base64
    raw = {"status": "COMPLETED", "output": {"message": base64.b64encode(PNG).decode()}}
    atualizado = asyncio.run(pipeline._apply_result(job["id"], raw))
    assert atualizado["status"] == "pronto"
    assert atualizado["media"]["file"].endswith(".png")
    assert atualizado["media"]["origem"] == "base64"
    print("ok pipeline: saída base64 também vira arquivo local")


def test_falha_no_download_nao_perde_o_job():
    job = pipeline.job_create("falha", "cena", "dark", 4, tenant_id="demo")
    raw = {"status": "COMPLETED", "output": {"message": "https://s3.example/x.mp4"}}
    with com_cliente_fake(_Resposta([b""], status_code=500)):
        atualizado = asyncio.run(pipeline._apply_result(job["id"], raw))
    assert atualizado["status"] == "pronto", "o resultado do worker não pode ser perdido"
    assert atualizado["media"] is None
    assert "500" in atualizado["media_error"]
    assert atualizado["video_url"] == "https://s3.example/x.mp4"
    print("ok pipeline: falha ao salvar mantém o job pronto e explica")


def test_job_com_erro_nao_tenta_baixar():
    job = pipeline.job_create("erro", "cena", "dark", 4, tenant_id="demo")
    with com_cliente_fake(_Resposta([MP4])):
        atualizado = asyncio.run(pipeline._apply_result(
            job["id"], {"status": "FAILED", "output": {"error": "CUDA out of memory"}}))
    assert atualizado["status"] == "erro"
    assert "memory" in atualizado["error"]
    assert _Cliente.chamadas == []
    print("ok pipeline: job com erro não tenta baixar nada")


# ================================================================ retenção
def _iso_dias_atras(dias: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - dias * 86400))


def test_retencao_respeita_janela_e_os_recentes():
    jobs = []
    for i in range(15):                                   # 15 antigos
        jobs.append({"id": f"velho-{i}", "status": "pronto", "created_at": _iso_dias_atras(120)})
    for i in range(3):                                    # 3 novos
        jobs.append({"id": f"novo-{i}", "status": "pronto", "created_at": _iso_dias_atras(1)})
    storage._write(pipeline.JOBS_FILE, jobs)
    _cfg(RETENTION_DIAS="90", RETENTION_ENABLED="1")

    rel = retention.run(force=True)
    restantes = [j["id"] for j in pipeline.jobs_list()]
    # 18 itens, MANTER["jobs"] = 5 → ficam os 5 mais novos, 13 velhos saem
    assert rel["removidos"]["jobs"] == 13, rel
    assert len(restantes) == 5
    assert all(f"novo-{i}" in restantes for i in range(3)), "os mais novos sempre ficam"
    print("ok retenção: janela de 90 dias + os 5 mais recentes preservados")


def test_retencao_nunca_apaga_item_sem_data():
    storage._write(pipeline.JOBS_FILE, [
        {"id": "sem-data-1", "status": "pronto"},
        {"id": "sem-data-2", "status": "pronto"},
        *[{"id": f"v{i}", "status": "pronto", "created_at": _iso_dias_atras(400)} for i in range(12)],
    ])
    retention.run(force=True)
    ids = [j["id"] for j in pipeline.jobs_list()]
    assert "sem-data-1" in ids and "sem-data-2" in ids
    print("ok retenção: item sem data é preservado (não dá para provar que está velho)")


def test_retencao_poda_usage_e_ingeridos():
    agora = time.time()
    antigos_uso = [{"tenant": "demo", "action": "search", "ts": agora - (200 + i) * 86400,
                    "credits": 2} for i in range(20)]
    recentes_uso = [{"tenant": "demo", "action": "search", "ts": agora - i * 60,
                     "credits": 2} for i in range(100)]
    storage._write(credits.USAGE_FILE, antigos_uso + recentes_uso)

    antigos_ing = [{"platform": "tiktok", "title": f"antigo-{i}",
                    "ingested_at": _iso_dias_atras(200)} for i in range(10)]
    recentes_ing = [{"platform": "tiktok", "title": f"recente-{i}",
                     "ingested_at": _iso_dias_atras(2)} for i in range(50)]
    storage._write(mining.INGEST_FILE, antigos_ing + recentes_ing)

    _cfg(RETENTION_DIAS="90", RETENTION_ENABLED="1")
    retention.run(force=True)

    uso = storage._read(credits.USAGE_FILE, [])
    assert len(uso) == 100, f"esperado 100 eventos, veio {len(uso)}"
    assert all(e["ts"] > agora - 90 * 86400 for e in uso), "sobrou evento fora da janela"
    ing = [v["title"] for v in mining._ingested()]
    assert len(ing) == 50 and all(t.startswith("recente-") for t in ing)
    print("ok retenção: ledger e ingestão seguem a mesma janela")


def test_retencao_preserva_comets():
    """Comet é configuração de monitor: não expira por idade."""
    storage._write(mining.COMETS_FILE, [{
        "id": "cmt_velho", "tenant": "demo", "name": "monitor antigo",
        "keywords": ["cozinha"], "frequency": "daily",
        "created_at": _iso_dias_atras(500), "series": []}])
    retention.run(force=True)
    assert any(c["id"] == "cmt_velho" for c in mining._comets()), \
        "comet antigo não pode ser apagado pela retenção"
    print("ok retenção: comets (configuração) nunca são podados por idade")


def test_retencao_limpa_midia_orfa():
    job = pipeline.job_create("com arquivo", "cena", "dark", 4, tenant_id="demo")
    info = media.save_base64(__import__("base64").b64encode(MP4).decode(), "demo", job["id"])
    pipeline.job_update(job["id"], {"media": info})

    orfao = media.path_for("demo", "job-orfao", ".mp4")
    orfao.write_bytes(MP4)
    antigo = time.time() - 3 * 86400
    os.utime(orfao, (antigo, antigo))                     # órfão "velho"

    novo = media.path_for("demo", "job-recem-baixado", ".mp4")
    novo.write_bytes(MP4)                                 # órfão recente: não pode sair

    rel = retention.run(force=True)
    assert media.resolve(media.relative(orfao)) is None, "órfão velho deveria sair"
    assert media.resolve(media.relative(novo)) is not None, "arquivo recém-criado não sai"
    assert media.resolve(info["file"]) is not None, "arquivo com job vivo não sai"
    assert rel["removidos"]["arquivos"] >= 1
    print("ok retenção: varre órfãos de mídia sem tocar em arquivo referenciado")


def test_retencao_desligada_nao_faz_nada():
    storage._write(pipeline.JOBS_FILE, [
        {"id": f"velho-{i}", "status": "pronto", "created_at": _iso_dias_atras(999)} for i in range(20)])
    _cfg(RETENTION_ENABLED="0")
    rel = retention.run()
    assert rel["executado"] is False
    assert len(pipeline.jobs_list()) == 20
    _cfg(RETENTION_ENABLED="1")
    print("ok retenção: RETENTION_ENABLED=0 desliga sem apagar nada")


def test_status():
    st = retention.status()
    assert st["config"]["dias"] == 90
    assert "contagens" in st and "midia" in st
    assert st["midia"]["bytes"] > 0
    print("ok retenção: status expõe config, contagens e uso de disco")


if __name__ == "__main__":
    test_salva_base64_png()
    test_salva_url_com_streaming()
    test_extensao_vem_dos_bytes_nao_da_url()
    test_limite_de_tamanho()
    test_download_desligado()
    test_erro_http()
    test_path_traversal_bloqueado()
    test_job_concluido_guarda_arquivo_e_biblioteca()
    test_job_com_base64()
    test_falha_no_download_nao_perde_o_job()
    test_job_com_erro_nao_tenta_baixar()
    test_retencao_respeita_janela_e_os_recentes()
    test_retencao_nunca_apaga_item_sem_data()
    test_retencao_poda_usage_e_ingeridos()
    test_retencao_preserva_comets()
    test_retencao_limpa_midia_orfa()
    test_retencao_desligada_nao_faz_nada()
    test_status()
    print("\nTODOS OS TESTES DE MÍDIA E RETENÇÃO PASSARAM ✔")
