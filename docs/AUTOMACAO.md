# 🤖 Automação — n8n + RunPod/ComfyUI + MineraAI (Imagem, Vídeo, Misto)

Guia para colocar o pipeline monumental em produção: **imagens, vídeos e kits mistos** gerados por IA via ComfyUI RunPod, roteados por n8n, entregues dentro do MineraAI.

```
FÁBRICA COMFYUI (imagem | vídeo | misto)
MineraAI ──POST /api/fabrica/jobs {tipo, product, prompt, roteiro:{hook,cenas[],narracao}, prompts[]}
    │
    ├─▶ n8n ROUTER webhook: mineraai-fabrica-job
    │      Detecta Tipo → Switch
    │      ├─▶ imagem → mineraai-imagem-job → monta N KSamplers SDXL → RunPod /run → /status → extrai images[]
    │      ├─▶ video  → mineraai-video-job  → AnimateDiff 16f / LTX 121f + STYLE_PREFIX → video_url + thumb
    │      └─▶ misto  → mineraai-misto-job  → 4 imagens CAPA/HOOK/DEMO/CTA + 1 vídeo AnimateDiff 24f
    │              │
    │              ▼ POST {workflow API Format}
    │      RunPod Serverless (ComfyUI) ──▶ GPU paga por segundo (~centavos)
    │              │ storage (R2/Supabase/S3) ──▶ video_url + images[]
    │              ▼
    └────────── callback POST /api/fabrica/jobs/{id}/result {video_url, images[], cost_usd} → MineraAI
                         header X-Pipeline-Token = N8N_TOKEN

CURADORIA → FÁBRICA
curadoria-publicacao.json: Biblioteca → Gera ComfyUI? → Via Fábrica MineraAI? 
  → sim: POST /api/fabrica/jobs {tipo=misto|imagem|video, roteiro curado}
  → não: monta workflow direto → RunPod → Salva Biblioteca → webhook externo → publicado

MINERAÇÃO CONTÍNUA
n8n schedule ──▶ POST /api/mining/run ──▶ Scrapling ──▶ cache 7 dias
qualquer fonte ──▶ POST /api/ingest/videos ──▶ Radar Viral (selo n8n)
curadoria-automatica: schedule 1h → auto-curate keywords → fila → outliers ≥75 → alerta
```

## 1) RunPod — endpoint ComfyUI serverless

1. Crie conta em [runpod.io](https://www.runpod.io) e adicione créditos
   (US$ 10 já rendem centenas de gerações curtas).
2. **Deploy**: Serverless → Templates → procure **ComfyUI**
   (ex.: `runpod/worker-comfyui` ou `runpod/serverless-ckpt-comfyui` com SDXL + AnimateDiff + LTX) → Deploy.
   Dica: use template com `realisticVision`, `SDXL base 1.0`, `AnimateDiff v2`, `VHS nodes` e `LTX-Video` instalados.
3. Anote:
   - `RUNPOD_ENDPOINT` = `https://api.runpod.ai/v2/<seu-endpoint-id>`
   - `RUNPOD_API_KEY` (Settings → API Keys)
4. **Workflows ComfyUI**: já prontos em `comfyui/workflows/` em API Format:
   - `workflow-imagem-sdxl.json` (768x1344 9:16 SDXL)
   - `workflow-imagem-produto.json` (batch 3 produto UGC)
   - `workflow-video-animatediff.json` (512x768 16 frames AnimateDiff + VHS_VideoCombine)
   - `workflow-video-ltx.json` (576x1024 121 frames LTX-Video 24fps)
   - `workflow-misto-ugc.json` (3 KSamplers GANCHO/DEMO/CTA + vídeo)
   - `workflow-misto-curadoria.json` (capa + 3 imgs + vídeo 24f, recebe roteiro curado)
   - Cole no node `Montar Workflow` do workflow n8n correspondente, ou use direto via API RunPod.
5. Custo típico serverless: US$ 0,0002–0,0007 por segundo de GPU —
   imagem ~$0.002-0.005, vídeo 6s ~$0.02-0.08; idle não cobra.

## 2) n8n — importar os workflows (7 arquivos)

1. Suba o n8n: `docker run -it -p 5678:5678 n8nio/n8n` (grátis, self-host) ou n8n Cloud.
2. Workflows → **Import from File** → importe:
   - `n8n/fabrica-router-comfyui-runpod.json` (ROUTER principal — webhook `mineraai-fabrica-job`)
   - `n8n/fabrica-imagens-comfyui-runpod.json` (webhook `mineraai-imagem-job`)
   - `n8n/fabrica-videos-comfyui-runpod.json` (webhook `mineraai-video-job`)
   - `n8n/fabrica-mista-comfyui-runpod.json` (webhook `mineraai-misto-job`)
   - `n8n/curadoria-publicacao.json` (curadoria → biblioteca/fábrica/webhook externo, agora com tipo misto)
   - `n8n/mineracao-automatica.json` + curadoria-* (opcionais)
3. Variáveis de ambiente do n8n (Settings → Environment):
   ```
   RUNPOD_ENDPOINT=https://api.runpod.ai/v2/<id>
   RUNPOD_API_KEY=seu_token_runpod
   MINERAAI_URL=https://<url-publica-do-mineraai>
   N8N_TOKEN=mesmo_token_de_APIs_&_Conexões
   ```
4. Em cada workflow fábrica, crie credencial **Header Auth**:
   nome `Authorization`, valor `Bearer {{$env.RUNPOD_API_KEY}}` e selecione-a nos nodes RunPod (`/run` e `/status`).
   Configure `RUNPOD_ENDPOINT` em `{{$env.RUNPOD_ENDPOINT}}` nos nodes HTTP.
5. Copie a URL do webhook do **ROUTER** (`fabrica-router-comfyui-runpod.json` → `https://seu-n8n.com/webhook/mineraai-fabrica-job`).
   Esse é o único que o MineraAI precisa chamar — ele roteia para os outros 3 internamente via `http://localhost:5678/webhook/...` (se self-host) ou via URL pública se Cloud.
6. Ative os 4 workflows de fábrica (router + 3). Se usar curadoria, ative `curadoria-publicacao.json`.

## 3) MineraAI — conectar tudo

Aba **APIs & Conexões** → cartão **n8n + RunPod/ComfyUI**:

| Campo | Valor | Nota |
|---|---|---|
| `N8N_WEBHOOK_URL` | URL do router `mineraai-fabrica-job` | Ex: `https://seu-n8n.com/webhook/mineraai-fabrica-job` |
| `N8N_TOKEN` | segredo compartilhado | Mesmo usado no callback `X-Pipeline-Token` |
| `MINERAAI_PUBLIC_URL` | URL pública do MineraAI | Para n8n chamar `/api/fabrica/jobs/{id}/result` |

Clique em **Testar conexão** — o MineraAI faz um ping no webhook router.

Env vars adicionais no `.env` do MineraAI (opcionais, já documentadas em `.env.example`):
```
RUNPOD_ENDPOINT=https://api.runpod.ai/v2/xxx
RUNPOD_API_KEY=xxx (se MineraAI chamar RunPod direto sem n8n, modo curadoria-publicacao direto)
```

## 4) Fluxo ponta a ponta (imagem | vídeo | misto)

1. **Fábrica ComfyUI** → escolha tipo `misto` (recomendado) → preencha produto + roteiro JSON (ou use Exemplo misto UGC) → Enviar
2. Job aparece na fila: `fila → enviado (router) → processando (RunPod) → pronto` (auto-refresh 7s)
3. n8n router recebe `{tipo, product, prompt, roteiro:{hook,cenas[],narracao}}`, injeta `STYLE_PREFIX` + prompts por cena nos nodes CLIPTextEncode do workflow ComfyUI API, dispara RunPod `/run` → polling `/status` com retry loop (Wait + IF COMPLETED)
4. Extrai `video_url` (VHS_VideoCombine) + `images[]` (SaveImage) → POST callback MineraAI com token
5. No MineraAI, clique **▶ Ver** → modal com player vídeo + galeria 4 imagens + links + custo

**Curadoria → Fábrica**: em `curadoria-publicacao.json`, quando item aprovado, workflow gera `roteiroFinal` a partir de `enriquecimento.hooks[0]` + `analise.formato_detectado`, monta `promptsImagem` por cena + `promptVideo` + `promptFabrica`, e se `usar_fabrica_mineraai=true` envia para `/api/fabrica/jobs` tipo=misto; senão monta ComfyUI direto RunPod e salva em `/api/library` + webhook externo.

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
