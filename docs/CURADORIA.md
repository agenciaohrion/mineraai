# ✅ Curadoria Inteligente + Fábrica ComfyUI — MineraAI

Sistema completo de curadoria para transformar garimpo bruto em conteúdo pronto para publicar, com **geração automática de imagens, vídeos e kits mistos via ComfyUI no RunPod Serverless**.

## Novo: Fábrica ComfyUI (imagem | vídeo | misto)

Desde 2026-05, a Fábrica evoluiu de apenas vídeo para **3 tipos**:

| Tipo | n8n webhook | ComfyUI workflow | Output MineraAI |
|---|---|---|---|
| `imagem` | `mineraai-imagem-job` | `workflow-imagem-sdxl.json` (SDXL 768x1344) ou `workflow-imagem-produto.json` (batch 3) | `images[]` (1-4 imagens) |
| `video` | `mineraai-video-job` | `workflow-video-animatediff.json` (512x768 16f) ou `workflow-video-ltx.json` (576x1024 121f) | `video_url` + `images[]` thumb |
| `misto` | `mineraai-misto-job` | `workflow-misto-ugc.json` (3 imgs+vídeo) ou `workflow-misto-curadoria.json` (capa+3+vídeo) | `video_url` + `images[]` 4 imagens |

**Router**: `fabrica-router-comfyui-runpod.json` webhook `mineraai-fabrica-job` recebe qualquer `tipo` e roteia para fábrica correta. Configure `N8N_WEBHOOK_URL` para apontar para ele.

### Payload padrão MineraAI → n8n

```json
{
  "job_id": "job-abc123",
  "tipo": "misto",
  "product": "garrafa térmica premium",
  "prompt": "garrafa térmica na mesa, luz natural, UGC",
  "style": "ugc",
  "duration": 6,
  "roteiro": {
    "hook": "Pare de comprar garrafas que não gelam!",
    "cenas": [
      {"nome":"CAPA","descricao":"thumb scroll-stopper","prompt":"premium bottle with ice, bold text, studio light, 9:16","duracao":1},
      {"nome":"GANCHO","descricao":"close gelo caindo","prompt":"close-up ice cubes falling into black bottle, slow motion","duracao":2},
      {"nome":"DEMO","descricao":"prova 24h gelado","prompt":"woman holding cold bottle after 24h, condensation, lifestyle kitchen, UGC","duracao":3},
      {"nome":"CTA","descricao":"oferta","prompt":"bottle on table with price tag R$ 79,90, buy now overlay, cozy home","duracao":2}
    ],
    "narracao": "Essa garrafa mantém gelo 24h de verdade..."
  },
  "prompts": ["prompt extra 1", "prompt extra 2"],
  "callback_url": "https://seu-mineraai/api/fabrica/jobs/job-abc123/result",
  "token": "seu-token"
}
```

n8n injeta no workflow ComfyUI API (CLIPTextEncode) com `STYLE_PREFIX` por estilo:

- `ugc`: "amateur photo, natural light, iPhone, real house, authentic, "
- `produto`: "product photography, studio lighting, white background, 8k, "
- `dark`: "dark aesthetic, moody lighting, cinematic, mysterious, "
- `cinematic`: "cinematic lighting, 8k, ultra detailed, professional, "
- `anime`: "anime style, studio ghibli, vibrant colors, "

E chama RunPod `/run` → polling `/status` → extrai URLs → callback MineraAI com:

```json
{
  "status": "pronto",
  "video_url": "https://r2.../video.mp4",
  "images": [
    {"url":"https://r2.../capa.png","prompt":"...","cena":"CAPA"},
    {"url":"https://r2.../gancho.png","prompt":"...","cena":"GANCHO"},
    {"url":"https://r2.../demo.png","prompt":"...","cena":"DEMO"},
    {"url":"https://r2.../cta.png","prompt":"...","cena":"CTA"}
  ],
  "cost_usd": 0.045
}
```

Frontend `Fábrica ComfyUI` já exibe galeria de imagens + player de vídeo.

### Workflows ComfyUI (API Format) em `comfyui/workflows/`

- `workflow-imagem-sdxl.json`: SDXL base 768x1344 vertical, prompt injetável
- `workflow-imagem-produto.json`: realisticVisionV60 batch 3 UGC produto
- `workflow-video-animatediff.json`: AnimateDiff mm_sd_v15_v2 512x768 16f + VHS_VideoCombine mp4
- `workflow-video-ltx.json`: LTX-Video 2B 576x1024 121f 24fps
- `workflow-misto-ugc.json`: 3 KSamplers (GANCHO/DEMO/CTA) + 1 AnimateDiff vídeo, kit UGC
- `workflow-misto-curadoria.json`: capa thumb + hook/demo/CTA + vídeo 24f, recebe roteiro curado

Todos com `filename_prefix: mineraai/` e placeholders `PROMPT_*` para injeção n8n.

---

# ✅ Curadoria Inteligente — pipeline original (mantido abaixo)

Sistema completo de curadoria para transformar garimpo bruto em conteúdo pronto para publicar.

## Pipeline em 5 etapas

```
1. COLETA → Radar Viral, Mineração n8n, Ingestão livre, Manual (botão Curar)
       ↓
2. FILTRAGEM AUTOMÁTICA → regras + blacklist + score mod
       ↓
3. ENRIQUECIMENTO IA → hooks + Viral Lab + tags + título sugerido
       ↓
4. DECISÃO HUMANA → kanban: novo → em_analise → aprovado/rejeitado → arquivado/publicado
       ↓
5. AÇÃO → Biblioteca (auto) + Fábrica de Vídeos + Webhook externo (scheduler)
```

## Backend (server/curation.py)

### Storage
- `data/curation.json` → até 5000 itens, cada item:
```json
{
  "id": "cur-abc123",
  "status": "novo|em_analise|aprovado|rejeitado|arquivado|publicado",
  "video": { "id, title, platform, views, likes, viral_score, ...": "" },
  "query_origem": "garrafa térmica",
  "source": "radar|mineracao|ingestao|manual|auto|n8n",
  "curadoria": { "score_curadoria": 82, "score_original": 75, "reasons": [], "blocked": false, "auto_decision": null },
  "enriquecimento": { "hooks": [], "analise": {}, "tags_sugeridas": [] },
  "decisao": { "por": "humano", "em": "...", "notas": "", "historico": [] }
}
```
- `data/curation_rules.json` → regras editáveis via UI ou API

### Regras padrão
| Campo | Default | Efeito |
|---|---|---|
| `min_viral_score` | 35 | filtra abaixo |
| `min_views` | 1000 | filtra abaixo |
| `min_engagement` | 1.0% | alerta se abaixo |
| `max_age_hours` | 720 (30d) | penaliza -15 se muito antigo |
| `required_platform` | all | se tiktok/ig/yt, bloqueia outras |
| `blacklist_keywords` | ["golpe","aposta",...] | bloqueia e vai pra rejeitado |
| `whitelist_keywords` | [] | boost +10 score |
| `tags_prioritarias` | ["viral","achadinhos"...] | boost +8 |
| `auto_approve_score` | 85 | se ativo, ≥ vira aprovado |
| `auto_reject_score` | 15 | se ativo, ≤ vira rejeitado |
| `auto_approve_enabled` | false | liga/desliga auto decisão |

### Endpoints
```
GET  /api/curation/queue?status=&platform=&min_score=&q=&limit=&sort=
GET  /api/curation/outliers?min_score=75&limit=20
GET  /api/curation/stats
GET  /api/curation/rules
POST /api/curation/rules { rules: {...} }
POST /api/curation/items { videos: [...], query: "", source: "manual|radar|n8n|auto" }
POST /api/curation/auto-curate { query, platform, limit }  # garimpa e já cura
POST /api/curation/items/{id}/decision { decision, notas, por }
POST /api/curation/bulk-decision { ids: [], decision, notas }
POST /api/curation/items/{id}/enrich { hooks, analise, tags_sugeridas, ... }
POST /api/curation/items/{id}/auto-enrich  # usa IA interna (Groq/Gemini ou motor interno)
DELETE /api/curation/items/{id}
POST /api/curation/clear?status=rejeitado  # limpa por status ou tudo
```

## Frontend (SPA)

### Nova página: Curadoria ✅
- **KPIs**: total, outliers ≥75, aprovados, média score, novos 24h
- **Filtros**: busca texto, status, plataforma, min score, ordenação
- **Ações rápidas**:
  - `Garimpar e curar` → digita keyword → busca no Radar + aplica regras → fila
  - `Só outliers` → filtra ≥75
  - `Curar todos` no Radar Viral → envia todos resultados da busca atual para curadoria
- **Lista**: cards com checkbox multi-seleção, score ring, razões de bloqueio/boost, hooks IA se enriquecido
- **Bulk bar**: aparece ao selecionar ≥1 → Aprovar, Em análise, Rejeitar, Arquivar
- **Detalhes modal**: diagnóstico completo, hooks, análise Viral Lab, botão gerar vídeo na Fábrica
- **Regras modal**: edita todos thresholds, blacklist, whitelist, tags prioritárias, auto-aprovação

### Integrações existentes
- Radar Viral: botão `✅ Curar` em cada card + `✅ Curar todos`
- Dashboard: KPI de curadoria + lista por status
- APIs & Conexões: card de curadoria explicativo
- Biblioteca: aprovados vão auto para biblioteca

## Workflows n8n (pasta n8n/)

### 1. curadoria-automatica.json — `MineraAI · Curadoria Automática`
- **Trigger**: Schedule a cada 1 hora
- **Fluxo**:
  - Code: lista de keywords do nicho + regras
  - Loop: POST /api/curation/auto-curate para cada keyword (garimpa + filtra + fila)
  - Code: agrega resumo (criados, duplicados, bloqueados)
  - IF tem novos → GET /api/curation/outliers ≥75
  - Code: formata mensagem com top outliers
- **Env vars n8n**: `MINERAAI_URL`, `N8N_TOKEN` (opcional)
- **Como usar**: Importe, edite keywords no node `Keywords + Regras`, configure env, ative

### 2. curadoria-enriquecimento-ia.json — `Enriquecimento IA`
- **Trigger**: Webhook POST `/mineraai-curadoria-enrich`
- **Fluxo**:
  - Responde 202 imediatamente
  - Code: prepara prompts (hooks + lab) a partir do item
  - HTTP: POST /api/ai/hooks (MineraAI)
  - HTTP: POST /api/ai/analyze (MineraAI)
  - Code: mescla hooks + análise + tags
  - HTTP: POST /api/curation/items/{id}/enrich com token
- **Uso manual**: POST para webhook com `{ item_id, video: {...} }` ou configure MineraAI para chamar quando item entra em `em_analise`
- **Env vars**: `MINERAAI_URL`, `N8N_TOKEN`
- **Extensão**: Troque os nodes MineraAI por Groq/Gemini direto se quiser LLM externo puro no n8n

### 3. curadoria-publicacao.json — `Publicação`
- **Trigger**: Webhook POST `/mineraai-curadoria-aprovado`
- **Fluxo**:
  - Responde 202
  - Code: config (salvar_biblioteca true/false, gerar_video_fabrica true/false, webhook_externo URL)
  - IF salvar_biblioteca → POST /api/library
  - IF gerar_video_fabrica → POST /api/fabrica/jobs (prompt montado do enriquecimento)
  - IF webhook_externo preenchido → POST para scheduler (Metricool, Buffer, Make, etc) com `{ event, item_id, video, enriquecimento }`
  - Final: POST /api/curation/items/{id}/decision → publicado
- **Env vars**: `MINERAAI_URL`, `N8N_TOKEN`
- **Como usar**: Edite `config` no node `Config Publicação`, coloque URL do seu agendador, ative gerar vídeo se quiser produção automática

### 4. curadoria-alertas-outliers.json — `Alertas`
- **Trigger**: Schedule a cada 30 min
- **Fluxo**:
  - GET /api/curation/outliers?min_score=75&limit=10
  - IF count > 0 → Code: formata mensagens para Telegram/Slack/Discord
  - 3 nodes HTTP em paralelo: Telegram, Slack, Discord (cada um usa sua env var)
- **Env vars**: `MINERAAI_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SLACK_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL`
- **Nota**: Desative os nodes que não usar (ex: se só usa Telegram, desative Slack/Discord)

## Como implementar na prática

### Passo 1 — Rodar MineraAI
```bash
./run.sh  # sobe em :8000, curadoria já ativa sem config
```

### Passo 2 — Importar workflows n8n
1. `docker run -it -p 5678:5678 n8nio/n8n` ou n8n Cloud
2. Workflows → Import from File → selecione os 4 arquivos `curadoria-*.json`
3. Settings → Environment → adicione:
```
MINERAAI_URL=https://sua-url-mineraai.com
N8N_TOKEN=seu-token-seguro (mesmo de APIs & Conexões)
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
SLACK_WEBHOOK_URL=...
DISCORD_WEBHOOK_URL=...
```
4. No MineraAI, aba APIs & Conexões → preencha `N8N_TOKEN` e `MINERAAI_PUBLIC_URL`
5. Ative os workflows

### Passo 3 — Fluxo manual (sem n8n)
1. Radar Viral → garimpe "garrafa térmica" → `✅ Curar todos`
2. Vá em Curadoria → veja itens com score curadoria + razões
3. Clique `✨ Enriquecer IA` nos promissores
4. Aprove em lote → vão para Biblioteca
5. No detalhe, `🎬 Gerar vídeo` → Fábrica

### Passo 4 — Fluxo 100% automático (com n8n)
1. Ative `curadoria-automatica` → a cada 1h garimpa suas keywords e popula fila
2. Opcional: crie um workflow que escuta `novo` e chama `curadoria-enriquecimento-ia` webhook
3. Ative `curadoria-alertas-outliers` → te avisa no Telegram quando achar ≥75
4. Aprove manualmente ou ligue `auto_approve_enabled` nas regras (≥85)
5. Ative `curadoria-publicacao` e configure webhook externo → aprovados vão para agendador

## Boas práticas de curadoria

- **Blacklist agressiva no início**: bloqueie apostas, golpes, onlyfans, etc. Evita ruído.
- **Whitelist para seu nicho**: se vende "casa", whitelist ["organizador","cozinha","limpeza"] dá +10.
- **Score 75 é ouro**: no mercado, 75+ tem alta chance de replicação. Foque aí.
- **Enriqueça só outliers**: não gaste LLM em tudo, só em ≥70.
- **Biblioteca = banco de criativos**: aprovados viram biblioteca → base para treinar equipe ou fine-tune.
- **Fábrica + Curadoria**: curadoria acha formato, fábrica recria com seu produto.

## Roadmap sugerido

- [ ] Webhook automático: quando item entra em `novo` com score ≥75, dispara enriquecimento
- [ ] Integração Metricool/Buffer: publicar direto aprovados
- [ ] Export CSV da fila para planilha
- [ ] Treino de modelo próprio: usar aprovados/rejeitados como dataset para classificador local
- [ ] Kanban drag-and-drop visual (hoje é por botões, pode virar colunas arrastáveis)
