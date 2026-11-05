# Arquitetura — MineraAI v2 (escopo unificado)

> Como o MineraAI unifica Virlo, Kalodata, DarkLAB e ViralFindr em um produto só —
> e por que essa união é mais defensável do que a soma das quatro ferramentas.

---

## 1. O mapa mental

```
                     ┌──────────────────────────────────────────┐
                     │        DESCOBERTA  (data layer)          │
                     │  Radar Viral · Outliers · Commerce Intel │
                     └───────────────┬──────────────────────────┘
                                     │  sinal validado
                     ┌───────────────▼──────────────────────────┐
                     │        CRIAÇÃO  (studio layer)           │
                     │  Hooks · Roteiro · Narração · B-roll     │
                     └───────────────┬──────────────────────────┘
                                     │  ativo pronto
                     ┌───────────────▼──────────────────────────┐
                     │       PRODUÇÃO  (factory layer)          │
                     │  RunPod (ComfyUI) → MP4 → Biblioteca     │
                     └───────────────┬──────────────────────────┘
                                     │  resultado realimenta
                                     └──────────► dados (loop fechado)
```

Cada concorrente para em uma caixa:

| Ferramenta | Para onde vai | O que não faz |
|---|---|---|
| Virlo | descobre o outlier e entrega o dossiê | não valida commerce, não produz |
| Kalodata | mostra GMV estimado de produto/loja/criador | não cria conteúdo |
| DarkLAB | produz canal dark (roteiro, voz, cenas) | não tem dado de commerce cross-platform |
| ViralFindr | busca rasa + download | não analisa, não produz, não cobra por uso real |

O MineraAI cobre as quatro caixas **e** conecta uma na outra: o mesmo dado que
descobre o outlier alimenta o roteiro, que alimenta a fábrica de vídeo, cujo
resultado volta para a base de dados.

---

## 2. Camadas de código

### 2.1 Data layer — `server/research.py`

Ponto único de entrada para qualquer pesquisa. Ordem de confiança:

```
API oficial  >  Virlo API  >  mineração própria (Orbit/Comet)  >  demo
```

Responsabilidades:

- fan-out assíncrono das fontes (`collect_official`, `collect_virlo`,
  `mined_for_query` em `mining.py`);
- deduplicação via esquema unificado;
- enriquecimento com métricas;
- fallback transparente — uma fonte fora do ar nunca derruba a resposta
  (erros agregados em `errors`, exibidos na UI como "⚠ fontes com erro").

Consumidores: endpoints REST, Research Agents, API pública e MCP. Nenhum deles
fala com `providers.py`, `virlo.py` ou `mining.py` diretamente. A troca de fonte é
uma decisão de `research.py`, não do consumidor.

**Isolamento de origem:** `search_videos(..., source=...)` aceita `oficial`,
`virlo`, `mineracao` ou `demo`. Em `all` vale a ordem de confiança acima; isolando
uma camada o demo não entra como reserva — a lista volta vazia com o motivo em
`errors`. É o que permite responder "este número é real?" sem ambiguidade.
As facetas (hashtags, sons, criadores) são calculadas **dos vídeos devolvidos**,
não do gerador demo — antes elas podiam descrever um conjunto que não era o exibido.

**Por que existe a camada:** cada fonte tem custo e formato próprios — YouTube Data
é grátis e cota limitada, a Virlo é paga por chamada (US$ 0,50) e a mineração
própria custa CPU do servidor. Concentrar a escolha num único módulo permite
ligar/desligar fonte por configuração (`VIRLO_AUTO_USE`) sem tocar em rota nenhuma.

### 2.1.1 Integrações — `server/free_sources.py`, `virlo.py`, `runpod.py`

Cada integração é um módulo independente, com `configured()` próprio, teste
individual (`POST /api/settings/test/{id}`) e tratamento de erro próprio:

| Módulo | Integração | Auth | Falha isolada |
|---|---|---|---|
| `providers.py` | YouTube · TikTok · Instagram | API key / OAuth | cai para a próxima camada |
| `virlo.py` | Virlo (Orbit/Comet/Satellite) | `Bearer virlo_tkn_*` | `VirloError` com status |
| `free_sources.py` | Reddit · Mercado Livre · Suggest · oEmbed · Trends · Pexels | OAuth/client credentials/chave própria | mensagem por fonte |
| `runpod.py` | RunPod serverless | `Bearer` + endpoint id | `RunPodError` com status |

`GET /api/integrations` devolve o inventário — id, grupo, campos aceitos,
`conectado` e custo — e é o que a tela **APIs & Conexões** usa para montar um card
por serviço. Não há campo compartilhado entre fontes: derrubar a cota do Reddit
não afeta o Pexels.

Chaves marcadas como secretas em `storage.SECRET_KEYS` são mascaradas na leitura e
nunca devolvidas em claro (a máscara é aplicada no ponto único `is_secret()`).

### 2.2 Esquema — `server/schema.py`

Cinco entidades, um `uid` estável por entidade:

| Entidade | `uid` | Campos-chave |
|---|---|---|
| `video` | `vid:<plataforma>:<id nativo>` | views, likes, comments, shares, age_hours, sound, hashtags |
| `creator` | `cr:<plataforma>:<id>` | followers, engagement_rate, gmv_est, niche |
| `product` | `prod:<plataforma>:<id>` | price, units, gmv (+faixa), curve, commission |
| `shop` | `shop:<plataforma>:<id>` | products, gmv, creators_affiliated, live_share |
| `live` | `live:<plataforma>:<id>` | viewers_peak, gmv, live_now |

`merge()` resolve conflito por ranking de fonte **sem perder campo preenchido** —
se a Virlo trouxe a thumb e a API oficial não, a thumb sobrevive.

### 2.3 Métricas — `server/metrics.py`

Toda a matemática do produto, testável sem rede:

| Métrica | Fórmula | Por que existe |
|---|---|---|
| `viral_score` | `0.50·velocidade + 0.35·engajamento + 0.15·frescor` | "o que está quente agora" |
| `outlier_score` | `log10(views ÷ baseline) · 46 + 14`, 0–100 | **sinal preditivo**: fura a curva antes do pico |
| `velocity` | `views ÷ horas desde a publicação` | separa viral de acumulado |
| `gmv_estimate` | `unidades × ticket` com faixa de confiança | honestidade estatística |
| `trend_score` | `0.6·crescimento + 0.4·aceleração recente` | força de uma curva |
| `momentum` | acelerando / subindo / estável / desacelerando | leitura em uma palavra |

**Baseline do outlier** — decisão central:

1. criador com ≥3 vídeos no corpus → mediana do próprio criador, confiança alta;
2. caso contrário → mediana do corpus pesquisado (o "normal" do nicho), confiança estimada;
3. piso de 2 500 views evita explosão em criador minúsculo.

Nunca usamos o próprio vídeo como baseline: isso faria todo vídeo ser outlier.

### 2.4 Billing — `server/credits.py`

```
tenant ──< api_keys
  │
  ├── plano (créditos/mês, cota diária, assentos)
  ├── créditos usados no ciclo + bônus (top-up)
  └── ledger de consumo (auditável)
```

Planos: `free` (600 cr) · `starter` R$49 (2 000) · `pro` R$199 (12 000) ·
`enterprise` (40 000).

Custo por ação (extrato da verdade em `credits.ACTIONS`):

| Ação | Créditos | Ação | Créditos |
|---|---|---|---|
| `search` | 2 | `ai_script` | 20 |
| `outliers` | 3 | `ai_analyze` | 15 |
| `products` | 2 | `ai_narration` | 30 |
| `agent_run` | 100 | `fabrica_job` | 250 |
| `mining_orbit` | 10 | `mining_comet` | 10 |
| `virlo_read` | 1 | `virlo_orbit` | 60 |
| `virlo_satellite` | 60 | `virlo_comet` | 60 |
| `ingest` | 0 (grátis) | `runpod_health` | 0 (grátis) |

Erros devolvidos: **402** (`quota_exceeded`, com `credits_needed` e
`credits_remaining`) e **429** (`rate_limited`, com `daily_limit`). A UI mostra a
mensagem pronta; a API pública devolve o detail estruturado.

### 2.5 Research Agents — `server/agents.py`

Um agente guarda: query, plataforma, período, objetivo, frequência, canais de
entrega e histórico de dossiês (últimos 20).

Fluxo de uma execução:

```
search_videos → sort by outlier → top 8 outliers
             → facetas (hashtags, sons, criadores)
             → 5 hooks gerados pelo Estúdio IA
             → recomendações ("replicar formato X porque 12,5x acima do baseline")
             → entrega: webhook / Slack / Discord
```

Agendador: loop `asyncio` iniciado no `startup` (`AGENTS_INTERVAL`, padrão 60 s).
Sem Celery, sem Redis. Para escala, o `scheduler_tick()` é o único ponto a mover
para um worker.

### 2.6 Produto — `static/app.js`

SPA sem build. Módulos visíveis:

| Menu | Tela | Serve para |
|---|---|---|
| Descoberta | 🔎 Radar Viral | busca + facetas (seletor de origem) |
| | 🚀 Outliers | sinal preditivo + baseline |
| | 🤖 Research Agents | pesquisa agendada |
| | ⛏️ Mineração | Orbits (fila) e Comets (monitor) |
| | 📦 Produtos · 🏪 Lojas · 👤 Criadores · 🔴 Lives · 🧭 Nichos | commerce intel |
| Criação | ✨ Estúdio IA · 🎬 Fábrica de Vídeos · 📁 Biblioteca | produção |
| Sistema | 💳 Uso & Plano · 🔌 APIs & Conexões | billing e chaves |

O pill de créditos no menu lateral reflete `GET /api/me` em todas as telas e
fica vermelho acima de 85% de consumo.

---

## 3. Modelo de dados em disco

Tudo em JSON (runtime, `gitignore`d) — trocável por Postgres sem tocar nas regras:

| Arquivo | Conteúdo |
|---|---|
| `data/tenants.json` | workspaces, planos, créditos, chaves |
| `data/usage.json` | ledger de consumo (últimos 5 000 eventos) |
| `data/agents.json` | agentes + histórico de dossiês |
| `data/library.json` | biblioteca de mídia/conteúdo |
| `data/settings.json` | chaves de conectores |
| `data/jobs.json` | jobs da Fábrica (execução RunPod, custo, outputs) |
| `data/orbits.json` · `data/comets.json` | mineração: buscas e monitores com série temporal |
| `data/ingested.json` | vídeos importados por API (dedupe por `uid`) |

Migração para Postgres: as funções de `credits.py`, `agents.py` e `storage.py`
concentram todo acesso a disco — é a única camada a reescrever.

---

## 4. Segurança e isolamento

- Chave de API resolvida por header `X-API-Key` ou `Authorization: Bearer`;
  sem chave, cai no workspace `demo` (plano free), o que mantém a plataforma
  explorável sem cadastro.
- Chaves armazenadas no servidor e expostas **mascaradas** (`mka_abcd••••wxyz`);
  a chave completa aparece uma única vez, na criação.
- Todos os recursos (agentes, créditos, biblioteca por workspace) são filtrados
  por `tenant_id` — testado em `server/tests_unified.py`.
- `secrets.compare_digest` na comparação de chaves.

---

## 5. Roadmap por fases

| Fase | Entrega | Estado |
|---|---|---|
| 0 | esquema unificado + normalizer + normalização idempotente | ✅ feito |
| 1 | Radar Viral com fan-out de fontes e métricas centralizadas | ✅ feito |
| 2 | multi-tenant + créditos + cotas + chaves + ledger | ✅ feito |
| 3 | Commerce Intel: produtos, lojas, criadores, lives com GMV em faixa | ✅ feito |
| 4 | Outlier detection com baseline de criador | ✅ feito |
| 5 | Research Agents + agendador + entrega externa | ✅ feito |
| 6 | Estúdio IA + Voice Studio + Fábrica de Vídeos (RunPod direto) | ✅ v3 |
| 6b | OAuth real de Reddit/Mercado Livre + 1 credencial por fonte | ✅ v3 |
| 6c | Mineração própria (Orbit/Comet) + Virlo API como fonte | ✅ v3 |
| 7 | API pública versionada + servidor MCP + webhooks de alerta | 🟡 manifesto pronto |
| 8 | Stripe real, assentos/convites, SSO enterprise | ⬜ próximo |
| 9 | Postgres + Timescale, fila dedicada, multi-região | ⬜ próximo |

---

## 6. Riscos e decisões de honestidade

1. **Nenhum concorrente vê os números internos da plataforma.** Os dados são
   públicos + modelados. Por isso todo GMV sai em faixa e todo score vem com o
   critério explicado na resposta (`criterio` no `/api/outliers`).
2. **Coleta tem custo e risco jurídico.** A arquitetura usa apenas APIs oficiais
   (YouTube/TikTok/Instagram), OAuth (Reddit/Mercado Livre) e fontes de chave
   própria — nada de scraping de página, nada de fingerprint de navegador. Onde a
   cobertura oficial não existe (TikTok/IG sem aprovação), a escolha é explícita:
   ou a **Virlo API** paga por chamada, ou o dado sai rotulado como `demo`.
3. **Crédito é disjuntor, não só receita.** Sem cobrança por ação, um cliente em
   loop queima a cota da operação inteira — o `charge()` existe por isso.
