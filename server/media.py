"""Mídia produzida pela Fábrica — o arquivo fica no nosso disco.

Motivo: o RunPod devolve uma URL do S3 dele que **expira**. Se a única referência
do vídeo é essa URL, o job "concluído" de ontem vira um link quebrado amanhã — e
a Biblioteca fica cheia de entradas que não abrem. Então, assim que o worker
termina, o MineraAI baixa o arquivo e guarda em `data/media/<tenant>/<job>.<ext>`.

Também serve para o caminho contrário: quando o worker devolve **base64** em vez
de URL (payload pequeno), o arquivo é decodificado aqui, sem passar por HTTP.

Layout em disco::

    data/media/<tenant>/<job_id>.mp4     (ou .png/.jpg/.webp/.gif)

Tudo que sai daqui é caminho **relativo a `data/`** (`media/demo/job-x.mp4`), para
o JSON do job não guardar caminho absoluto de uma máquina específica.
"""
from __future__ import annotations

import base64
import binascii
import time
from pathlib import Path
from typing import Optional

import httpx

from . import storage

#: raiz da mídia. O "data root" é sempre o diretório **pai** de MEDIA_DIR, então
#: mover/patchar MEDIA_DIR (testes, outro volume) continua consistente.
MEDIA_DIR = storage.DATA_DIR / "media"
MAX_MB_PADRAO = 200
CHUNK = 64 * 1024
TIMEOUT = 120.0

#: assinaturas de arquivo → extensão (o RunPod às vezes devolve sem content-type)
_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"\xff\xd8\xff", ".jpg"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"RIFF", ".webp"),          # RIFF....WEBP
    (b"\x1aE\xdf\xa3", ".webm"),  # matroska/webm
]
_VIDEO_EXT = {".mp4", ".webm", ".mov", ".m4v"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class MediaError(Exception):
    """Falha ao trazer o arquivo para o disco (rede, tamanho, formato)."""


# ------------------------------------------------------------------ utilidades
def _cfg(key: str, default: str = "") -> str:
    return str(storage.settings_get().get(key) or default)


def _data_root() -> Path:
    return MEDIA_DIR.parent


def max_bytes() -> int:
    """Teto de tamanho por arquivo (`MEDIA_MAX_MB`, padrão 200 MB)."""
    try:
        mb = int(float(_cfg("MEDIA_MAX_MB", str(MAX_MB_PADRAO)) or MAX_MB_PADRAO))
    except (TypeError, ValueError):
        mb = MAX_MB_PADRAO
    # 0/negativo desliga o download: evita encher o disco por acidente
    return max(0, mb) * 1024 * 1024


def _safe_part(part: str) -> str:
    limpo = "".join(c for c in (part or "") if c.isalnum() or c in "-_")
    return limpo or "demo"


def tenant_dir(tenant_id: str) -> Path:
    d = MEDIA_DIR / _safe_part(tenant_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(tenant_id: str, job_id: str, ext: str = ".mp4") -> Path:
    ext = ext if ext.startswith(".") and len(ext) <= 6 else ".mp4"
    return tenant_dir(tenant_id) / (f"{_safe_part(job_id)}{ext}")


def relative(path: Path) -> str:
    """Caminho relativo a `data/` — é o que vai no JSON."""
    return path.resolve().relative_to(_data_root().resolve()).as_posix()


def resolve(rel: str) -> Optional[Path]:
    """Resolve um caminho relativo recusando qualquer coisa fora de media/.

    Barreira de path traversal: `../../.env` não pode ser servido por acidente.
    """
    if not rel:
        return None
    base = MEDIA_DIR.resolve()
    alvo = (_data_root() / rel).resolve()
    try:
        alvo.relative_to(base)
    except ValueError:
        return None
    return alvo if alvo.is_file() else None


def guess_ext(head: bytes, content_type: str = "", url: str = "") -> str:
    ct = (content_type or "").lower()
    for assinatura, ext in _MAGIC:
        if head.startswith(assinatura):
            if assinatura == b"RIFF" and b"WEBP" not in head[:16]:
                continue
            return ext
    if head[4:8] == b"ftyp":
        return ".mp4"
    if "video" in ct:
        return ".mp4"
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "webp" in ct:
        return ".webp"
    if "gif" in ct:
        return ".gif"
    sufixo = Path(url.split("?")[0]).suffix.lower() if url else ""
    return sufixo if sufixo in (_VIDEO_EXT | _IMAGE_EXT) else ".mp4"


def is_video(ext: str) -> bool:
    return ext in _VIDEO_EXT


# ------------------------------------------------------------------ gravação
async def save_from_url(url: str, tenant_id: str, job_id: str,
                        limite: Optional[int] = None) -> dict:
    """Baixa o arquivo do worker para `data/media/...` em streaming.

    Streaming (e não `response.content`) porque um vídeo de 100 MB não precisa
    passar inteiro pela memória; e o corte por tamanho acontece durante a
    escrita, não depois.
    """
    limite = max_bytes() if limite is None else limite
    if limite <= 0:
        raise MediaError("download de mídia desativado (MEDIA_MAX_MB=0)")

    dest = path_for(tenant_id, job_id, ".mp4")
    total = 0
    content_type = ""
    head = b""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as cli:
            async with cli.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise MediaError(f"o worker devolveu HTTP {resp.status_code} ao "
                                     f"baixar o arquivo")
                content_type = resp.headers.get("content-type", "")
                with dest.open("wb") as fh:
                    async for pedaco in resp.aiter_bytes(CHUNK):
                        if not head:
                            head = pedaco[:16]
                        total += len(pedaco)
                        if total > limite:
                            fh.close()
                            dest.unlink(missing_ok=True)
                            raise MediaError(
                                f"arquivo maior que o limite de {limite // (1024 * 1024)} MB "
                                "(ajuste MEDIA_MAX_MB)")
                        fh.write(pedaco)
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise MediaError(f"falha de rede ao baixar o vídeo: {exc}") from exc
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    if total == 0:
        dest.unlink(missing_ok=True)
        raise MediaError("o worker devolveu um arquivo vazio")

    # a extensão só é verdadeira depois de olhar os primeiros bytes
    ext = guess_ext(head, content_type, url)
    final = dest.with_suffix(ext)
    if final != dest:
        dest.replace(final)
    return {"file": relative(final), "bytes": total,
            "content_type": content_type or f"video/{ext.lstrip('.')}",
            "ext": ext, "origem": "url"}


def save_base64(data: str, tenant_id: str, job_id: str) -> dict:
    """Salva o que o worker devolveu inline (base64 / data URI)."""
    if not data:
        raise MediaError("saída base64 vazia")
    bruto = data.split(",", 1)[1] if data.startswith("data:") else data
    bruto = "".join(bruto.split())
    bruto += "=" * (-len(bruto) % 4)
    try:
        blob = base64.b64decode(bruto, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise MediaError(f"base64 inválido na saída do worker: {exc}") from exc
    if not blob:
        raise MediaError("base64 decodificado para zero bytes")

    limite = max_bytes()
    if limite and len(blob) > limite:
        raise MediaError(f"arquivo maior que o limite de {limite // (1024 * 1024)} MB")

    ext = guess_ext(blob[:16])
    dest = path_for(tenant_id, job_id, ext)
    dest.write_bytes(blob)
    return {"file": relative(dest), "bytes": len(blob),
            "content_type": f"video/{ext.lstrip('.')}" if is_video(ext)
                            else f"image/{ext.lstrip('.')}",
            "ext": ext, "origem": "base64"}


def delete(rel: str) -> bool:
    caminho = resolve(rel)
    if not caminho:
        return False
    try:
        caminho.unlink()
        return True
    except OSError:
        return False


# ------------------------------------------------------------------ inventário
def usage() -> dict:
    """Quanto a mídia ocupa em disco (por tenant e no total)."""
    arquivos = 0
    total = 0
    por_tenant: dict[str, int] = {}
    if not MEDIA_DIR.exists():
        return {"arquivos": 0, "bytes": 0, "por_tenant": {}}
    for caminho in MEDIA_DIR.rglob("*"):
        if not caminho.is_file():
            continue
        try:
            tamanho = caminho.stat().st_size
        except OSError:
            continue
        arquivos += 1
        total += tamanho
        por_tenant[caminho.parent.name] = por_tenant.get(caminho.parent.name, 0) + tamanho
    return {"arquivos": arquivos, "bytes": total,
            "mb": round(total / (1024 * 1024), 2), "por_tenant": por_tenant}


def prune_orphans(keep: set[str], idade_horas: float = 24.0) -> dict:
    """Apaga arquivos que não pertencem a nenhum job e já têm uma idade mínima.

    A idade mínima evita a corrida com um job que acabou de baixar o arquivo e
    ainda não gravou o JSON.
    """
    removidos = 0
    bytes_livres = 0
    corte = time.time() - idade_horas * 3600
    if not MEDIA_DIR.exists():
        return {"removidos": 0, "bytes_livres": 0}
    for caminho in MEDIA_DIR.rglob("*"):
        if not caminho.is_file():
            continue
        rel = caminho.resolve().relative_to(_data_root().resolve()).as_posix()
        if rel in keep:
            continue
        try:
            if caminho.stat().st_mtime > corte:
                continue
            bytes_livres += caminho.stat().st_size
            caminho.unlink()
            removidos += 1
        except OSError:
            continue
    return {"removidos": removidos, "bytes_livres": bytes_livres}


def info_arquivo(rel: str) -> Optional[dict]:
    """Metadados do arquivo para servir por HTTP."""
    caminho = resolve(rel)
    if not caminho:
        return None
    ext = caminho.suffix.lower()
    tipo = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif"}.get(ext, "application/octet-stream")
    return {"path": caminho, "media_type": tipo, "bytes": caminho.stat().st_size,
            "nome": caminho.name}


def ensure_dirs() -> None:
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
