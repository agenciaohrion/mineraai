"""Motor de IA do Estúdio — gratuito por padrão.

Estratégia em camadas:
  1. Se GROQ_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY estiver configurada,
     usamos o LLM real (tiers gratuitos existem nos três).
  2. Caso contrário (ou se a chamada falhar), cai no motor interno baseado em
     frameworks de copywriting (AIDA, PAS, hooks de padrão) — 100% offline.
"""
from __future__ import annotations

import json
import random
import hashlib
from typing import Optional

import httpx

from . import storage

TIMEOUT = 45.0


# ================================================================= LLM
def _llm_config() -> Optional[tuple[str, str]]:
    cfg = storage.settings_get()
    if cfg.get("GROQ_API_KEY"):
        return ("groq", cfg["GROQ_API_KEY"])
    if cfg.get("GEMINI_API_KEY"):
        return ("gemini", cfg["GEMINI_API_KEY"])
    if cfg.get("OPENAI_API_KEY"):
        return ("openai", cfg["OPENAI_API_KEY"])
    return None


async def _ask_llm(prompt: str) -> Optional[str]:
    prov = _llm_config()
    if not prov:
        return None
    kind, key = prov
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            if kind == "groq":
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": "llama-3.3-70b-versatile",
                          "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.85})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            if kind == "openai":
                cfg = storage.settings_get()
                r = await client.post(
                    (cfg.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
                    + "/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": cfg.get("OPENAI_MODEL") or "gpt-4o-mini",
                          "messages": [{"role": "user", "content": prompt}],
                          "temperature": 0.85})
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
            if kind == "gemini":
                r = await client.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"gemini-2.0-flash:generateContent?key={key}",
                    json={"contents": [{"parts": [{"text": prompt}]}],
                          "generationConfig": {"temperature": 0.85}})
                r.raise_for_status()
                parts = r.json()["candidates"][0]["content"]["parts"]
                return "".join(p.get("text", "") for p in parts)
    except Exception:
        return None
    return None


def _rnd(*parts) -> random.Random:
    return random.Random(int(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:10], 16))


# ================================================================= Hooks
HOOK_FORMULAS = [
    ("Curiosidade", "Pare de rolar o feed: {p} faz o que nenhum concorrente conseguiu — e o motivo é absurdo."),
    ("Prova social", "Mais de {n} pessoas já trocaram tudo por {p}. Eu fui entender por quê."),
    ("Dor → solução", "Se você perde tempo com {dor}, {p} resolve isso em segundos. Olha isso."),
    ("Contraste", "Eu achei que {p} era golpe… até testar por 7 dias seguidos."),
    ("Escassez", "O estoque de {p} some toda semana. Quando chegar no preço de hoje, corre."),
    ("Lista", "3 coisas que descobri usando {p} que ninguém te conta (a 2ª mudou tudo)."),
    ("POV", "POV: você descobriu {p} antes de virar febre nacional."),
    ("Antes/Depois", "Antes de {p}: caos. Depois de {p}: olha esse resultado real."),
    ("Autoridade", "Testei 12 opções parecidas. Só {p} sobreviveu ao meu teste de estresse."),
    ("Pergunta-gancho", "E se {p} for o motivo de você ainda não ter resultado com {dor}?"),
    ("Confissão", "Comprei {p} escondido só pra testar. Preciso confessar o que aconteceu."),
    ("Desafio", "Duvido você usar {p} por 7 dias e não querer comprar outro."),
]


async def generate_hooks(product: str, niche: str = "", audience: str = "",
                         tone: str = "direto", count: int = 10) -> dict:
    prompt = (f"Você é um copywriter sênior de anúncios virais no Brasil. "
              f"Produto: {product}. Nicho: {niche or 'geral'}. Público: {audience or 'amplo'}. "
              f"Tom: {tone}. Gere {count} hooks de até 12 palavras para vídeos curtos "
              f"(TikTok/Reels/Shorts), um por linha, numerados, sem repetir fórmula. "
              f"Responda apenas com a lista.")
    llm = await _ask_llm(prompt)
    engine = "llm"
    hooks = []
    if llm:
        for line in llm.strip().splitlines():
            t = line.strip(" -•\t0123456789.)").strip()
            if t:
                hooks.append({"formula": "IA", "hook": t})
            if len(hooks) >= count:
                break
    if len(hooks) < max(3, count // 2):
        engine = "motor-interno" if not hooks else engine
        rnd = _rnd(product, niche, tone)
        dores = {"beleza": "sua rotina de pele", "casa": "bagunça em casa",
                 "fitness": "falta de energia no treino", "tech": "cabos e lentidão",
                 "moda": "looks repetidos", "pets": "pelo espalhado pela casa"}.get(
            niche, "seu problema de sempre")
        pool = list(HOOK_FORMULAS)
        rnd.shuffle(pool)
        hooks = []
        for formula, tmpl in pool[:count]:
            hooks.append({
                "formula": formula,
                "hook": tmpl.format(p=product, n=f"{rnd.randint(3, 48)} mil", dor=dores),
            })
        engine = "motor-interno"
    return {"engine": engine, "product": product, "hooks": hooks[:count]}


# ================================================================= Roteiro UGC / Dark
def _script_internal(product: str, niche: str, duration: int, fmt: str) -> dict:
    rnd = _rnd(product, fmt, duration)
    hook = rnd.choice(HOOK_FORMULAS)[1].format(
        p=product, n="12 mil", dor="esse problema chato")
    beats = int(max(4, duration // 8))
    cena_tempo = max(2, duration // beats)
    cenas = []
    estrutura = [
        ("GANCHO", f"Câmera na mão, rosto próximo. Falar a frase: “{hook}” Cortar em 1.5s.",
         "Legendão na tela + zoom rápido"),
        ("PROBLEMA", f"Mostrar a dor real que {product} resolve. Sem fala bonita: "
                     "situação cotidiana e reconhecível.", "Corte seco, som ambiente"),
        ("APRESENTAÇÃO", f"Revelar {product} em close. Mostrar textura/detalhe. "
                         "Frase curta: o que é e pra quem é.", "Slow zoom + música sobe"),
        ("DEMO", "Uso real do produto em 2-3 ângulos. Nada de estúdio: mesa de casa, "
                 "luz natural, mão tremendo levemente = autenticidade.", "Cortes no beat da música"),
        ("PROVA", "Print de avaliação 5 estrelas / antes e depois / reação espontânea.",
         "Overlay de texto com a prova"),
        ("OFERTA", "Ancorar preço: “custa menos que um lanche por dia” + benefício principal.",
         "Texto com preço destacado"),
        ("CTA", f"Chamada única e clara: comentar a palavra-chave, clicar no link ou "
                f"salvar o vídeo. Uma ação só.", "Tela final com seta/adesivo"),
    ]
    for i in range(beats):
        nome, desc, ed = estrutura[i % len(estrutura)]
        cenas.append({"beat": beats - i if i < 3 else nome, "nome": nome,
                      "tempo": f"{cena_tempo}s", "descricao": desc, "edicao": ed})
    narracao = (f"{hook} "
                f"Eu sinceramente não botava fé. Mas depois de usar {product} por uma semana, "
                f"preciso te contar: muda o jogo. Olha a diferença. "
                f"E o melhor: cabe no bolso. Se você chegou até aqui, comenta QUERO que eu te mando o link.")
    return {
        "titulo_sugerido": f"{product.capitalize()} — vale o hype?",
        "formato": fmt,
        "duracao": duration,
        "hook": hook,
        "cenas": cenas,
        "narracao": narracao,
        "legendas": "Ativar legendas dinâmicas palavra por palavra (retenção +35%).",
        "musica": rnd.choice(["trend sonora BR em alta", "beat acelerado com drop no beat 3",
                              "lo-fi leve para fundo falado", "som original com voz"]),
        "dicas_retencao": [
            "Primeiro frame já em movimento — nunca começar parado.",
            "Cortar toda respiração na edição (jump cuts agressivos).",
            "Trocar ângulo ou zoom a cada 2-4 segundos.",
            "Loop final: terminar conectando com a primeira frase.",
        ],
    }


async def generate_script(product: str, niche: str = "", duration: int = 30,
                          fmt: str = "ugc") -> dict:
    base = _script_internal(product, niche, duration, fmt)
    prompt = (f"Reescreva apenas o HOOK e a NARRAÇÃO deste roteiro de vídeo curto "
              f"({duration}s, formato {fmt}) para o produto “{product}”, nicho {niche or 'geral'}, "
              f"em português do Brasil, linguagem falada e natural, sem soar como IA. "
              f"Responda em JSON: {{\"hook\": \"...\", \"narracao\": \"...\"}}")
    llm = await _ask_llm(prompt)
    engine = "motor-interno"
    if llm:
        try:
            data = json.loads(llm[llm.find("{"):llm.rfind("}") + 1])
            if data.get("hook") and data.get("narracao"):
                base["hook"] = data["hook"]
                base["narracao"] = data["narracao"]
                engine = "llm"
        except Exception:
            pass
    base["engine"] = engine
    return base


# ================================================================= Legenda + hashtags
BASE_TAGS = ["#achados", "#dicas", "#viral", "#fyp", "#brasil", "#recomendo",
             "#comprinhas", "#review", "#testei", "#explora"]


async def generate_caption(product: str, platform: str, benefit: str = "") -> dict:
    rnd = _rnd(product, platform)
    rnd.shuffle(BASE_TAGS)
    words = [w for w in product.lower().split() if len(w) > 3][:2]
    tags = [f"#{w.replace(' ', '')}" for w in words] + BASE_TAGS[: {"tiktok": 5,
                                                                     "instagram": 9,
                                                                     "youtube": 3}.get(platform, 5)]
    corpo = {
        "tiktok": (f"espera até o final 👀 testei {product} de verdade e o resultado me "
                   f"surpreendeu. {benefit or 'Salva esse vídeo pra não perder!'}. "
                   f"Comenta EU QUERO que te conto onde achei 👇"),
        "instagram": (f"{product.capitalize()} {benefit or '— o achadinho do momento'} ✨\n\n"
                      "Arrasta pra ver o antes e depois 👉\n"
                      "💬 Marca alguém que precisa ver isso\n"
                      "🔗 Link na bio\n"
                      "Salva pra não esquecer 📌"),
        "youtube": (f"Testei {product} por 7 dias e esse é o resultado HONESTO. "
                    f"Nesse vídeo: unboxing, teste real, prós, contras e se vale o preço. "
                    f"Se inscreve pra mais testes sem filtro!"),
    }.get(platform, "")
    prompt = (f"Escreva uma legenda curta e viral em PT-BR para {platform} sobre o produto "
              f"{product}. Máximo 2 frases + 1 chamada para ação. Responda só com a legenda.")
    llm = await _ask_llm(prompt)
    if llm:
        corpo = llm.strip()
    return {"engine": "llm" if llm else "motor-interno", "platform": platform,
            "caption": corpo, "hashtags": tags}


# ================================================================= Títulos SEO (YouTube)
TITLE_PATTERNS = [
    "TESTEI {p} POR 7 DIAS — OLHA NO QUE DEU 😱",
    "{p}: VALE A PENA EM 2026? (Verdade Sem Filtro)",
    "A VERDADE sobre {p} que NINGUÉM te conta",
    "{p} — Antes e Depois REAL (funciona mesmo?)",
    "NÃO COMPRE {p} antes de ver isso!",
    "5 MOTIVOS pra ter {p} (o 3º me convenceu)",
    "{p} BARATO: encontrei o melhor custo-benefício",
    "REAGINDO aos resultados de {p} — chocante",
    "{p} vs CONCORRENTE: qual vence o teste?",
    "COMPREI {p} MAIS VIRAL DA INTERNET (review completo)",
]


async def generate_titles(theme: str) -> dict:
    rnd = _rnd(theme, "titles")
    titles = []
    pool = list(TITLE_PATTERNS)
    rnd.shuffle(pool)
    for t in pool[:10]:
        titles.append(t.replace("{p}", theme.capitalize()))
    desc = (f"Vídeo completo sobre {theme.lower()}: unboxing, teste na prática, prós e "
            f"contras, comparativo e veredito final com opinião sincera.\n\n"
            f"⏱ CAPÍTULOS:\n00:00 Introdução\n00:45 Unboxing\n02:10 Teste real\n"
            f"05:30 Prós e contras\n07:15 Veredito\n\n"
            f"🔔 Se inscreve e ativa o sininho pra não perder os próximos testes!")
    tags = [theme.lower(), f"{theme.lower()} review", f"{theme.lower()} vale a pena",
            "review sincero", "unboxing", "teste real", "custo benefício",
            "melhores 2026", "comprinhas", "análise completa"]
    engine = "motor-interno"
    prompt = (f"Gere 10 títulos de YouTube altamente clicáveis (sem clickbait falso) em PT-BR "
              f"sobre “{theme}”. Um por linha, numerados, com no máximo 65 caracteres.")
    llm = await _ask_llm(prompt)
    if llm:
        got = [l.strip(" -•\t0123456789.)").strip()
               for l in llm.splitlines() if l.strip()]
        if len(got) >= 5:
            titles = got[:10]
            engine = "llm"
    return {"engine": engine, "theme": theme, "titles": titles,
            "description": desc, "tags": tags}


# ================================================================= Viral Lab (análise)
async def analyze_video(subject: str) -> dict:
    rnd = _rnd(subject, "lab")
    outlier = rnd.randint(41, 97)
    formatos = ["lista com contagem regressiva", "storytelling com loop aberto",
                "POV + zoom progressivo", "antes/depois com prova social",
                "talking head dinâmico com B-roll"]
    hooks = [
        "abre com afirmação polêmica + corte seco em 1.2s",
        "começa no meio da ação (in media res) e depois explica",
        "pergunta direta ao espectador olhando pra câmera",
        "texto na tela promete o payoff antes da primeira fala",
    ]
    analise = {
        "outlier_score": outlier,
        "veredito": ("OUTLIER FORTE — formato com desempenho muito acima da média do canal."
                     if outlier >= 75 else
                     "BOM DESEMPENHO — desempenho acima da média, replicável com ajustes."
                     if outlier >= 55 else
                     "DENTRO DA MÉDIA — desempenho esperado; teste variações de hook."),
        "formato_detectado": rnd.choice(formatos),
        "hook_detectado": rnd.choice(hooks),
        "beats": [
            {"tempo": "0-2s", "funcao": "Gancho: promessa forte + movimento"},
            {"tempo": "2-8s", "funcao": "Contexto mínimo: por que isso importa AGORA"},
            {"tempo": "8-18s", "funcao": "Demonstração / desenvolvimento com cortes no beat"},
            {"tempo": "18-24s", "funcao": "Prova social ou resultado mensurável"},
            {"tempo": "24-30s", "funcao": "CTA único + loop de retenção"},
        ],
        "hipoteses_virais": [
            "Retenção alta por cortes a cada ~2s — o algoritmo interpreta como conteúdo premium.",
            "O hook gera comentários de dúvida (“isso funciona?”), o que empurra distribuição.",
            "Som em trend + tema evergreen = alcance duplo (busca + FYP).",
            "Compartilhamentos altos por utilidade imediata (salvar/enviar).",
        ],
        "plano_replicacao": [
            "Replique o formato com SEU produto nos primeiros 2s.",
            "Mantenha a duração ±10% do original.",
            "Use a mesma trend sonora (licenciada) ou som original falado.",
            "Publique no horário de pico do nicho (19h-22h) e responda comentários na 1ª hora.",
        ],
        "engine": "motor-interno",
    }
    prompt = (f"Analise estrategicamente este vídeo/canal para replicação: “{subject}”. "
              f"Responda em JSON com as chaves: formato_detectado, hook_detectado, "
              f"hipoteses_virais (lista com 4 itens em PT-BR).")
    llm = await _ask_llm(prompt)
    if llm:
        try:
            d = json.loads(llm[llm.find("{"):llm.rfind("}") + 1])
            for k in ("formato_detectado", "hook_detectado"):
                if d.get(k):
                    analise[k] = d[k]
            if isinstance(d.get("hipoteses_virais"), list) and d["hipoteses_virais"]:
                analise["hipoteses_virais"] = d["hipoteses_virais"]
            analise["engine"] = "llm"
        except Exception:
            pass
    return analise


# ================================================================= Narração (Voice Studio)
def prepare_narration(text: str, tone: str = "suspense") -> dict:
    """Marca pausas dramáticas e emoção para TTS (estilo DarkLAB Voice Studio)."""
    import re
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    marked = []
    for i, s in enumerate(sentences):
        s = s.strip()
        if not s:
            continue
        pause = "[pausa 0.8s]" if tone == "suspense" and i < len(sentences) - 1 else "[pausa 0.35s]"
        if tone == "energetico":
            s = s.rstrip(".") + "!" if s.endswith(".") else s
            pause = "[pausa 0.2s]"
        marked.append(f"{s} {pause}")
    ssml_hint = " ".join(marked)
    plain = re.sub(r"\[pausa [\d.]+s\]", "...", ssml_hint)
    return {
        "original": text,
        "tom": tone,
        "marcacao": ssml_hint,
        "para_leitura": plain,
        "duracao_estimada_s": round(len(plain.split()) / 2.4),
        "dica": ("Use o player de voz embutido (grátis, roda no navegador) ou cole a "
                 "marcação no seu TTS preferido (ElevenLabs, Edge TTS, Groq TTS)."),
    }
