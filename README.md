# ⛏️ MineraAI — Ecossistema Unificado de Descoberta Viral, Commerce & Criação

**v2 — escopo unificado.** Um único produto que cobre o que quatro ferramentas de
mercado fazem separadamente, com o loop fechado que nenhuma delas tem:
*descobrir → validar o produto → gerar o roteiro → produzir o vídeo → medir o resultado.*

| Referência de mercado | O que o MineraAI implementa |
|---|---|
| **Virlo** (short-form video intelligence) | 🚀 **Outliers** (vídeos furando a curva do próprio criador) + 🤖 **Research Agents** (pesquisa agendada com dossiê entregue no Slack/Discord/webhook) + 📡 **API pública** e **MCP** |
| **ViralFindr** (pesquisa de conteúdo viral) | 🔎 **Radar Viral**: busca por palavra-chave em TikTok, Instagram e YouTube com viral score, filtros (período, ordenação, views mínimas), hashtags dominantes, sons em alta e criadores do tema |
| **Kalodata** (analytics de TikTok Shop) | 📦 **Produtos** com GMV **em faixa de confiança**, unidades, crescimento, curva 14 dias, comissões + 🏪 **Lojas** (catálogo, criadores afiliados, dependência de live) + 👤 **Criadores** + 🔴 **Vídeos & Lives** (live commerce) |
| **DarkLab AI** (laboratório para canais dark) | ✨ **Estúdio IA**: hooks virais, roteiros UGC/dark cena a cena, legendas + hashtags, títulos SEO YouTube, 🧪 **Viral Lab** (engenharia reversa com metadados reais via oEmbed), 🎙️ **Voice Studio** e 🧭 **Radar de Nichos** |
| — (produção em escala) | 🎬 **Fábrica de Vídeos**: jobs de geração enviados ao **n8n → ComfyUI no RunPod serverless**, com entrega do MP4 dentro da plataforma (workflows prontos em `n8n/`) |

### 💳 Camada SaaS (o que faltava para ser produto, não demo)

| Recurso | Como funciona |
|---|---|
| **Multi-tenant** | cada workspace tem plano, créditos, chaves de API e agentes isolados (`POST /api/workspaces` cria um na hora) |
| **Créditos** | toda ação que gasta rede/IA/GPU é cobrada (busca = 2, agent run = 100, vídeo = 250) — mesmo modelo de Virlo e Kalodata |
| **Cotas** | limite diário + teto mensal por plano (free → enterprise), com **HTTP 402/429** explicando exatamente quanto falta |
| **Ledger** | cada consumo é registrado; `/api/billing/usage` mostra por ação e por dia |
| **API keys** | `X-API-Key` (ou Bearer) por workspace, com revogação e último uso |
| **Planos** | free · starter (R$49) · pro (R$199) · enterprise, com upgrade simulado pronto para plugar Stripe |

Além disso: **Dashboard** com visão do dia + **termos em alta em tempo real
(Google Trends BR)**, **Fábrica de Vídeos 🎬** (produção automatizada via
**n8n + RunPod/ComfyUI** — veja [`docs/AUTOMACAO.md`](docs/AUTOMACAO.md)),
**Biblioteca** persistente e **APIs & Conexões** com gestão de chaves e testes.

### 🆓 Pacote de fontes gratuitas integradas (monumental, quase sem custo)

- **Oficiais com chave grátis**: YouTube Data API v3, TikTok Research API,
  Instagram Graph API
- **Sem chave nenhuma**: Scrapling (coleta pública), Mercado Livre (produtos
  reais BR com preço/vendas/reviews), Reddit JSON (pauta viral), Google
  Suggest (demanda de busca), Google Trends RSS, oEmbed YouTube/TikTok
- **Chave grátis opcional**: Pexels (B-roll), Groq/Gemini (LLMs do Estúdio)
- **Produção de vídeo**: n8n (self-host grátis) + RunPod serverless
  (centavos por vídeo) orquestrando ComfyUI — workflows importáveis em `n8n/`

### Fontes de dados em 3 camadas (cada item é rotulado)

| Selo | Fonte | Quando |
|---|---|---|
| 🟢 `oficial` | APIs oficiais (YouTube Data v3, TikTok Research, IG Graph) | chaves configuradas |
| 🔵 `coleta real` | **[Scrapling](https://github.com/D4Vinci/Scrapling)** — coleta pública em tempo real das páginas de busca, com fingerprint TLS de Chrome | ligada por padrão, sem chave |
| 🟣 `demo` | Motor determinístico de demonstração | fallback sempre disponível |

> Design, código e textos 100% originais — as plataformas acima foram usadas apenas
> como referência de *funcionalidades* (features não são copiáveis, código/design sim).

---

## 🚀 Rodando

```bash
./run.sh          # cria o venv, instala dependências e sobe em http://0.0.0.0:8000
```

Sem nenhuma chave configurada a plataforma roda em **modo demonstração**: um motor
determinístico gera datasets realistas (distribuição power-law de views, engajamento
derivado, curvas de venda) para o produto ser explorável de ponta a ponta. Cada item
exibe o selo `demo` ou `oficial` indicando a origem do dado.

---

## 🔌 APIs utilizadas (pesquisa de viabilidade, set/2026)

### Scrapling — coleta pública sem chave (integrado)

O repositório [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling) foi
integrado como camada intermediária de dados reais:

- `Fetcher` com **impersonação de Chrome** (TLS fingerprint) e headers stealth;
- **YouTube**: parsing do JSON `ytInitialData` embutido na página de busca —
  retorna vídeos reais com views, canal, duração e data (sem cota, sem chave);
- **TikTok**: parsing do `__UNIVERSAL_DATA_FOR_REHYDRATION__` da busca;
- **Instagram**: tentativa na página pública de hashtag (normalmente exige
  login — para IG o caminho recomendado segue sendo a Graph API oficial);
- **Google Trends**: RSS público oficial → termos em alta no Brasil em tempo
  real, exibidos no Dashboard e clicáveis para garimpar no Radar Viral;
- **Circuit breaker**: se uma varredura falhar por completo (ex.: servidor sem
  saída de rede), a coleta entra em cooldown de 10 min para não atrasar buscas;
  qualquer sucesso reseta o circuito;
- **Modo stealth opcional** (`scrapling install` + checkbox na aba de APIs)
  usa o StealthyFetcher com navegador real para sites com anti-bot pesado.

Uso responsável: 1 requisição por plataforma/busca, timeouts curtos, retries
mínimos e sem contornar login/paywall.

Testes dos parsers (sem rede): `.venv/bin/python -m server.tests_scrapling`

### Oficiais — prioridade do projeto

| API | Custo | Requisitos | Uso no MineraAI |
|---|---|---|---|
| **YouTube Data API v3** | ✅ Gratuita — 10.000 unidades/dia (`search` = 100 unid., `videos.list` = 1 unid.) | Chave simples no Google Cloud Console | Busca real de vídeos com views/likes/comentários — **a única das 3 redes com busca pública gratuita** |
| **TikTok Research API** | ✅ Gratuita | Aprovação restrita a instituições acadêmicas/sem fins lucrativos (revisão de semanas a meses); uso não-comercial | Busca de vídeos por keyword com métricas completas |
| **Instagram Graph API** | ✅ Gratuita | Conta **Business/Creator** vinculada a uma Página + app aprovado (Meta App Review). Limite oficial: 30 hashtags únicas/7 dias | Busca de mídia por hashtag (`ig_hashtag_search` → `top_media`) |

**Como conectar:** aba *APIs & Conexões* dentro do app (ou copie `.env.example` → `.env`).

### Alternativas pesquisadas (para cobrir as lacunas das oficiais)

- **Apify** — atores prontos de TikTok/IG com créditos grátis iniciais (scraping estruturado).
- **RapidAPI** — marketplace com dezenas de APIs sociais com tier gratuito.
- **Google Trends / pytrends** — termômetro gratuito de termos em alta.
- **Reddit API** — gratuita, útil para descoberta de micro-nichos e dores do público.
- **Groq (Llama) e Google Gemini** — tiers gratuitos generosos de LLM; elevam a qualidade
  do Estúdio IA quando conectados (o motor interno de copywriting já funciona sem chave).
- **Web Speech API** — síntese de voz gratuita do navegador (prévia do Voice Studio).

### Por que o modo demonstração existe

TikTok encerrou o acesso amplo gratuito e a Research API exige vínculo acadêmico;
a Meta fechou o acesso público do Instagram em 2020 (Graph API cobre apenas contas
autorizadas + busca de hashtags limitada). Ou seja: **nenhuma solução 100% gratuita
cobre busca pública em TikTok/IG hoje** — o padrão de mercado (Kalodata etc.) é usar
coleta própria + modelos de estimativa, exatamente o que o motor demo simula aqui,
com rótulo transparente. Ao plugar as chaves oficiais, os dados reais passam a ter
prioridade e são mesclados automaticamente.

---

## 🧠 Arquitetura

```
server/
  main.py              # FastAPI + rotas (/api/*), tenant/billing e frontend
  research.py          # DATA LAYER: busca unificada, fan-out de fontes, outliers
  schema.py            # Esquema unificado das entidades + merge/dedupe entre fontes
  metrics.py           # viral_score, outlier_score, velocity, GMV em faixa, trend
  credits.py           # Planos, créditos, cotas, ledger e chaves de API (multi-tenant)
  agents.py            # Research Agents: CRUD, execução, agendador e entrega externa
  providers.py         # Conectores OFICIAIS: YouTube, TikTok Research, Instagram Graph
  scrapling_sources.py # Camada COLETA: Scrapling (YouTube/TikTok/IG + Google Trends)
  free_sources.py      # Grátis sem chave: Mercado Livre, Reddit, Suggest, oEmbed, Pexels
  pipeline.py          # Fábrica de Vídeos (jobs n8n/RunPod) + mineração/ingestão
  data.py              # Motor demo determinístico (vídeos, produtos, lojas, lives)
  ai_engine.py         # Estúdio IA: motor interno de copy + adaptadores Groq/Gemini/OpenAI
  storage.py           # Persistência JSON (biblioteca + configurações/chaves)
  tests_scrapling.py   # Testes offline dos parsers de coleta (fixtures locais)
  tests_unified.py     # Testes offline da camada unificada (métricas/schema/créditos/agentes)
static/                # SPA em JS puro (sem build)
n8n/                   # Workflows n8n importáveis (Fábrica + Mineração)
docs/AUTOMACAO.md      # Guia RunPod + n8n ponta a ponta
data/                  # Arquivos persistidos em runtime (gitignored)
```

**Decisões-chave**

1. **Esquema de dados unificado**: todo vídeo — oficial, coleta ou demo — passa
   por `normalize_video()`, então o frontend não muda com a fonte dos dados.
2. **Viral score**: `0.50·velocidade + 0.35·engajamento + 0.15·recência` (0–100).
3. **Outlier score**: `views ÷ baseline do criador` em escala log (0–100), caindo
   para a mediana do nicho quando não há histórico — é o sinal preditivo do produto.
4. **GMV sempre em faixa**: `unidades × ticket` com intervalo de confiança
   (nunca um número único) — a leitura honesta que os dados públicos permitem.
5. **IA em camadas**: LLM externo se houver chave (Groq/Gemini/OpenAI-compatível);
   senão, frameworks de copywriting (curiosidade, prova social, PAS, AIDA) offline.
6. **Sem build de frontend**: HTML/CSS/JS puros servidos pelo próprio FastAPI —
   deploy em qualquer lugar com Python 3.11+.

## 📡 Endpoints principais

```
GET  /api/status                      # modo atual + conectividade dos providers
GET  /api/search?q=&platform=&period=&sort=&min_views=   # oficial → coleta → n8n → demo
GET  /api/outliers?q=&platform=&period=&min_score=       # vídeos furando a curva
GET  /api/shops?q=&category=&sort=   | GET /api/shops/{id}
GET  /api/agents  POST /api/agents  PATCH/DELETE /api/agents/{id}
POST /api/agents/{id}/run                                # executa (100 créditos)
GET  /api/me  GET /api/billing/usage  GET /api/billing/plans
POST /api/billing/plan  POST /api/billing/credits  POST/DELETE /api/billing/keys
POST /api/workspaces                                     # cadastro multi-tenant
GET  /api/mcp/manifest                                   # ferramentas p/ Claude/MCP
GET  /api/trends?limit=               # termos em alta (Google Trends BR, tempo real)
GET  /api/products?q=&category=&sort= | GET /api/products/{id}
GET  /api/creators  GET /api/lives  GET /api/niches
POST /api/ai/hooks | /api/ai/script | /api/ai/caption | /api/ai/titles
POST /api/ai/analyze | /api/ai/narration
GET/POST/DELETE /api/library
GET/POST /api/settings  ·  POST /api/settings/test/{youtube|tiktok|instagram|coleta}
```


---

## 🧪 Testes

```bash
.venv/bin/python -m server.tests_unified    # métricas, schema, créditos, agentes
.venv/bin/python -m server.tests_scrapling  # parsers da camada de coleta
```

Nenhum dos dois toca a rede: são a garantia de que a matemática do produto
(outlier, GMV, cobrança) e os parsers continuam corretos após qualquer mudança.

## 📚 Documentação

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — desenho da plataforma unificada,
  modelo de dados, cobrança em créditos e roadmap por fases.
- [`docs/AUTOMACAO.md`](docs/AUTOMACAO.md) — RunPod + n8n ponta a ponta.
- [`DEPLOY.md`](DEPLOY.md) — VPS Contabo (systemd + nginx).
