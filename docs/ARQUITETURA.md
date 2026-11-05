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
                     │  n8n → ComfyUI/RunPod → MP4 → Biblioteca │
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
API oficial  >  coleta pública (Scrapling)  >  n8n (mineração/ingestão)  >  demo
```

Responsabilidades:

- fan-out assíncrono das fontes (`collect_official`, `collect_public`);
- deduplicação via esquema unificado;
- enriquecimento com métricas;
- fallback transparente — uma fonte fora do ar nunca derruba a resposta.

Consumidores: endpoints REST, Research Agents, API pública e MCP. Nenhum deles
fala com `providers.py` ou `scrapling_sources.py` diretamente.

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
se a coleta trouxe a thumb e a API oficial não, a thumb sobrevive.

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
| `mining` | 10 | `ingest` | 0 (grátis) |

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
| Descoberta | 🔎 Radar Viral | busca + facetas |
| | 🚀 Outliers | sinal preditivo + baseline |
| | 🤖 Research Agents | pesquisa agendada |
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
| `data/jobs.json`, `data/mined*.json`, `data/ingested*.json` | fábrica e mineração |

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
| 6 | Estúdio IA + Voice Studio + Fábrica de Vídeos (n8n/RunPod) | ✅ herdado v1 |
| 7 | API pública versionada + servidor MCP + webhooks de alerta | 🟡 manifesto pronto |
| 8 | Stripe real, assentos/convites, SSO enterprise | ⬜ próximo |
| 9 | Postgres + Timescale, fila dedicada, multi-região | ⬜ próximo |

---

## 6. Riscos e decisões de honestidade

1. **Nenhum concorrente vê os números internos da plataforma.** Os dados são
   públicos + modelados. Por isso todo GMV sai em faixa e todo score vem com o
   critério explicado na resposta (`criterio` no `/api/outliers`).
2. **Scraping tem custo e risco jurídico.** A arquitetura prefere APIs oficiais,
   limita a coleta a uma requisição por busca, respeita timeout e desliga por
   configuração (`SCRAPLING_ENABLED=0`).
3. **Crédito é disjuntor, não só receita.** Sem cobrança por ação, um cliente em
   loop queima a cota da operação inteira — o `charge()` existe por isso.
