# 🤖 Automação — n8n + RunPod/ComfyUI + MineraAI

Guia para colocar o pipeline monumental em produção: vídeos gerados por IA
entregues dentro do MineraAI e mineração contínua alimentando o Radar Viral.

```
                        ┌────────────────────────────────────────────┐
 FÁBRICA DE VÍDEOS      │  n8n (self-host grátis ou Cloud)           │
 MineraAI ──webhook──▶  │  workflow: fabrica-videos-comfyui-runpod   │
    ▲                   │     │                                       │
    │ callback + MP4    │     ▼  POST {workflow}                      │
    └───────────────────┤  RunPod Serverless (ComfyUI) ──▶ GPU       │
                        │     │      paga por segundo (~centavos)     │
                        │     ▼                                       │
                        │  storage (R2/Supabase) ──▶ video_url        │
                        └────────────────────────────────────────────┘

 MINERAÇÃO CONTÍNUA
 n8n schedule ──▶ POST /api/mining/run ──▶ Scrapling ──▶ cache 7 dias
 qualquer fonte ──▶ POST /api/ingest/videos ──▶ Radar Viral (selo n8n)
```

## 1) RunPod — endpoint ComfyUI serverless

1. Crie conta em [runpod.io](https://www.runpod.io) e adicione créditos
   (US$ 10 já rendem centenas de gerações curtas).
2. **Deploy**: Serverless → Templates → procure **ComfyUI**
   (ex.: `runpod/worker-comfyui` ou templates da comunidade) → Deploy.
3. Anote:
   - `RUNPOD_ENDPOINT` = `https://api.runpod.ai/v2/<seu-endpoint-id>`
   - `RUNPOD_API_KEY` (Settings → API Keys)
4. **Workflow ComfyUI**: monte sua geração de vídeo (AnimateDiff, SVD,
   LTX-Video, Hunyuan…) no ComfyUI, exporte em **API Format** e cole no
   node *Montar Workflow ComfyUI* do workflow n8n (ponto marcado `>>> COLE AQUI <<<`).
5. Custo típico serverless: US$ 0,0002–0,0007 por segundo de GPU —
   um vídeo curto custa centavos; idle não cobra nada.

## 2) n8n — importar os workflows

1. Suba o n8n: `docker run -it -p 5678:5678 n8nio/n8n` (grátis, self-host)
   ou use o n8n Cloud.
2. Workflows → **Import from File** → importe os dois arquivos:
   - `n8n/fabrica-videos-comfyui-runpod.json`
   - `n8n/mineracao-automatica.json`
3. Variáveis de ambiente do n8n (Settings → Environment):
   ```
   RUNPOD_ENDPOINT=https://api.runpod.ai/v2/<id>
   MINERAAI_URL=https://<url-publica-do-mineraai>
   ```
4. No workflow da Fábrica, crie a credencial **Header Auth**:
   nome `Authorization`, valor `Bearer <RUNPOD_API_KEY>` e selecione-a
   nos dois nodes RunPod.
5. Copie a URL do webhook gerada (ex.: `https://seu-n8n.com/webhook/mineraai-video-job`).
6. Ative os dois workflows.

## 3) MineraAI — conectar tudo

Aba **APIs & Conexões** → cartão **n8n + RunPod/ComfyUI**:

| Campo | Valor |
|---|---|
| `N8N_WEBHOOK_URL` | URL do webhook do passo 2.5 |
| `N8N_TOKEN` | qualquer segredo (use o mesmo no callback) |
| `MINERAAI_PUBLIC_URL` | URL pública do MineraAI (para o n8n chamar de volta) |

Clique em **Testar conexão** — o MineraAI faz um ping no webhook.

## 4) Fluxo ponta a ponta

1. Estúdio IA → gere o roteiro → **🎬 Gerar vídeo na Fábrica** (ou crie direto lá)
2. O job aparece na fila: `enviado → processando → pronto` (auto-refresh 7s)
3. O n8n recebe o job, injeta o prompt, dispara o ComfyUI no RunPod,
   aguarda, salva o resultado e chama `POST /api/fabrica/jobs/{id}/result`
4. O MP4 abre no player dentro do MineraAI, com custo em USD

## 5) Endpoints para automação (referência)

```
POST /api/fabrica/jobs                  cria job + dispara webhook
GET  /api/fabrica/jobs                  fila de produção
POST /api/fabrica/jobs/{id}/result      callback (header X-Pipeline-Token)
GET  /api/fabrica/broll?q=              B-roll grátis (Pexels)
POST /api/mining/run                    minera keywords (Scrapling) + persiste
GET  /api/mining/summary                cache de mineração
POST /api/ingest/videos                 ingestão livre (header X-Pipeline-Token)
POST /api/settings/test/n8n             ping no webhook
POST /api/settings/test/fontes          teste Reddit/ML/Suggest
```

## 6) Onde entra o LangChain?

Recomendação: **dentro do MineraAI**, não no n8n. O `server/ai_engine.py`
já tem adaptadores Groq/Gemini/OpenAI — basta apontar para um agente
LangChain seu (ex.: `langchain` analisando os dados minerados e gerando
briefings). O n8n fica com orquestração/transporte, onde é imbatível;
o raciocínio LLM fica onde os dados estão.

## 7) Fontes gratuitas ativas nesta build

| Fonte | Chave | Uso |
|---|---|---|
| YouTube Data API v3 | grátis | busca oficial |
| TikTok Research API | grátis (aprovação) | busca oficial |
| Instagram Graph API | grátis (Business) | hashtag search |
| Scrapling coleta | nenhuma | coleta pública geral |
| Mercado Livre API | nenhuma | produtos reais BR (preço/vendas/reviews) |
| Reddit JSON | nenhuma | pauta viral |
| Google Suggest | nenhuma | demanda de busca |
| Google Trends RSS | nenhuma | termos em alta BR |
| oEmbed YouTube/TikTok | nenhuma | metadados reais de links |
| Pexels | grátis opcional | B-roll da Fábrica |
| Groq / Gemini | grátis | IA do Estúdio |
