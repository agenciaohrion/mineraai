"""Motor de métricas unificadas do MineraAI.

Centraliza TODA a matemática do produto. Nenhum endpoint calcula score na mão:
tudo passa por aqui, para que o mesmo vídeo tenha sempre o mesmo número,
venha ele da API oficial, da Virlo, da mineração própria ou do modo demonstração.

Conceitos-chave (os diferenciais dos apps que estamos unificando):

  viral_score     — quão rápido o vídeo está performando AGORA (0-100)
  outlier_score   — quão acima do normal do criador o vídeo está (0-100)
                    é o sinal preditivo: vídeo furando a curva antes do pico
  velocity        — views por hora desde a publicação
  gmv_estimate    — faixa de faturamento estimado (nunca um número só)
  trend_score     — força de uma curva de 14/30 dias (crescimento + momento)
"""
from __future__ import annotations

import math
import statistics
from typing import Iterable, Optional, Sequence

SCHEMA_VERSION = "1.0"

# Referências de normalização (views/hora consideradas "muito altas")
VELOCITY_REF = 12_000
ENGAGEMENT_REF = 12.0
# Piso de baseline: criador pequeno não deve gerar outlier infinito
BASELINE_FLOOR = 2_500
BASELINE_CAP = 50_000_000


# ------------------------------------------------------------------ utilidades
def safe_div(a: float, b: float, default: float = 0.0) -> float:
    try:
        return a / b if b else default
    except ZeroDivisionError:
        return default


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def log_ratio(value: float, ref: float, cap: float = 12.0) -> float:
    """Escala logarítmica de razão → 0..cap (1x = 0, 10x ≈ 2.3, 100x ≈ 4.6)."""
    if value <= 0 or ref <= 0:
        return 0.0
    return min(cap, math.log10(max(1.0, value / ref)) * 2.3)


def percentile_rank(values: Sequence[float], x: float) -> float:
    """Em que percentil x está dentro de values (0-100)."""
    if not values:
        return 0.0
    below = sum(1 for v in values if v <= x)
    return round(100 * below / len(values), 1)


# ------------------------------------------------------------------ scores
def engagement_rate(views: int, likes: int, comments: int, shares: int = 0) -> float:
    """Engajamento em % das views (likes + comentários + shares)."""
    return round(safe_div(likes + comments + shares, views) * 100, 2)


def velocity(views: int, age_hours: float) -> float:
    """Views por hora desde a publicação."""
    return round(safe_div(views, max(float(age_hours or 1), 1.0)), 1)


def freshness(age_hours: float, horizon: float = 2400) -> float:
    """1.0 para conteúdo fresquíssimo → 0.0 para conteúdo velho."""
    return _clamp(100 - (min(float(age_hours or 0), horizon) / horizon) * 100, 0, 100) / 100


def viral_score(views: int, likes: int, comments: int, shares: int,
                age_hours: float) -> int:
    """0-100 — combina velocidade (50%), engajamento (35%) e frescor (15%)."""
    views = int(views or 0)
    if views <= 0:
        return 0
    v = velocity(views, age_hours)
    er = engagement_rate(views, likes, comments, shares)
    score = (0.50 * _clamp(safe_div(v, VELOCITY_REF) * 100)
             + 0.35 * _clamp(safe_div(er, ENGAGEMENT_REF) * 100)
             + 0.15 * freshness(age_hours) * 100)
    return int(round(_clamp(score)))


def outlier_score(views: int, baseline_views: float) -> int:
    """0-100 — quanto o vídeo supera a mediana do próprio criador.

    É o sinal que nenhuma plataforma entrega no painel nativo: um criador de
    8 mil views medianas que estoura 400 mil tem outlier ~50x = score ~100.
    """
    base = max(float(baseline_views or 0), BASELINE_FLOOR)
    ratio = safe_div(max(views, 0), base)
    if ratio <= 1.0:
        return 0
    # log10(2)=0.30 → ~14 ; log10(10)=1 → 46 ; log10(50)=1.69 → 78 ; log10(500) → 100
    return int(round(_clamp(math.log10(ratio) * 46 + 14)))


def outlier_ratio(views: int, baseline_views: float) -> float:
    base = max(float(baseline_views or 0), BASELINE_FLOOR)
    return round(safe_div(max(views, 0), base), 2)


TIERS = [
    (85, "extremo", "🚀", "outlier extremo"),
    (70, "forte", "🔥", "outlier forte"),
    (50, "claro", "📈", "acima da curva"),
    (30, "leve", "↗", "levemente acima"),
    (0, "normal", "·", "dentro do normal"),
]


def tier(score: int) -> dict:
    for floor, slug, icon, label in TIERS:
        if score >= floor:
            return {"slug": slug, "icon": icon, "label": label}
    return {"slug": "normal", "icon": "·", "label": "dentro do normal"}


# ------------------------------------------------------------------ baseline
def creator_baseline(videos: Iterable[dict]) -> dict[str, dict]:
    """Calcula a mediana de views por criador a partir do conjunto observado.

    Com poucos vídeos por criador a mediana é frágil, então mesclamos com um
    piso (BASELINE_FLOOR) para não inflar outliers de criadores desconhecidos.
    """
    by_handle: dict[str, list[int]] = {}
    for v in videos:
        handle = (v.get("handle") or v.get("author") or "").strip().lower()
        if not handle:
            continue
        by_handle.setdefault(handle, []).append(int(v.get("views") or 0))

    out: dict[str, dict] = {}
    for handle, views in by_handle.items():
        median = statistics.median(views) if views else BASELINE_FLOOR
        baseline = min(BASELINE_CAP, max(median, BASELINE_FLOOR))
        out[handle] = {
            "handle": handle,
            "videos_observados": len(views),
            "mediana_views": int(median),
            "baseline": int(baseline),
            "confianca": "alta" if len(views) >= 3 else "baixa",
        }
    return out


# ------------------------------------------------------------------ enriquecimento
def corpus_baseline(videos: Iterable[dict]) -> float:
    """Mediana de views do conjunto observado — o "normal" do nicho/pesquisa."""
    views = [int(v.get("views") or 0) for v in videos if int(v.get("views") or 0) > 0]
    return float(statistics.median(views)) if views else BASELINE_FLOOR


def enrich_video(video: dict, baselines: Optional[dict[str, dict]] = None,
                 fallback_baseline: Optional[float] = None) -> dict:
    """Devolve o vídeo com todos os campos derivados preenchidos.

    Baseline do criador quando há histórico suficiente; senão, a mediana do
    conjunto pesquisado (o "normal" do nicho) — nunca o próprio vídeo, que
    tornaria todo outlier igual e inútil.
    """
    v = dict(video)
    views = int(v.get("views") or 0)
    age_h = float(v.get("age_hours") or 24)
    v["velocity"] = velocity(views, age_h)
    v["engagement"] = v.get("engagement") or engagement_rate(
        views, int(v.get("likes") or 0), int(v.get("comments") or 0),
        int(v.get("shares") or 0))
    v["viral_score"] = v.get("viral_score") or viral_score(
        views, int(v.get("likes") or 0), int(v.get("comments") or 0),
        int(v.get("shares") or 0), age_h)

    handle = (v.get("handle") or v.get("author") or "").strip().lower()
    base = (baselines or {}).get(handle)
    if base and base.get("confianca") == "alta":
        baseline = base["baseline"]
        v["creator_confidence"] = "alta"
        v["creator_median_views"] = base["mediana_views"]
    else:
        baseline = max(BASELINE_FLOOR, float(
            fallback_baseline if fallback_baseline else (base or {}).get("baseline")
            or BASELINE_FLOOR))
        v["creator_confidence"] = "estimada"
        v["creator_median_views"] = int(baseline)
    v["creator_baseline"] = int(baseline)
    v["outlier_ratio"] = outlier_ratio(views, baseline)
    v["outlier_score"] = outlier_score(views, baseline)
    v["tier"] = tier(v["outlier_score"])
    return v


def enrich_videos(videos: Sequence[dict]) -> list[dict]:
    """Enriquece um lote calculando o baseline de criador do próprio lote."""
    baselines = creator_baseline(videos)
    fallback = corpus_baseline(videos)
    return [enrich_video(v, baselines, fallback) for v in videos]


# ------------------------------------------------------------------ GMV / commerce
CONFIDENCE_RANGE = {
    "alta": (0.82, 1.18),
    "media": (0.68, 1.32),
    "baixa": (0.45, 1.65),
}


def gmv_estimate(units: int, price: float, confidence: str = "media") -> dict:
    """GMV estimado SEMPRE como faixa — é assim que Kalodata/FastMoss operam.

    Devolver um número único cria expectativa de precisão que os dados públicos
    não sustentam. A faixa é a entrega honesta e continua acionável.
    """
    low_f, high_f = CONFIDENCE_RANGE.get(confidence, CONFIDENCE_RANGE["media"])
    point = round(float(units) * float(price), 2)
    return {
        "gmv": round(point),
        "gmv_low": round(point * low_f),
        "gmv_high": round(point * high_f),
        "confidence": confidence,
        "method": "unidades estimadas × ticket médio, ajustado por faixa de confiança",
    }


def gmv_from_views(views: int, price: float, conversion: tuple[float, float] = (0.004, 0.02),
                   confidence: str = "baixa") -> dict:
    """Estimativa a partir de views (quando não há unidades observadas)."""
    units_low = int(views * conversion[0])
    units_high = int(views * conversion[1])
    point = int((units_low + units_high) / 2)
    est = gmv_estimate(point, price, confidence)
    est["units"] = point
    est["units_low"] = units_low
    est["units_high"] = units_high
    return est


# ------------------------------------------------------------------ séries temporais
def moving_average(series: Sequence[float], window: int = 3) -> list[float]:
    if not series:
        return []
    window = max(1, int(window))
    out = []
    for i in range(len(series)):
        chunk = series[max(0, i - window + 1): i + 1]
        out.append(round(sum(chunk) / len(chunk), 1))
    return out


def growth_rate(series: Sequence[float], window: int = 7) -> float:
    """Variação % entre a primeira e a última janela da série."""
    if len(series) < 2:
        return 0.0
    window = min(max(1, window), len(series) // 2 or 1)
    head = statistics.median(series[:window]) if series[:window] else 0
    tail = statistics.median(series[-window:]) if series[-window:] else 0
    return round(safe_div(tail - head, head) * 100, 1) if head else 0.0


def trend_score(series: Sequence[float]) -> int:
    """0-100 — junta crescimento (60%) e aceleração recente (40%)."""
    if len(series) < 3:
        return 0
    growth = growth_rate(series)
    recent = growth_rate(series[-4:], window=2) if len(series) >= 4 else growth
    score = (0.6 * _clamp(50 + growth / 2)
             + 0.4 * _clamp(50 + recent / 2))
    return int(round(_clamp(score)))


def momentum(series: Sequence[float]) -> str:
    """Classifica o momento da curva em 4 estados."""
    if len(series) < 3:
        return "estável"
    recent = growth_rate(series, window=max(1, len(series) // 3))
    if recent > 25:
        return "acelerando"
    if recent > 5:
        return "subindo"
    if recent > -10:
        return "estável"
    return "desacelerando"
