"""Motor de dados de demonstração — determinístico por semente (query/plataforma).

Gera datasets realistas (distribuição power-law de views, engajamento derivado,
velocidade de viralização) para que o ecossistema seja explorável sem chaves.
Quando as APIs oficiais estão configuradas, os resultados reais têm prioridade
e são mesclados com estes (fonte marcada como 'demo' vs 'oficial').
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Optional

from .providers import normalize_video

# ------------------------------------------------------------ vocabulário
NICHOS = {
    "beleza": ["skincare noturno", "base perfeita", "hidratante facial", "protetor solar",
               "sérum de vitamina C", "make natural", "brow lamination"],
    "casa": ["organizador de cozinha", "luminária LED", "mini processador", "mop giratório",
             "umidificador", "kit potes herméticos", "aspirador portátil"],
    "tech": ["fone bluetooth", "smartwatch", "ring light", "microfone de lapela",
             "carregador magnético", "mini projetor", "teclado mecânico"],
    "fitness": ["garrafa térmica", "elástico de treino", "tapete de yoga", "creatina",
                "whey protein", "corda de pular", "mini stepper"],
    "moda": ["bolsa transversal", "óculos de sol", "tênis casual", "jaqueta corta-vento",
             "kit meias", "acessórios dourados", "pijama de seda"],
    "pets": ["brinquedo interativo", "fonte para gatos", "escova removedora", "petisco natural",
             "caminha ortopédica", "coleira LED", "tapete higiênico"],
    "maternidade": ["babá eletrônica", "mochila maternidade", "esterilizador", "prato com ventosa",
                    "naninha", "tapete de atividades", "copo de transição"],
    "automotivo": ["aspirador veicular", "suporte de celular", "kit polimento", "câmera de ré",
                   "organizador de porta-malas", "calibrador digital", "led automotivo"],
}

HOOK_PATTERNS = [
    "testei {p} por 7 dias e olha no que deu",
    "{p} que está viralizando — será que funciona?",
    "o segredo de {p} que ninguém te conta",
    "comprei {p} mais falado da internet 😳",
    "3 erros que você comete com {p}",
    "POV: você descobriu {p} antes de todo mundo",
    "antes e depois usando {p} (resultado real)",
    "{p} vale o hype? testei pra você",
    "achadinho que mudou minha rotina: {p}",
    "por que todo mundo está falando de {p}?",
    "economizei 70% comprando {p} — veja como",
    "ninguém esperava esse resultado com {p} 🤯",
]

SOUNDS = ["som original — beat acelerado", "funk remix 2.0", "lo-fi chill", "áudio viral da semana",
          "pop instrumental épico", "som original — voz grave", "acoustic cover", "bass drop viral",
          "trend sonora BR", "piano dramático"]

CREATOR_NAMES = [
    "ana.descobertas", "lukinhas.review", "garimpo.digital", "achei.no.br", "vitrine.viral",
    "dicas.da.mai", "top.achados.ofc", "revisa.aqui", "comprei.e.testei", "radar.do.lucas",
    "ofertas.da.bia", "nerd.do.unboxing", "casa.inteligente.br", "rotina.fit.oficial",
    "mundo.pet.dicas", "beleza.sem.filtro", "tech.barato", "achou.zoeira", "testa.tudo.ai",
    "curadoria.prime", "manual.do.consumer", "trend.hunter.br", "lojinha.da.sheila", "venda.mais.shop",
]

LIVE_HOSTS = ["loja.oficial.%s", "%s.store", "garimpo.%s", "shop.%s.oficial"]


def _seed(*parts) -> int:
    h = hashlib.md5("|".join(str(p) for p in parts).encode()).hexdigest()
    return int(h[:12], 16)


def _powerlaw(rnd: random.Random, floor: int, cap: int) -> int:
    """Distribuição de views estilo rede social: muitos pequenos, poucos gigantes."""
    u = rnd.random()
    v = int(floor / ((1 - u) ** 1.6))
    return min(v, cap)


def _age(rnd: random.Random, period: str) -> int:
    hours = {"24h": 24, "7d": 168, "30d": 720, "90d": 2160}.get(period, 2160)
    # concentra no início recente (conteúdo novo viraliza mais)
    return max(2, int(rnd.expovariate(1 / (hours / 2.4))))


# ------------------------------------------------------------ pesquisa de vídeos
def demo_videos(q: str, platform: str, period: str = "30d", limit: int = 24,
                min_views: int = 0) -> list[dict]:
    q = (q or "tendências").strip().lower()
    rnd = random.Random(_seed(q, platform, period))
    slug = re.sub(r"[^a-z0-9áéíóúãõç ]", "", q).strip() or "viral"
    words = slug.split()
    core = " ".join(words[:3])

    out = []
    for i in range(limit):
        views = _powerlaw(rnd, 18_000, 48_000_000)
        if views < min_views:
            views = max(min_views, views // 3)
        likes = int(views * rnd.uniform(0.045, 0.17))
        comments = int(views * rnd.uniform(0.002, 0.011))
        shares = int(views * rnd.uniform(0.004, 0.03)) if platform != "youtube" else int(views * rnd.uniform(0.001, 0.004))
        age_h = _age(rnd, period)
        title = rnd.choice(HOOK_PATTERNS).replace("{p}", core)
        creator = rnd.choice(CREATOR_NAMES)
        tags = [f"#{w}" for w in words[:3]] + rnd.sample(
            ["#achados", "#viral", "#dicas", "#review", "#comprinhas", "#testei",
             "#musthave", "#brasil", "#fy", "#explora"], k=rnd.randint(2, 4))
        out.append(normalize_video({
            "id": f"{abs(_seed(q, platform, i)) % 10**9}",
            "title": title.capitalize(),
            "author": creator,
            "handle": f"@{creator}",
            "views": views, "likes": likes, "comments": comments, "shares": shares,
            "age_hours": age_h,
            "hashtags": tags[:6],
            "sound": rnd.choice(SOUNDS) if platform in ("tiktok", "instagram") else None,
            "duration": rnd.randint(9, 60) if platform != "youtube" else rnd.randint(60, 960),
            "url": "",
            "source": "demo",
        }, platform))
    return out


def search_aggregate(q: str, platforms: list[str], period: str, min_views: int,
                     limit_per_platform: int = 14) -> dict:
    """Gera o conjunto demo de vídeos + facetas (hashtags, sons, criadores)."""
    videos = []
    for p in platforms:
        videos += demo_videos(q, p, period, limit_per_platform, min_views)

    tag_count: dict[str, int] = {}
    sound_count: dict[str, int] = {}
    creator_stat: dict[str, dict] = {}
    for v in videos:
        for t in v["hashtags"]:
            tag_count[t] = tag_count.get(t, 0) + v["views"]
        if v.get("sound"):
            sound_count[v["sound"]] = sound_count.get(v["sound"], 0) + v["views"]
        c = creator_stat.setdefault(v["handle"], {"videos": 0, "views": 0, "platform": v["platform"]})
        c["videos"] += 1
        c["views"] += v["views"]

    top_hashtags = [{"tag": k, "reach": v} for k, v in
                    sorted(tag_count.items(), key=lambda x: -x[1])][:8]
    top_sounds = [{"sound": k, "reach": v} for k, v in
                  sorted(sound_count.items(), key=lambda x: -x[1])][:6]
    top_creators = [{"handle": k, **v} for k, v in
                    sorted(creator_stat.items(), key=lambda x: -x[1]["views"])][:8]
    return {"videos": videos, "top_hashtags": top_hashtags,
            "top_sounds": top_sounds, "top_creators": top_creators}


# ------------------------------------------------------------ produtos
def _category_for(q: str) -> str:
    ql = q.lower()
    for cat, items in NICHOS.items():
        if any(w in ql for w in items) or cat in ql:
            return cat
    rnd = random.Random(_seed(q, "cat"))
    return rnd.choice(list(NICHOS.keys()))


def demo_products(q: Optional[str] = None, category: str = "", sort: str = "gmv",
                  limit: int = 18) -> list[dict]:
    seed_key = (q or "ranking") + "|" + category
    rnd = random.Random(_seed(seed_key, "products"))
    if q:
        cat = _category_for(q)
        pool = [q.strip()] + rnd.sample(NICHOS[cat], k=min(6, len(NICHOS[cat])))
    elif category and category in NICHOS:
        pool = list(NICHOS[category])
    else:
        pool = []
        for items in NICHOS.values():
            pool += items
        rnd.shuffle(pool)

    out = []
    for i, name in enumerate(pool[:limit]):
        price = round(rnd.uniform(19, 249), 2)
        units = _powerlaw(rnd, 120, 90_000)
        gmv = round(units * price * rnd.uniform(0.82, 0.97), 0)
        growth = round(rnd.uniform(-12, 240), 1)
        curve = []
        base = max(10, units // 14)
        v = base * rnd.uniform(0.35, 0.7)
        for d in range(14):
            v = max(5, v * rnd.uniform(0.86, 1.34))
            curve.append(int(v))
        if growth > 0:
            curve[-1] = int(curve[-1] * (1 + growth / 220))
        category_of = next((c for c, its in NICHOS.items() if name in its), "casa")
        sellers = rnd.randint(2, 48)
        out.append({
            "id": f"prod-{abs(_seed(seed_key, name)) % 10**8}",
            "name": name.capitalize(),
            "category": category_of,
            "price": price,
            "units": units,
            "gmv": gmv,
            "growth": growth,
            "curve": curve,
            "creators_promoting": rnd.randint(4, 620),
            "shops": sellers,
            "rating": round(rnd.uniform(3.9, 5.0), 1),
            "commission": round(rnd.uniform(5, 22), 0),
            "source": "demo",
        })
    key = {"gmv": "gmv", "units": "units", "growth": "growth",
           "price": "price", "commission": "commission"}.get(sort, "gmv")
    out.sort(key=lambda p: -p[key])
    return out


def demo_product_detail(product_id: str) -> dict:
    rnd = random.Random(_seed(product_id, "detail"))
    products = demo_products(limit=60)
    prod = next((p for p in products if p["id"] == product_id), None)
    if not prod:
        prod = demo_products(limit=1)[0]
    videos = []
    for p in ("tiktok", "instagram", "youtube"):
        videos += demo_videos(prod["name"], p, "30d", 4)
    videos.sort(key=lambda v: -v["views"])
    live_sessions = [{
        "host": rnd.choice(LIVE_HOSTS) % prod["name"].split()[0].lower(),
        "platform": "tiktok",
        "viewers_peak": rnd.randint(180, 24000),
        "duration_min": rnd.randint(22, 190),
        "gmv": round(prod["gmv"] * rnd.uniform(0.04, 0.2), 0),
        "days_ago": rnd.randint(0, 6),
    } for _ in range(5)]
    live_sessions.sort(key=lambda s: -s["gmv"])
    return {**prod, "top_videos": videos[:9], "lives": live_sessions}


# ------------------------------------------------------------ criadores
def demo_creators(q: Optional[str] = None, platform: str = "all",
                  limit: int = 14) -> list[dict]:
    seed_key = f"{q or 'top'}|{platform}"
    rnd = random.Random(_seed(seed_key, "creators"))
    names = list(CREATOR_NAMES)
    rnd.shuffle(names)
    platforms = ["tiktok", "instagram", "youtube"] if platform == "all" else [platform]
    out = []
    for i, name in enumerate(names[:limit]):
        plat = rnd.choice(platforms)
        followers = _powerlaw(rnd, 8_000, 12_000_000)
        er = round(rnd.uniform(1.4, 11.8), 2)
        gmv = round(followers * rnd.uniform(0.4, 3.2), 0)
        niche = rnd.choice(list(NICHOS.keys()))
        out.append({
            "id": f"cr-{abs(_seed(seed_key, name)) % 10**8}",
            "handle": f"@{name}",
            "platform": plat,
            "niche": niche,
            "followers": followers,
            "engagement_rate": er,
            "videos_30d": rnd.randint(6, 92),
            "gmv_est": gmv,
            "top_product": rnd.choice(NICHOS[niche]).capitalize(),
            "verified": rnd.random() < 0.25,
            "source": "demo",
        })
    out.sort(key=lambda c: -c["gmv_est"])
    return out


# ------------------------------------------------------------ lives
def demo_lives(limit: int = 12) -> list[dict]:
    rnd = random.Random(_seed("lives", time_day(), "seed"))
    out = []
    for i in range(limit):
        prod = rnd.choice([p for items in NICHOS.values() for p in items])
        peak = rnd.randint(150, 68_000)
        out.append({
            "id": f"live-{i}-{abs(_seed(prod, i)) % 10**6}",
            "host": (rnd.choice(LIVE_HOSTS)) % prod.split()[0].lower(),
            "platform": rnd.choice(["tiktok", "instagram", "youtube"]),
            "product": prod.capitalize(),
            "viewers_peak": peak,
            "gmv": round(peak * rnd.uniform(6, 90), 0),
            "units": int(peak * rnd.uniform(0.04, 0.5)),
            "started_min_ago": rnd.randint(3, 720),
            "live_now": rnd.random() < 0.55,
            "source": "demo",
        })
    out.sort(key=lambda l: -l["gmv"])
    return out


# ------------------------------------------------------------ nichos (radar)
def demo_niches(limit: int = 12) -> list[dict]:
    rnd = random.Random(_seed("niches", "v3"))
    micro = [
        ("histórias de navios abandonados", "mistério/documentário"),
        ("restauração de relógios antigos", "artesanato/satisfatório"),
        ("finanças para motoristas de app", "finanças/nicho"),
        ("receitas de marmita congelada fit", "culinária/fitness"),
        ("curiosidades de cidades fantasmas BR", "mistério/brasil"),
        ("organização de garagens pequenas", "casa/faça-você-mesmo"),
        ("treino em casa sem equipamento", "fitness/casa"),
        ("achadinhos de loja de 1,99", "achados/economia"),
        ("idiomas com séries — inglês real", "educação/idiomas"),
        ("pets exóticos legalizados no BR", "pets/educação"),
        ("setup gamer econômico", "tech/gamer"),
        ("maternidade real sem filtro", "maternidade/lifestyle"),
        ("som ASMR de limpeza profunda", "satisfatório/asrm"),
        ("direito do consumidor em 60s", "educação/direito"),
    ]
    out = []
    for name, sub in micro[:limit]:
        videos = rnd.randint(8, 140)
        views = _powerlaw(rnd, 300_000, 90_000_000)
        outlier = min(99, int((views / max(videos, 1)) / 25_000))
        out.append({
            "id": f"niche-{abs(_seed(name)) % 10**7}",
            "niche": name,
            "sub_nicho": sub,
            "platform": rnd.choice(["youtube", "tiktok", "instagram"]),
            "canal_exemplo": "@" + name.replace(" ", ".")[:18],
            "videos": videos,
            "views_total": views,
            "views_por_video": int(views / max(videos, 1)),
            "outlier_score": max(8, outlier),
            "monetizado": rnd.random() < 0.6,
            "faceless": rnd.random() < 0.72,
            "status": rnd.choice(["QUENTE", "EMERGENTE", "EMERGENTE", "NÃO EXPLORADO"]),
            "concorrentes": rnd.randint(0, 14),
            "source": "demo",
        })
    out.sort(key=lambda n: -n["outlier_score"])
    return out


def time_day() -> str:
    import time as _t
    return _t.strftime("%Y-%m-%d")
