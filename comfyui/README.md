# 🎨 ComfyUI Workflows — RunPod Serverless

Esta pasta contém **workflows ComfyUI em API Format** prontos para colar no RunPod.

## Como usar

1. **RunPod**: Serverless → Templates → ComfyUI (ex: `runpod/worker-comfyui`) → Deploy
2. Copie `RUNPOD_ENDPOINT` e `RUNPOD_API_KEY`
3. Abra um dos arquivos `workflows/*.json` → copie o conteúdo
4. No workflow n8n `fabrica-*`, cole no node `Montar Workflow ComfyUI` onde está marcado `>>> COLE AQUI <<<`
5. Ou use direto via API RunPod: `POST {RUNPOD_ENDPOINT}/run` com `{"input": {"workflow": <seu workflow>}}`

## Estrutura de um job MineraAI → ComfyUI

MineraAI envia para o webhook n8n:

```json
{
  "job_id": "job-abc123",
  "tipo": "imagem|video|misto",
  "product": "garrafa térmica premium",
  "prompt": "garrafa térmica na mesa de madeira, luz natural, estilo UGC...",
  "style": "ugc|dark|cinematic|produto|anime",
  "duration": 6,
  "roteiro": {
    "hook": "Pare de rolar...",
    "cenas": [
      {"nome": "GANCHO", "descricao": "...", "prompt": "close-up rosto...", "duracao": "2s"},
      {"nome": "DEMO", "descricao": "...", "prompt": "garrafa com gelo...", "duracao": "3s"}
    ],
    "narracao": "Texto da narração..."
  },
  "prompts": ["prompt extra 1", "prompt extra 2"],
  "callback_url": "https://seu-mineraai/api/fabrica/jobs/job-abc123/result",
  "token": "seu-token"
}
```

O n8n injeta `prompt`, `product`, `style` no workflow ComfyUI e dispara no RunPod.

## Workflows disponíveis

| Arquivo | Tipo | Modelo sugerido | Descrição |
|---|---|---|---|
| `workflow-imagem-sdxl.json` | imagem | `sd_xl_base_1.0.safetensors` | SDXL 768x1344 vertical, alta qualidade produto |
| `workflow-imagem-produto.json` | imagem | `realisticVisionV60` | Foto realista produto UGC, fundo casa |
| `workflow-video-animatediff.json` | vídeo | `sd15 + mm_sd_v15_v2` | AnimateDiff 16 frames, 512x768, 8fps |
| `workflow-video-ltx.json` | vídeo | `LTX-Video` | LTX-Video text-to-video 121 frames |
| `workflow-misto-ugc.json` | misto | SDXL + AnimateDiff | 3 imagens (hook/demo/cta) + vídeo curto UGC |
| `workflow-misto-curadoria.json` | misto | SDXL | Recebe roteiro curado, gera kit completo: capa + 3 variações + vídeo |

## Nodes importantes

- **CheckpointLoaderSimple**: modelo base (troque `ckpt_name` pelo seu)
- **CLIPTextEncode**: onde o prompt é injetado (n8n substitui `text`)
- **EmptyLatentImage**: resolução (vertical 9:16 = 768x1344 para imagem, 512x768 para vídeo)
- **KSampler**: seed aleatório, steps, cfg
- **AnimateDiff**: para vídeo (ADE_LoadAnimateDiffModel)
- **VHS_VideoCombine**: combina frames em MP4 (para vídeo)
- **SaveImage**: salva imagem

## Dicas

- **Vertical sempre**: TikTok/Reels = 9:16. Use 768x1344 (imagem) ou 512x768 (vídeo) ou 576x1024
- **Batch para cenas**: para roteiro com 3 cenas, use `batch_size: 3` e 3 prompts diferentes, ou 3 KSamplers separados
- **Custo RunPod**: imagem ~$0.002-0.005, vídeo 6s ~$0.02-0.08
- **Storage**: configure RunPod para salvar em S3/R2 e retornar URL, ou o worker retorna base64 que n8n salva
- **Estilos**: no n8n, mapeie `style` para prefixos de prompt:
  - `ugc`: "foto amadora, luz natural, mão tremendo, iPhone, casa real, "
  - `dark`: "dark aesthetic, moody lighting, cinematic, misterioso, "
  - `cinematic`: "cinematic lighting, 8k, ultra detailed, professional, "
  - `produto`: "product photography, white background, studio lighting, "
  - `anime`: "anime style, studio ghibli, vibrant colors, "

## Exemplo de payload RunPod

```json
{
  "input": {
    "workflow": {
      "3": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
      "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "garrafa térmica premium na mesa, luz natural, UGC", "clip": ["3", 1]}}
      // ... resto do workflow
    }
  }
}
```

Resposta RunPod:
```json
{
  "status": "COMPLETED",
  "output": {
    "images": [{"filename": "mineraai/job-abc123_00001.png", "type": "output"}],
    "video_url": "https://..."
  }
}
```

O n8n deve transformar isso em callback para MineraAI:
```json
{
  "status": "pronto",
  "video_url": "https://r2.../video.mp4",
  "images": [{"url": "https://r2.../img1.png", "prompt": "...", "cena": "GANCHO"}],
  "cost_usd": 0.045
}
```
