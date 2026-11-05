# Como o Virlo minera — e como o MineraAI faz o mesmo

> Este documento responde a uma pergunta específica: **como a Virlo consegue os dados
> e como replicamos isso dentro do MineraAI**, sem n8n, sem Scrapling e sem copiar
> código proprietário.

---

## 1. O que é observável na Virlo

A Virlo expõe a arquitetura dela na própria documentação pública (`dev.virlo.ai/docs`),
porque a API é o produto:

| Família | Endpoint | O que faz | Preço |
|---|---|---|---|
| **Orbit** | `POST /v1/orbit` | enfileira uma busca por palavras-chave + plataformas + min_views | US$ 0,50 |
| | `GET /v1/orbit/{id}` | status + relatório de IA | grátis |
| | `GET /v1/orbit/{id}/videos` | resultados paginados com filtros de ordenação | grátis |
| | `GET /v1/orbit/{id}/creators/outliers` | criadores performando acima do normal | grátis |
| | `GET /v1/orbit/{id}/ads` | anúncios do Meta Ads Library do tema | grátis |
| **Comet** | `POST/GET/PATCH/DELETE /v1/comet` | configuração de monitoramento de nicho | US$ 0,50 |
| | `GET /v1/comet/{id}/videos` | coletas recorrentes daquele nicho | grátis |
| **Satellite** | `GET /v1/satellite/creator/{platform}/{username}` | ficha completa de um criador | US$ 0,50 |

Três detalhes dessa estrutura entregam o modelo inteiro:

1. **`POST /orbit` não devolve vídeos — devolve um `id`.** A doc avisa que o
   processamento leva **5 a 10 minutos**. Isso é a assinatura de uma **fila de
   coleta**: o pedido entra, um worker processa depois, e você consulta o resultado.
   Busca síncrona não levaria 10 minutos — coleta agendada leva.
2. **Leitura é gratuita, criação é paga.** O custo está em *disparar* uma coleta nova,
   não em consultar. Confirma que o gasto deles é com aquisição de dado (requisição,
   proxy, GPU de parsing), não com servir o JSON.
3. **`Comet` existe separado do `Orbit`.** Se fosse só busca, um endpoint bastaria.
   O Comet é a mesma coleta rodando **por agendamento** — ou seja, eles mantêm uma
   base própria atualizada continuamente e vendem acesso a ela.

**Conclusão honesta:** a Virlo não "consulta a API do TikTok" — não existe API pública
que entregue isso. Ela mantém um pipeline próprio de coleta contínua, normaliza tudo em
um índice único (por isso um Orbit busca em TikTok + YouTube + Instagram de uma vez) e
vende tanto o índice pronto (`/videos`, `/trends`, `/hashtags`) quanto a busca sob demanda.

O que **não** é observável: como eles coletam tecnicamente (proxies, fingerprints, quais
endpoints internos das plataformas). Isso não está na doc e não vamos replicar — é
justamente a parte que envolve risco jurídico e que exige engenharia reversa de binário.

---

## 2. O que copiamos: a arquitetura

`server/mining.py` replica o **desenho**, com fontes legítimas:

```
                ┌──────────────── ORBIT (busca em fila) ────────────────┐
 POST /api/mining/orbits                                              │
   keywords[] + platforms[] + min_views  ──▶  job persistido (queued) │
                                              │                      │
                                     worker (orbit_run)              │
                                              │                      │
        ┌─────────────┬───────────────────────┴──────────┐           │
        ▼             ▼                                  ▼           │
  YouTube Data   Virlo API (leitura)          ingestão externa       │
        └─────────────┴───────────────┬──────────────────┘           │
                                      ▼                              │
                        normalize (schema.py) → dedupe               │
                                      ▼                              │
                     métricas (metrics.py): viral + outlier         │
                                      ▼                              │
                        persistido (data/orbits.json) ───────────────┘
                                      │
                    ┌─────────────────▼──────────────────┐
                    │ COMET (agendado): mesmo pipeline   │
                    │ + série temporal por ciclo         │
                    └────────────────────────────────────┘
```

### Etapas, uma por uma

| # | Etapa | Onde | Por quê |
|---|---|---|---|
| 1 | **Enfileirar** | `orbit_create()` | keywords + plataformas viram um job persistido. Sobrevive a restart. |
| 2 | **Coletar** | `_coletar_keyword()` | uma keyword por vez, erro isolado por fonte — YouTube fora não impede a Virlo de rodar. |
| 3 | **Normalizar** | `schema.normalize_video()` | o mesmo vídeo tem o mesmo `uid`, venha de onde vier. |
| 4 | **Deduplicar** | `schema.dedupe()` | duas fontes trazendo o mesmo vídeo = um registro, com a fonte mais confiável vencendo campo a campo. |
| 5 | **Pontuar** | `metrics.enrich_videos()` | `viral_score`, `velocity` e sobretudo `outlier_score` (views ÷ baseline do criador). |
| 6 | **Persistir série** | `comet_run()` | cada ciclo empilha `{videos, outliers, mediana}` — é o que permite ver tendência em vez de foto. |

### O que o Comet adiciona

Um Orbit é uma foto. O Comet é o filme. Cada ciclo guarda:

```json
{"at": "2026-11-10T12:00:00Z", "videos": 42, "outliers": 7,
 "mediana_views": 53800, "top_outlier_score": 96}
```

Com 3+ ciclos já dá para responder "este nicho está subindo ou saturando?" — a pergunta
que a busca avulsa nunca responde.

---

## 3. Por que o outlier é o produto, não o dado

Um vídeo com 2 milhões de views é irrelevante se o criador tem 2 milhões de views em
tudo. O que muda decisão é o **desvio**:

```
outlier_ratio = views do vídeo ÷ baseline do criador
baseline      = mediana das views do criador no corpus   (confiança alta com ≥3 vídeos)
              = mediana do nicho pesquisado              (confiança estimada, sem histórico)
```

`outlier_score` traduz esse ratio para 0–100 em escala logarítmica:
2x ≈ 28 pontos · 10x ≈ 60 · 50x ≈ 90 · 500x ≈ 100.

Regra que não abrimos mão: **o próprio vídeo nunca é o próprio baseline**. Se fosse,
todo vídeo seria "outlier de 4x" e o número perderia sentido.

---

## 4. Usando

```bash
# 1) buscar e minerar na hora (10 créditos)
curl -X POST localhost:8000/api/mining/orbits \
  -H 'Content-Type: application/json' \
  -d '{"keywords":["skincare","glass skin"],"platforms":["tiktok","youtube"],"min_views":10000}'

# 2) ver o resultado
curl localhost:8000/api/mining/orbits/{orbit_id}

# 3) criar monitor agendado (Comet)
curl -X POST localhost:8000/api/mining/comets \
  -H 'Content-Type: application/json' \
  -d '{"keywords":["achadinhos de cozinha"],"frequency":"6h"}'

# 4) rodar um ciclo manualmente
curl -X POST localhost:8000/api/mining/comets/{comet_id}/run

# 5) explicação do pipeline (mesmo texto que a UI mostra)
curl localhost:8000/api/mining/como-funciona
```

### Quando a mineração vem vazia

Sem fonte real conectada, o Orbit termina com `0 vídeos` e devolve um erro explícito:
*"Nenhuma fonte real conectada: configure YouTube Data API ou a Virlo API"*.
Não preenchemos com dados de demonstração — a UI do Radar tem o fallback demo, a
mineração não. Um job de mineração que "funciona" com dado inventado seria pior que
um job que admite não ter fonte.

---

## 5. Alternativa: usar a Virlo como fonte

Se você não quiser manter coleta própria, a Virlo entra como fonte pronta:

- `VIRLO_API_KEY` + `VIRLO_AUTO_USE=1` → o Radar mescla o índice deles
  (`source: "virlo"` em cada vídeo).
- Orbit/Satellite/Comet da Virlo ficam expostos em `/api/virlo/*`, com custo de
  60 créditos por chamada paga (≈ US$ 0,50).
- Custo estimado: 1 Orbit + leituras ≈ US$ 0,50 por pesquisa profunda.

Trade-off direto:

| | Mineração própria | Virlo API |
|---|---|---|
| Custo | CPU do seu servidor + chaves oficiais grátis | US$ 0,50 por busca profunda |
| Cobertura TikTok/IG | só com Research API/Graph aprovadas | completa de imediato |
| Manutenção | você | eles |
| Controle do dado | total | índice deles |

O MineraAI suporta os dois ao mesmo tempo — e é isso que a camada `research.py`
resolve: o consumidor não sabe de onde veio.
