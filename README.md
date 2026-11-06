# ⛏️ MineraAI — Ecossistema Unificado de Descoberta Viral, Commerce & Criação

[![CI](https://github.com/agenciaohrion/mineraai/actions/workflows/ci.yml/badge.svg)](https://github.com/agenciaohrion/mineraai/actions/workflows/ci.yml)

**v3 — integrações diretas.** Um único produto que cobre o que quatro ferramentas de
mercado fazem separadamente, com o loop fechado que nenhuma delas tem:
*descobrir → validar o produto → gerar o roteiro → produzir o vídeo → medir o resultado.*

| Referência de mercado | O que o MineraAI implementa |
|---|---|
| **Virlo** (short-form video intelligence) | 🚀 **Outliers** (vídeos furando a curva do próprio criador) + 🤖 **Research Agents** (pesquisa agendada com dossiê entregue no Slack/Discord/webhook) + ⛏️ **Mineração** (Orbit/Comet: o modelo deles, rodando com as nossas fontes) + 📡 **API pública** e **MCP** + integração opcional da **Virlo API** como fonte paga |
| **ViralFindr** (pesquisa de conteúdo viral) | 🔎 **Radar Viral**: busca por palavra-chave em TikTok, Instagram e YouTube com viral score, filtros (período, ordenação, views mínimas), hashtags dominantes, sons em alta e criadores do tema |
| **Kalodata** (analytics de TikTok Shop) | 📦 **Produtos** com GMV **em faixa de confiança**, unidades, crescimento, curva 14 dias, comissões + 🏪 **Lojas** (catálogo, criadores afiliados, dependência de live) + 👤 **Criadores** + 🔴 **Vídeos & Lives** (live commerce) |
| **DarkLab AI** (laboratório para canais dark) | ✨ **Estúdio IA**: hooks virais, roteiros UGC/dark cena a cena, legendas + hashtags, títulos SEO YouTube, 🧪 **Viral Lab** (engenharia reversa com metadados reais via oEmbed), 🎙️ **Voice Studio** e 🧭 **Radar de Nichos** |
| — (produção em escala) | 🎬 **Fábrica de Vídeos**: o MineraAI chama a API do **RunPod serverless direto** (`/runsync` ou `/run`) com o workflow do ComfyUI — **sem n8n no meio**, sem webhook, sem callback |

### 💳 Camada SaaS (o que faltava para ser produto, não demo)

| Recurso | Como funciona |
|---|---|
| **Multi-tenant** | cada workspace tem plano, créditos, chaves de API e agentes isolados (`POST /api/workspaces` cria um na hora) |
| **Créditos** | toda ação que gasta rede/IA/GPU é cobrada (busca = 2, agent run = 100, vídeo = 250, Orbit = 10, chamada paga da Virlo = 60) — mesmo modelo de Virlo e Kalodata |
| **Cotas** | limite diário + teto mensal por plano (free → enterprise), com **HTTP 402/429** explicando exatamente quanto falta |
| **Ledger** | cada consumo é registrado; `/api/billing/usage` mostra por ação e por dia |
| **API keys** | `X-API-Key` (ou Bearer) por workspace, com revogação e último uso |
| **Planos** | free · starter (R$49) · pro (R$199) · enterprise, com upgrade simulado pronto para plugar Stripe |

### 🔌 Uma integração por card, uma credencial por fonte

A tela **APIs & Conexões** deixou de ser um bloco único. Cada serviço tem o seu card
com os seus campos, o seu teste e o seu custo — se uma fonte cai, as outras seguem:

| Grupo | Integrações | Campos próprios |
|---|---|---|
| **Plataformas oficiais** | YouTube Data API v3 · TikTok Research API · Instagram Graph API | `YOUTUBE_API_KEY` · `TIKTOK_CLIENT_*` · `IG_ACCESS_TOKEN`+`IG_USER_ID` |
| **Dados pagos** | **Virlo API** (Orbit · Comet · Satellite) | `VIRLO_API_KEY` · `VIRLO_AUTO_USE` · `VIRLO_BASE_URL` |
| **IA** | **OpenAI** e **Gemini** — chaves independentes | `OPENAI_API_KEY`/`MODEL`/`BASE_URL` · `GEMINI_API_KEY`/`MODEL` |
| **Fontes gratuitas** | **Reddit (OAuth)** · **Mercado Livre (OAuth)** · **Google Suggest** · **oEmbed** · **Google Trends** · **Pexels** | um campo por fonte (ver `.env.example`) |
| **Produção** | **RunPod Serverless** direto | `RUNPOD_API_KEY` · `RUNPOD_ENDPOINT_ID` · `RUNPOD_GPU_PRICE_HORA` · template do workflow |
| **Publicação** | **YouTube (OAuth do canal)** — upload + medição | `YOUTUBE_CLIENT_ID/SECRET/REDIRECT_URI` · `PUBLISH_JANELA_DIAS` |

Sem nenhuma chave a plataforma roda em **modo demonstração** (motor determinístico com
distribuição power-law de views, engajamento derivado, curvas de venda) e cada item
exibe o selo da origem: `oficial` · `virlo` · `mineração` · `demo`.

### 🔐 OAuth de verdade, não "campo opcional"

- **Reddit** — `POST /api/integrations/reddit/token` faz `client_credentials` com
  Basic auth e guarda o token (100 req/min em vez de 10 no endpoint público).
  Sem credencial, cai no JSON público automaticamente.
- **Mercado Livre** — fluxo `authorization_code` completo:
  `GET /api/integrations/meli/authorize` → usuário autoriza → **o próprio Mercado Livre
  devolve o navegador** em `GET /api/integrations/meli/callback?code=…`, que troca o
  `code` por `access_token` + `refresh_token` e mostra uma página de retorno ao app.
  Se o redirect apontar para outro domínio, o `code` pode ser colado no diálogo
  (`POST` na mesma rota). `POST /api/integrations/meli/refresh` renova — e o
  `meli_access_token()` renova sozinho quando faltam 5 minutos.

O Radar tem **seletor de origem** (`Todas · Só oficial · Só Virlo · Só mineração ·
Só demonstração`). Isolar uma camada serve para auditar e para quem paga por cobertura
real: em `só oficial`, o demo **não entra como reserva** — a resposta volta vazia com
explicação, em vez de número estimado disfarçado de oficial. API equivalente:
`?source=oficial` e `?include_demo=false`.

### 📡 Fontes de dados em 4 camadas (cada item é rotulado)

| Selo | Fonte | Quando |
|---|---|---|
| 🟢 `oficial` | APIs oficiais (YouTube Data v3, TikTok Research, IG Graph, Mercado Livre) | chaves configuradas |
| 🟣 `virlo` | **Virlo API** — índice pronto de short-form (Orbit/Satellite) | `VIRLO_API_KEY` (+ `VIRLO_AUTO_USE` no Radar) |
| 🟡 `mineração` | Orbits e Comets do próprio MineraAI (`server/mining.py`) | quando você minera |
| ⚪ `demo` | Motor determinístico de demonstração | fallback sempre disponível |

> Design, código e textos 100% originais — as plataformas acima foram usadas apenas
> como referência de *funcionalidades*. Nada de Scrapling, nada de n8n, nada de Groq.

---

## 🚀 Rodando

```bash
./run.sh          # cria o venv, instala dependências e sobe em http://0.0.0.0:8000
```

Depois abra **APIs & Conexões** no app e preencha só o que você tem — o card fica
verde ("conectado") assim que o teste passa.

---

## 🎬 Fábrica de vídeo: RunPod direto (sem n8n)

```
MineraAI ──POST /v2/{endpoint}/runsync──▶ worker ComfyUI no RunPod
        ◀──── {"status":"COMPLETED","output":{"message":"<url do mp4>"}}
```

- **O arquivo fica com a gente.** Ao concluir, o MP4 é baixado para
  `data/media/<workspace>/` e servido por `GET /api/fabrica/jobs/{id}/file` —
  porque a URL que o RunPod devolve é do S3 deles e **expira**. Se o download
  falhar, o job continua `pronto` com a URL original e o motivo em `media_error`.
- **`mode: "sync"`** → `runsync`, espera o vídeo (limite de 20 MB de payload).
- **`mode: "async"`** → `run` + `GET /status/{id}` com polling
  (`GET /api/fabrica/jobs/{id}/poll`), cancelamento via `/cancel`.
- O workflow do ComfyUI vem de `RUNPOD_WORKFLOW_TEMPLATE` (formato API, "Save → API
  Format") ou do grafo SDXL padrão em `server/runpod.py`; o prompt é injetado nos nós
  `CLIPTextEncode`, o seed é randomizado e o custo é estimado por `executionTime × preço da GPU`.
- Guia completo: [`docs/AUTOMACAO.md`](docs/AUTOMACAO.md).

## 📤 Publicação — o loop fecha aqui

O ciclo parava em "produzir". Agora o vídeo sai da Fábrica direto para o canal:

```
Fábrica (job pronto) → 📤 Publicar (OAuth do canal, unlisted por padrão)
                    → YouTube (videos.insert, ~1.600 un. de cota)
                    → medição a cada 6h por 7 dias (views/likes/comentários)
                    → corpus da mineração com source "publicado"
                    → o baseline de outlier passa a incluir o que a gente publicou
```

O último passo é o que importa: `mining.ingest_videos(..., "publicado", substituir=True)`
faz o vídeo realimentar o mesmo `outlier_score` que usamos para descobrir tendências.
Guia completo (app OAuth no Google Cloud, cota, estados de falha, o que não é feito):
[`docs/PUBLICACAO.md`](docs/PUBLICACAO.md).

## ⛏️ Mineração: como o Virlo faz, como fazemos

O Virlo não tem API oficial das redes — ele mantém **fila de coleta (Orbit)** +
**monitor agendado (Comet)** + detecção de outlier por baseline de criador. A doc
pública deles revela o desenho (`POST /orbit` devolve um `id` e leva 5–10 min;
leitura é grátis, criação custa US$ 0,50). Reproduzimos o desenho com fontes
legítimas — desta vez, sem depender de n8n:

```
keywords → job persistido (queued) → worker coleta (YouTube oficial + Virlo + ingestão)
        → normalize → dedupe → métricas (viral + outlier) → data/orbits.json
Comet  → mesmo pipeline a cada ciclo → série temporal (videos, outliers, mediana)
```

Documento completo, com as etapas uma por uma e o trade-off
"mineração própria × Virlo API": [`docs/MINERACAO.md`](docs/MINERACAO.md).

---

## 🧠 Arquitetura

```
server/
  main.py          # FastAPI + rotas (/api/*), tenant/billing e frontend
  research.py      # DATA LAYER: fan-out oficial → Virlo → mineração → demo, outliers
  schema.py        # Esquema unificado das entidades + merge/dedupe entre fontes
  metrics.py       # viral_score, outlier_score, velocity, GMV em faixa, trend
  credits.py       # Planos, créditos, cotas, ledger e chaves de API (multi-tenant)
  agents.py        # Research Agents: CRUD, execução, agendador e entrega externa
  providers.py     # Conectores OFICIAIS: YouTube, TikTok Research, Instagram Graph
  free_sources.py  # Reddit (OAuth) · Mercado Livre (OAuth) · Suggest · oEmbed · Trends · Pexels
  virlo.py         # Cliente da Virlo API: Orbit · Comet · Satellite · trends · hashtags
  runpod.py        # Cliente DIRETO do RunPod: submit, status, poll, cancel, custo
  mining.py        # Orbits/Comets: fila de coleta, agendador, série temporal
  pipeline.py      # Fábrica de Vídeos: jobs, dispatch ao RunPod, polling e mídia
  data.py          # Motor demo determinístico (vídeos, produtos, lojas, lives)
  ai_engine.py     # Estúdio IA: motor interno + adaptadores OpenAI e Gemini
  storage.py       # Persistência JSON (biblioteca + configurações/chaves)
  youtube.py       # OAuth do canal, upload resumable e métricas dos vídeos
  publications.py  # Publicação + série temporal + realimentação do corpus
  media.py         # Mídia local: download do worker, sniff de formato, órfãos
  retention.py     # Retenção: janela em dias, tetos e varredura de mídia
  tests_unified.py      # Testes offline: métricas, schema, créditos, agentes
  tests_integracoes.py  # Testes offline: RunPod, Virlo, mineração e as 6 fontes
  tests_media.py        # Testes offline: mídia local + retenção
  tests_publicacao.py   # Testes offline: OAuth, upload, medição, corpus
static/            # SPA em JS puro (sem build)
docs/              # ARQUITETURA · AUTOMACAO (RunPod) · MINERACAO
data/              # Arquivos persistidos em runtime (gitignored)
```

**Decisões-chave**

1. **Esquema de dados unificado**: todo vídeo — oficial, Virlo, mineração ou demo —
   passa por `normalize_video()`; o frontend não muda com a fonte.
2. **Viral score**: `0.50·velocidade + 0.35·engajamento + 0.15·recência` (0–100).
3. **Outlier score**: `views ÷ baseline do criador` em escala log (0–100), caindo
   para a mediana do corpus quando não há histórico — o sinal preditivo do produto.
4. **GMV sempre em faixa**: `unidades × ticket` com intervalo de confiança.
5. **IA em camadas**: OpenAI ou Gemini (chaves separadas) se houver; senão o motor
   interno de copywriting (PAS, AIDA, prova social) offline.
6. **Integração direta**: nenhum orquestrador externo entre o produto e as APIs.
   Menos salto, menos ponto de falha, menos latência e um log a menos para auditar.
7. **Sem build de frontend**: HTML/CSS/JS puros servidos pelo próprio FastAPI.

## 📡 Endpoints principais

```
# descoberta
GET  /api/status                                  # modo + conectividade por integração
GET  /api/search?q=&platform=&period=&sort=&min_views=   # oficial → virlo → mineração → demo
                 &source=all|oficial|virlo|mineracao|demo &include_demo=false
GET  /api/outliers?q=&platform=&period=&min_score=
GET  /api/trends?limit=                           # Google Trends BR em tempo real

# commerce intel
GET  /api/shops | /api/shops/{id} | /api/products | /api/products/{id}
GET  /api/creators | /api/lives | /api/niches

# criação
POST /api/ai/hooks | /script | /caption | /titles | /analyze | /narration
GET/POST/DELETE /api/library

# fábrica de vídeo (RunPod direto)
POST /api/fabrica/jobs                            # {product, prompt, images[], mode: sync|async}
GET  /api/fabrica/jobs | /api/fabrica/jobs/{id}
GET  /api/fabrica/jobs/{id}/poll | /cancel
GET  /api/fabrica/jobs/{id}/file[?download=true]  # arquivo local (não expira)

# publicação (YouTube)
GET  /api/integrations/youtube/authorize
GET  /api/integrations/youtube/callback           # retorno do Google (o navegador volta aqui)
POST /api/integrations/youtube/refresh
GET  /api/integrations/youtube/canal
POST /api/fabrica/jobs/{id}/publicar              # titulo, descricao, tags, privacidade
GET  /api/publicacoes | /api/publicacoes/{id}
POST /api/publicacoes/sync | /api/publicacoes/{id}/sync
DELETE /api/publicacoes/{id}                      # remove só o registro local

# manutenção / retenção
GET  /api/maintenance/status                      # config, uso de disco, última poda
POST /api/maintenance/run                         # roda a poda agora
GET  /api/runpod/health | /api/runpod/workflow

# virlo api
GET  /api/virlo/balance | /trends | /hashtags | /orbit | /orbit/{id}
POST /api/virlo/orbit | /api/virlo/satellite/{platform}/{username}

# mineração (orbit/comet)
GET/POST/DELETE /api/mining/orbits | /api/mining/orbits/{id}
GET/POST/DELETE /api/mining/comets | POST /api/mining/comets/{id}/run
GET  /api/mining/como-funciona
POST /api/ingest/videos                           # entrada de dados por workspace

# agentes, billing, integrações
GET/POST /api/agents · POST /api/agents/{id}/run
GET  /api/me | /api/billing/usage | /api/billing/plans
POST /api/billing/plan | /credits | /keys
GET  /api/integrations                            # inventário: campos por fonte
GET  /api/integrations/meli/authorize
GET  /api/integrations/meli/callback              # retorno do OAuth (o navegador volta aqui)
POST /api/integrations/reddit/token | /meli/callback | /meli/refresh
GET/POST /api/settings
POST /api/settings/test/{youtube|tiktok|instagram|openai|gemini|virlo|reddit|
                         mercadolivre|suggest|oembed|trends|pexels|runpod}
GET  /api/mcp/manifest
```

---

## 🗄️ Retenção — nada em disco cresce sem teto

JSON em disco não é log infinito. A poda roda no boot e a cada
`RETENTION_INTERVALO_H` (padrão 6h), com três regras:

1. os itens mais recentes sempre ficam;
2. fora isso, vale a janela (`RETENTION_DIAS`, padrão 90);
3. item sem data **nunca** é apagado — não dá para provar que está velho.

Podados: `jobs`, `usage`, `orbits`, `ingested`. **Não** podados, de propósito:
`comets` (configuração de monitor do usuário), `library` (curadoria), `agents` e
`tenants`. A varredura de mídia remove só arquivo **órfão** com mais de 24h — se o
vídeo está referenciado por um job ou pela Biblioteca, fica.

```bash
curl localhost:8000/api/maintenance/status   # config, MB em disco, última poda
curl -X POST localhost:8000/api/maintenance/run
```

## 🧪 Testes

```bash
.venv/bin/python -m server.tests_unified      # métricas, schema, créditos, agentes
.venv/bin/python -m server.tests_integracoes  # RunPod, Virlo, mineração e as 6 fontes
.venv/bin/python -m server.tests_media        # mídia local + retenção
.venv/bin/python -m server.tests_publicacao   # OAuth, upload, medição e realimentação
```

Nenhum toca a rede: `httpx` é substituído por dublês, então dá para validar
contrato (URL, auth, payload, tratamento de 401/404) sem gastar cota nem arriscar
banimento. São a garantia de que a matemática do produto e as integrações
continuam corretas depois de qualquer mudança.

Os dois rodam no **GitHub Actions** a cada push ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)),
junto com `node --check static/app.js` e uma checagem de que as rotas obrigatórias
continuam registradas — refatoração que apaga endpoint quebra o build.

## 📚 Documentação

- [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md) — desenho da plataforma, modelo de
  dados, cobrança em créditos e roadmap por fases.
- [`docs/AUTOMACAO.md`](docs/AUTOMACAO.md) — RunPod serverless + ComfyUI ponta a ponta.
- [`docs/MINERACAO.md`](docs/MINERACAO.md) — como o Virlo minera e como replicamos.
- [`DEPLOY.md`](DEPLOY.md) — VPS Contabo (systemd + nginx).
