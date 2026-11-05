# 🎬 Automação de vídeo — RunPod Serverless direto

> **Mudança de arquitetura nesta versão:** o caminho antigo era
> `MineraAI → n8n (webhook) → ComfyUI → RunPod`. O n8n saiu do projeto.
> Agora é `MineraAI → api.runpod.ai/v2/{endpoint}/runsync` — uma requisição,
> sem webhook, sem callback, sem máquina intermediária.

---

## 1. Por que tirar o n8n do caminho

| | Com n8n | Direto |
|---|---|---|
| Saltos de rede | 3 (MineraAI → n8n → RunPod → volta) | 1 |
| Pontos de falha | n8n fora do ar = fábrica parada | só o RunPod |
| Latência extra | fila do n8n + cold start do workflow | só o cold start do worker |
| Autenticação | token do n8n + token do RunPod | só o API key do RunPod |
| Observabilidade | log em duas máquinas | um log, um `runpod_job_id` |
| Custo | mais um VPS ligado | zero |

O n8n fazia sentido quando o MineraAI não tinha código para orquestrar. Tem agora:
`server/pipeline.py` faz fila, dispatch, polling, cancelamento e contabilização de custo.

---

## 2. Preparando o RunPod (uma vez)

### 2.1. Criar o endpoint serverless

1. <https://www.runpod.io/console/serverless> → **New Endpoint**.
2. Escolha um template com **ComfyUI** (ex.: `runpod/worker-comfyui`), ou suba a sua
   imagem com o ComfyUI exposto.
3. GPU: `RTX 4090` (melhor custo/qualidade para SDXL) ou `L4` para teste.
4. **Active Workers = 0** e **Max Workers ≤ 2** para começar: você paga só o que usa
   (cold start de 20–60 s na primeira chamada).
5. Anote o **Endpoint ID** (aparece na URL: `.../v2/{ENDPOINT_ID}/...`).

### 2.2. Criar o API key

<https://www.runpod.io/console/user/settings> → **API Keys** → *Create*.
A chave é `Bearer` e só aparece uma vez.

### 2.3. Preencher no MineraAI

Tela **APIs & Conexões → RunPod Serverless**, ou no `.env`:

```env
RUNPOD_API_KEY=rpa_xxxxxxxxxxxx
RUNPOD_ENDPOINT_ID=abc123def
RUNPOD_GPU_PRICE_HORA=0.44
```

Clique em **🩺 Health**. Deve responder:

```json
{"ok": true, "workers": {"prontos": 0, "executando": 0},
 "fila": {"na_fila": 0, "em_execucao": 0}}
```

`ok: false` + "Configure API key e endpoint id" = falta chave.
`401` = chave inválida/revogada. `404` = endpoint id errado ou endpoint pausado.

---

## 3. O workflow do ComfyUI

### Opção A — grafo padrão (zero config)

Sem `RUNPOD_WORKFLOW_TEMPLATE`, o MineraAI usa o SDXL txt2img de
`server/runpod.py::WORKFLOW_PADRAO` (checkpoint `sd_xl_base_1.0.safetensors`,
1024×1024, 28 steps, cfg 7). Funciona em qualquer worker ComfyUI padrão.

### Opção B — o seu workflow

1. Monte o fluxo no ComfyUI (ComfyUI Manager → instale os nós que precisar).
2. **Save (API Format)** → exporta o JSON no formato que a API espera.
3. Cole no card do RunPod em **APIs & Conexões** (campo *Workflow (JSON)*) ou em
   `RUNPOD_WORKFLOW_TEMPLATE`.
4. Confira em `GET /api/runpod/workflow` qual fonte está ativa (`padrao` ou `template`).

O MineraAI injeta automaticamente nos nós `CLIPTextEncode`:

| Posição | Conteúdo |
|---|---|
| 1º nó de texto positivo | prompt do job (+ estilo: `cinematic dark`, `ugc selfie`, …) |
| 1º nó de texto negativo | negativo do template ou o padrão (`blurry, watermark, text, low quality`) |
| todos os `KSampler` | `seed` aleatório por job (cada vídeo é diferente) |

---

## 4. Job ponta a ponta

### Síncrono (vídeo curto, resposta imediata)

```bash
curl -X POST localhost:8000/api/fabrica/jobs \
  -H 'Content-Type: application/json' \
  -d '{"product":"garrafa térmica","prompt":"cena 1: produto na mesa de mármore, luz lateral",
       "style":"dark","mode":"sync"}'
```

Fluxo interno: `POST /v2/{ep}/runsync` → resposta `COMPLETED` → MP4 salvo na
Biblioteca → créditos debitados. Limite do RunPod: **payload de entrada até 20 MB**
(por isso imagens de referência vão em base64 só quando são pequenas).

### Assíncrono (vídeo longo, fila)

```bash
# dispara
curl -X POST localhost:8000/api/fabrica/jobs \
  -H 'Content-Type: application/json' \
  -d '{"product":"garrafa","prompt":"unboxing","mode":"async"}'
# → {"job": {"id": "job_...", "status": "enviado", "runpod_job_id": "xyz"}}

curl localhost:8000/api/fabrica/jobs/{job_id}/poll   # consulta status uma vez
curl localhost:8000/api/fabrica/jobs/{job_id}/cancel # cancela no RunPod
```

Na UI, o botão **↻ Consultar** faz o poll — e o job só muda de estado com resposta
real do RunPod, nunca por tempo decorrido.

### Estados do job

`rascunho` → `enviado` → `processando` → `concluido` | `erro` | `cancelado`

Campos preenchidos na resposta: `runpod_job_id`, `execution_ms`, `delay_ms`
(cold start), `outputs` (URLs dos MP4) e `cost_usd`.

---

## 5. Custo

`cost_usd = (delay_ms + execution_ms) / 3.600.000 × RUNPOD_GPU_PRICE_HORA`

Referência com `RUNPOD_GPU_PRICE_HORA=0.44` (RTX 4090):

| Cenário | Tempo | Custo |
|---|---|---|
| SDXL 1024², 28 steps, worker quente | ~8 s | ≈ US$ 0,001 |
| Mesmo job com cold start | ~8 s + 45 s | ≈ US$ 0,006 |
| 6 cenas de um roteiro | ~48 s + 45 s | ≈ US$ 0,011 |

**Por isso `Active Workers = 0`:** worker quente 24/7 custa ~US$ 317/mês; sob demanda,
100 vídeos/mês custam menos de US$ 1. Se o volume crescer, suba `Max Workers` e
mantenha 1 worker ativo só no horário comercial.

O MineraAI cobra **250 créditos por vídeo**, o que cobre o custo de GPU com margem
em todos os planos.

---

## 6. Problemas comuns

| Sintoma | Causa provável | Correção |
|---|---|---|
| `401` / "API key do RunPod inválida" | chave revogada | gere outra em *User Settings* |
| `404` / "endpoint não encontrado" | endpoint id errado ou endpoint pausado | confira em Serverless → Endpoints |
| `IN_QUEUE` eterno | Max Workers = 0 | suba para ≥1 |
| `FAILED` com erro do ComfyUI | nó ausente no worker | instale o custom node na imagem |
| `mode: sync` estourando 20 MB | imagens de referência grandes | reduza, ou use `mode: async` |
| Timeout em `sync` | fila longa | `RUNPOD_TIMEOUT=300` ou use `async` |

Logs do worker (stdout do ComfyUI) ficam no console do RunPod em
**Endpoints → {seu endpoint} → Requests** — cada request tem o `job_id` que aparece
em `runpod_job_id` no MineraAI.

---

## 7. O que o MineraAI continua fazendo sozinho

A Fábrica não é só "chamar o RunPod": ela encadeia

1. roteiro do Estúdio IA (cena a cena) → 2. prompt por cena com o estilo escolhido →
3. dispatch ao RunPod → 4. download do MP4 → 5. registro na Biblioteca →
6. débito de créditos no ledger → 7. custo real de GPU gravado no job.

Se o RunPod estiver fora do ar, os passos 1–2 continuam funcionando (são offline) e o
job fica em `erro` com a mensagem exata — não há estado fantasma.
