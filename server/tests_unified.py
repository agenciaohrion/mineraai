"""Testes offline da camada unificada — zero rede, zero dependência externa.

Rodam com:  .venv/bin/python -m server.tests_unified

Cobrem o que sustenta o produto: métricas (viral/outlier/GMV), esquema e
dedupe entre fontes, billing/cotas e o ciclo de vida dos research agents.
"""
from __future__ import annotations

import time

from fastapi import HTTPException

from server import agents, credits, metrics, schema


# ============================================================ métricas
def test_viral_score():
    base = metrics.viral_score(100_000, 8_000, 400, 900, 12)
    top = metrics.viral_score(9_000_000, 900_000, 40_000, 120_000, 6)
    weak = metrics.viral_score(2_000, 40, 3, 1, 700)
    assert 0 <= weak < base < top <= 100, (weak, base, top)
    assert metrics.viral_score(0, 0, 0, 0, 24) == 0
    print("ok viral_score")


def test_outlier_score():
    # 100x acima do baseline → outlier extremo
    assert metrics.outlier_score(10_000_000, 100_000) >= 90
    # 10x acima → faixa forte
    assert 60 <= metrics.outlier_score(1_000_000, 100_000) <= 80
    # abaixo do baseline → zero (não existe outlier negativo)
    assert metrics.outlier_score(50_000, 100_000) == 0
    # baseline minúsculo cai no piso e não explode
    assert metrics.outlier_score(30_000, 10) <= 100
    assert metrics.tier(90)["slug"] == "extremo"
    assert metrics.tier(0)["slug"] == "normal"
    print("ok outlier_score")


def test_enrich_videos_usa_baseline_do_criador():
    videos = [
        {"handle": "@a", "views": 1_000, "likes": 50, "comments": 5, "shares": 2, "age_hours": 20},
        {"handle": "@a", "views": 1_000, "likes": 50, "comments": 5, "shares": 2, "age_hours": 20},
        {"handle": "@a", "views": 1_100, "likes": 55, "comments": 5, "shares": 2, "age_hours": 21},
        {"handle": "@a", "views": 400_000, "likes": 40_000, "comments": 900, "shares": 3_000,
         "age_hours": 6},
    ]
    out = metrics.enrich_videos(videos)
    viral = next(v for v in out if v["views"] == 400_000)
    assert viral["outlier_score"] >= 80, viral["outlier_score"]
    assert viral["outlier_ratio"] > 100
    assert viral["creator_confidence"] == "alta"
    assert all("viral_score" in v and "velocity" in v for v in out)
    print("ok enrich_videos")


def test_gmv_estimates():
    est = metrics.gmv_estimate(1_000, 49.9)
    assert est["gmv_low"] < est["gmv"] < est["gmv_high"]
    assert est["confidence"] == "media"
    by_views = metrics.gmv_from_views(1_000_000, 100)
    assert by_views["units_low"] < by_views["units_high"]
    assert by_views["gmv_low"] <= by_views["gmv"] <= by_views["gmv_high"]
    print("ok gmv")


def test_trend_scores():
    rising = [10, 12, 15, 19, 26, 38, 55]
    falling = [55, 40, 29, 21, 16, 12, 10]
    assert metrics.trend_score(rising) > metrics.trend_score(falling)
    assert metrics.momentum(rising) in {"acelerando", "subindo"}
    assert metrics.momentum(falling) == "desacelerando"
    assert len(metrics.moving_average(rising, 3)) == len(rising)
    print("ok trend_score / momentum")


# ============================================================ esquema
def test_uid_e_dedupe():
    raw = {"id": "123", "title": "Teste", "author": "ana", "handle": "@ana",
           "views": 1000, "likes": 10, "comments": 1, "shares": 0, "age_hours": 5}
    v = schema.normalize_video(raw, "tiktok")
    assert v["uid"] == "vid:tiktok:123"
    assert v["kind"] == "video" and v["schema_version"]
    assert v["title"] == "Teste"

    # duas versões do MESMO vídeo: oficial vence, mas campos vazios são herdados
    oficial = {**v, "source": "oficial", "thumb": ""}
    demo = {**v, "source": "demo", "thumb": "https://x/thumb.jpg", "sound": "beat"}
    merged = schema.dedupe([oficial, demo], key_fields=("uid",))
    assert len(merged) == 1
    assert merged[0]["source"] == "oficial"
    assert merged[0]["thumb"] == "https://x/thumb.jpg"
    assert merged[0]["sound"] == "beat"
    print("ok uid / dedupe / merge")


def test_normalizadores():
    creator = schema.normalize_creator({"handle": "Ana", "followers": 1000})
    assert creator["handle"] == "@ana" and creator["kind"] == "creator"

    product = schema.normalize_product({
        "name": "Garrafa térmica", "price": 59.9, "units": 1000,
        "curve": [10, 12, 15, 20, 28, 40, 60],
    })
    assert product["gmv"] == 59900
    assert product["gmv_range"]["gmv_high"] > product["gmv"]
    assert product["momentum"] in {"acelerando", "subindo", "estável", "desacelerando"}

    shop = schema.normalize_shop({"name": "Loja X", "gmv": 5000, "catalog": [1, 2]})
    assert shop["kind"] == "shop" and shop["catalog"] == [1, 2]

    live = schema.normalize_live({"host": "loja.oficial", "units": 100, "price": 30})
    assert live["kind"] == "live" and live["gmv"] == 3000
    print("ok normalizadores (creator/product/shop/live)")


def test_validate():
    ok, errors = schema.validate(schema.normalize_video(
        {"id": "1", "title": "ok", "views": 10}, "youtube"))
    assert ok and not errors
    bad, bad_errors = schema.validate({"kind": "video", "uid": "", "views": -5})
    assert not bad and bad_errors
    print("ok validate")


# ============================================================ billing
def _fresh_tenant(plan: str = "free") -> dict:
    return credits.create_tenant(f"teste-{time.time_ns()}", plan)


def test_limites_e_cobranca():
    tenant = _fresh_tenant("free")
    lim = credits.limits(tenant)
    assert lim["credits_total"] == credits.PLANS["free"]["credits"]
    assert lim["credits_remaining"] == lim["credits_total"]

    res = credits.charge(tenant["id"], "search")
    assert res["charged"] == credits.ACTIONS["search"]
    assert res["credits_remaining"] == lim["credits_total"] - res["charged"]

    usage = credits.usage_summary(tenant["id"], 7)
    assert usage["chamadas"] == 1
    assert usage["por_acao"][0]["action"] == "search"
    print("ok limites / cobrança / ledger")


def test_quota_excedida():
    tenant = _fresh_tenant("free")
    total = credits.PLANS["free"]["credits"]
    custo = credits.ACTIONS["agent_run"]
    rodadas = total // custo
    for _ in range(rodadas):
        credits.charge(tenant["id"], "agent_run")
    assert credits.limits(credits.get_tenant(tenant["id"]))["credits_remaining"] == 0
    try:
        credits.charge(tenant["id"], "agent_run")
    except HTTPException as exc:
        assert exc.status_code == 402, exc.status_code
        assert exc.detail["code"] == "quota_exceeded"
        assert exc.detail["credits_needed"] == custo
    else:
        raise AssertionError("deveria ter bloqueado por falta de créditos")
    print("ok 402 quota_exceeded")


def test_rate_limit_diario():
    tenant = _fresh_tenant("free")
    limite = credits.PLANS["free"]["daily_queries"]
    for _ in range(limite):
        credits.charge(tenant["id"], "trends")
    try:
        credits.charge(tenant["id"], "trends")
    except HTTPException as exc:
        assert exc.status_code == 429, exc.status_code
        assert exc.detail["code"] == "rate_limited"
    else:
        raise AssertionError("deveria ter bloqueado pelo limite diário")
    print("ok 429 rate_limited")


def test_plano_e_creditos():
    tenant = _fresh_tenant("free")
    upgraded = credits.set_plan(tenant["id"], "pro")
    lim = credits.limits(upgraded)
    assert lim["plan"] == "pro"
    assert lim["credits_total"] == credits.PLANS["pro"]["credits"]

    credits.grant_credits(tenant["id"], 500, "top-up de teste")
    lim2 = credits.limits(credits.get_tenant(tenant["id"]))
    assert lim2["credits_total"] == credits.PLANS["pro"]["credits"] + 500
    print("ok upgrade de plano / top-up")


def test_chaves_de_api():
    tenant = _fresh_tenant("starter")
    assert len(tenant["api_keys"]) == 1
    nova = credits.create_key(tenant["id"], "ci")
    resolvido = credits.resolve_key(nova["key"])
    assert resolvido and resolvido["id"] == tenant["id"]
    assert credits.resolve_key("mka_invalida") is None

    mascaradas = credits.masked_keys(credits.get_tenant(tenant["id"]))
    assert all("key" not in k and "masked" in k for k in mascaradas)
    assert credits.revoke_key(tenant["id"], nova["id"])
    assert credits.resolve_key(nova["key"]) is None
    print("ok chaves de API")


# ============================================================ agentes
def test_ciclo_de_vida_dos_agentes():
    tenant = _fresh_tenant("pro")
    criado = agents.create_agent(tenant["id"], {
        "name": "Hooks de skincare", "query": "skincare",
        "platform": "tiktok", "schedule": "daily", "objective": "hooks",
    })
    assert criado["id"].startswith("ag_")
    assert criado["next_run"] is not None

    listados = agents.list_agents(tenant["id"])
    assert len(listados) == 1 and listados[0]["runs_count"] == 0

    atualizado = agents.update_agent(criado["id"], tenant["id"], {"schedule": "weekly"})
    assert atualizado["schedule"] == "weekly"

    stats = agents.stats(tenant["id"])
    assert stats["ativos"] == 1 and stats["execucoes"] == 0

    assert agents.get_agent(criado["id"], "outro_tenant") is None
    assert agents.delete_agent(criado["id"], tenant["id"])
    assert agents.list_agents(tenant["id"]) == []
    print("ok ciclo de vida dos agentes")


def test_agente_exige_query():
    tenant = _fresh_tenant("free")
    try:
        agents.create_agent(tenant["id"], {"name": "vazio", "query": ""})
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("agente sem query deveria falhar")
    print("ok validação de agente")


def test_recomendacoes():
    report = {
        "outliers": [{"title": "Teste", "outlier_ratio": 12.5, "creator_baseline": 8000,
                      "platform": "tiktok", "url": "", "outlier_score": 88}],
        "facetas": {"top_hashtags": [{"tag": "#skincare", "reach": 1000}]},
    }
    recs = agents._recommendations(report)
    assert recs and recs[0]["prioridade"] == 1
    assert "12.5x" in recs[0]["porque"]
    assert any("#skincare" in r["acao"] for r in recs)
    print("ok recomendações do agente")


if __name__ == "__main__":
    test_viral_score()
    test_outlier_score()
    test_enrich_videos_usa_baseline_do_criador()
    test_gmv_estimates()
    test_trend_scores()
    test_uid_e_dedupe()
    test_normalizadores()
    test_validate()
    test_limites_e_cobranca()
    test_quota_excedida()
    test_rate_limit_diario()
    test_plano_e_creditos()
    test_chaves_de_api()
    test_ciclo_de_vida_dos_agentes()
    test_agente_exige_query()
    test_recomendacoes()
    print("\nTODOS OS TESTES DA CAMADA UNIFICADA PASSARAM ✔")
