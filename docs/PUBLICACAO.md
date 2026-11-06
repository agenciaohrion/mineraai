# 📤 Publicação no YouTube — fechando o loop

> O ciclo do produto era *descobrir → validar → roteiro → produzir* e parava aí.
> Este documento cobre os dois passos que faltavam: **publicar** e **medir** — e
> o que se faz com a medição.

---

## 1. Por que só YouTube

| Plataforma | Upload por API | Situação |
|---|---|---|
| **YouTube** | ✅ `videos.insert` (Data API v3) | funciona hoje, cota gratuita de 10.000 unidades/dia |
| TikTok | API de Content Posting — exige app aprovado, auditoria e conta business | fora do escopo por ora |
| Instagram | Graph API de publicação — só conta Business, mídia hospedada publicamente, revisão de app | fora do escopo por ora |

Começar pelo YouTube não é limitação técnica: é o único caminho onde o produto
publica de verdade **sem** depender de uma aprovação de meses que pode ser negada.
Quando as outras duas forem aprovadas, entram como mais um destino — a camada de
publicação (`server/publications.py`) não sabe qual plataforma é.

---

## 2. Autorizando o canal (uma vez)

A chave de API do YouTube que o Radar usa **só lê**. Para publicar é preciso OAuth
do dono do canal — um app no Google Cloud com escopo de upload.

### 2.1. Criar o app OAuth

1. <https://console.cloud.google.com/> → crie/escolha um projeto.
2. **APIs e serviços → Biblioteca** → ative **YouTube Data API v3**.
3. **Tela de consentimento OAuth** → tipo *Externo* → preencha nome e e-mail.
   Em *Escopos*, adicione:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube.readonly`
4. Em *Usuários de teste*, adicione a conta Google dona do canal. Enquanto o app
   estiver em modo de teste, só esses usuários conseguem autorizar (e o refresh
   token dura 7 dias — publique o app ou reautorize semanalmente durante os testes).
5. **Credenciais → Criar credenciais → ID do cliente OAuth** → tipo
   *Aplicativo da Web*. Em **URIs de redirecionamento autorizados**, coloque
   exatamente o valor de `redirect_uri`:

   ```
   https://seu-dominio.com.br/api/integrations/youtube/callback
   ```

   (Em desenvolvimento: `http://localhost:8000/api/integrations/youtube/callback`.)

### 2.2. Preencher no MineraAI

**APIs & Conexões → Canal do YouTube** (ou no `.env`):

```env
YOUTUBE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
YOUTUBE_CLIENT_SECRET=GOCSPX-xxxxxxxx
YOUTUBE_REDIRECT_URI=https://seu-dominio.com.br/api/integrations/youtube/callback
```

Clique em **🔗 Autorizar** → escolha o canal → autorize. O Google devolve o
navegador para o callback, que troca o `code` por `access_token` + `refresh_token`,
lê o canal e mostra a página de retorno. Depois disso, **📺 Canal** deve mostrar
nome, inscritos e total de vídeos, e **🔍 Testar** deve responder ok.

> O refresh token só é emitido com `access_type=offline` — está no pedido, e o
> servidor renova o access token sozinho quando faltam 60 segundos.

---

## 3. Publicando

Na **Fábrica**, todo job com arquivo salvo (`media_url`) ganha o botão **📤 Publicar**:

```
título (prefill = nome do produto)
descrição (prefill = prompt do roteiro)
tags
privacidade: unlisted (padrão) · private · public
[ ] conteúdo feito para crianças
```

Ao publicar, o job passa a `publicado` e o vídeo ganha um registro em
`data/publications.json` com `video_id`, URL, privacidade e a primeira medição.

**Privacidade padrão é `unlisted`.** Publicar em público é decisão explícita do
usuário, nunca efeito colateral de um clique em "publicar" — um vídeo meu aparecendo
no canal de um cliente sem ele ter pedido seria um bug grave.

API equivalente:

```bash
curl -X POST localhost:8000/api/fabrica/jobs/{job_id}/publicar \
  -H 'Content-Type: application/json' \
  -d '{"titulo":"Garrafa térmica 24h","descricao":"cena 1...","tags":["garrafa"],
       "privacidade":"unlisted","made_for_kids":false}'
```

**Custo:** 40 créditos por publicação. Um upload consome ~**1.600** das 10.000
unidades diárias de cota do YouTube — ou seja, ~6 uploads/dia com a cota gratuita.
A leitura de métricas custa 1 unidade por chamada (até 50 vídeos por vez).

---

## 4. Medindo — e realimentando

A cada `PUBLISH_SYNC_INTERVALO_H` (padrão 6h), enquanto o vídeo estiver dentro da
janela `PUBLISH_JANELA_DIAS` (padrão 7 dias), o MineraAI lê
`statistics.viewCount/likeCount/commentCount` e empilha um snapshot:

```json
{"at": "2026-11-10T12:00:00Z", "views": 1500, "likes": 90,
 "comments": 7, "idade_h": 26.4}
```

Na tela **Publicações** isso vira velocidade (`views/h`) e uma sparkline da série.

### O passo que fecha o loop

Cada leitura também faz:

```python
mining.ingest_videos([video_com_metricas_reais], "publicado", substituir=True)
```

Ou seja: **o vídeo publicado entra no corpus da mineração** com `source: "publicado"`,
e é atualizado (não duplicado) a cada nova medição. Consequências práticas:

1. ele aparece no Radar com o selo `publicado` quando o termo casa com o título/tags;
2. ele participa do cálculo de `outlier_score` do nicho, com dados 100% reais;
3. o baseline deixa de ser "o que os outros fizeram" e passa a incluir "o que a
   gente fez" — que é a única forma de o modelo aprender com o próprio acerto.

Verificável em `GET /api/search?q=<termo>&source=mineracao` e no contador
**No corpus** da tela de Publicações.

---

## 5. Estados e falhas

| Situação | O que acontece |
|---|---|
| Job sem arquivo local | 400 — "publique só depois de o vídeo estar em data/media" |
| Job não `pronto` | 409 — diz o status atual |
| Outro workspace | 403 |
| Nenhum canal autorizado | 400 — manda autorizar |
| Token expirado | 401 do Google → "renove a autorização" |
| Cota diária estourada | 403 com a mensagem do YouTube + quando reseta (meia-noite no Pacífico) |
| Arquivo sumiu do disco | 400 — "gere o vídeo de novo" |
| Vídeo removido do canal | publicação vira `indisponivel` na próxima leitura, com motivo |

Falha de **medição** nunca derruba a publicação: o vídeo está no YouTube, o
registro guarda o erro e a próxima leitura tenta de novo.

---

## 6. O que este módulo não faz

- **Não apaga vídeo do YouTube.** `DELETE /api/publicacoes/{id}` remove só o nosso
  registro — está escrito na resposta da API e no texto da UI.
- **Não publica em público por padrão** (ver §3).
- **Não mexe em comentários, legendas nem thumbnails.** Isso é `thumbnails.set` e
  `captions.insert`; ficam para quando houver uso real pedindo.
- **Não faz upload de Shorts específico** — um vídeo vertical < 60 s vira Short
  automaticamente pelo próprio YouTube.
