# 🚀 Deploy na VPS Contabo (guia passo a passo)

Dois caminhos para levar o repositório à sua VPS:

## Opção A — via Git (recomendado)

O código está em `github.com/agenciaohrion/mineraai`. Na VPS:

```bash
# 1) dependências básicas (Ubuntu/Debian da Contabo)
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip

# 2) clonar
cd /opt
sudo git clone https://github.com/agenciaohrion/mineraai.git
sudo chown -R $USER:$USER /opt/mineraai
cd /opt/mineraai

# 3) configurar chaves/APIs (opcional — sem nada roda em modo demonstração)
cp .env.example .env
nano .env    # YOUTUBE_API_KEY, VIRLO_API_KEY, OPENAI_API_KEY, RUNPOD_* etc.

# 4) subir (cria o venv e instala tudo automaticamente)
./run.sh
```

Se o repo for privado, use um **Personal Access Token** (não compartilhe
senhas): `git clone https://SEU_TOKEN@github.com/agenciaohrion/mineraai.git`
ou configure uma chave SSH.

## Opção B — transferência direta (sem Git)

Da sua máquina local:

```bash
# baixar em zip do GitHub e enviar por SCP:
scp mineraai.zip root@IP_DA_CONTABO:/opt/
ssh root@IP_DA_CONTABO "cd /opt && apt install -y unzip && unzip mineraai.zip"

# ou rsync de uma pasta local:
rsync -avz --exclude .venv --exclude data ./mineraai/ root@IP_DA_CONTABO:/opt/mineraai/
```

## Rodar como serviço (não cair quando fechar o SSH)

```bash
sudo useradd -r -s /usr/sbin/nologin www-data 2>/dev/null || true
sudo chown -R www-data:www-data /opt/mineraai
sudo cp deploy/mineraai.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mineraai
sudo systemctl status mineraai     # deve aparecer "active (running)"
```

Teste: `curl http://127.0.0.1:8000/api/status`

## Expor na internet (nginx + HTTPS)

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo cp deploy/mineraai.example.nginx.conf /etc/nginx/sites-available/mineraai
sudo ln -s /etc/nginx/sites-available/mineraai /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d seu-dominio.com.br   # HTTPS grátis (Let's Encrypt)
```

Sem domínio? Aponte o `server_name` para o IP da Contabo e acesse
`http://IP_DA_CONTABO` (libere as portas 80/443 no painel da Contabo e no
`ufw`: `sudo ufw allow 80/tcp && sudo ufw allow 443/tcp`).

## Conectar as integrações

Nada de orquestrador externo: cada integração é chamada direto pelo servidor.

1. Abra **APIs & Conexões** em `https://seu-dominio.com.br`.
2. Preencha só os cards que você tem e clique em **Testar** em cada um:
   - **RunPod** → `RUNPOD_API_KEY` + `RUNPOD_ENDPOINT_ID` → botão 🩺 Health;
   - **Virlo** → `VIRLO_API_KEY` (`virlo_tkn_…`) → botão 💰 Saldo;
   - **Reddit** → `REDDIT_CLIENT_ID`+`SECRET` → 🔑 Emitir token OAuth;
   - **Mercado Livre** → `MELI_CLIENT_ID`+`SECRET` → 🔗 Autorizar (OAuth).
3. **Mercado Livre**: cadastre a URL de callback no app do Mercado Livre
   (Developers → sua aplicação → Redirect URI):
   `https://seu-dominio.com.br/api/integrations/meli/callback`
   O valor exato aparece em `GET /api/integrations` (`meli_redirect_uri`).
   Depois de autorizar, o Mercado Livre **devolve o navegador para essa URL**
   e a troca do código acontece sozinha — o usuário cai numa página de retorno
   que o leva de volta para a tela de integrações, já com os tokens salvos.
4. Quem preferir `.env`: as chaves têm os mesmos nomes e são lidas no boot.
   O que for salvo pela UI tem prioridade sobre o arquivo.

> O OAuth do Mercado Livre exige que o domínio seja público e HTTPS — o token de
> acesso dura 6h e é renovado automaticamente pelo próprio servidor.

## Publicar no YouTube (OAuth do canal)

Diferente da `YOUTUBE_API_KEY` (que só lê), publicar exige um **app OAuth**:

1. Google Cloud → APIs e serviços → ative **YouTube Data API v3**.
2. Tela de consentimento (Externo) com os escopos `youtube.upload` e `youtube.readonly`;
   adicione a conta dona do canal em *Usuários de teste*.
3. Credenciais → ID do cliente OAuth (Web) → **URIs de redirecionamento**:
   `https://seu-dominio.com.br/api/integrations/youtube/callback`
4. No app: **APIs & Conexões → Canal do YouTube** → preencha client id/secret →
   **🔗 Autorizar** → escolha o canal.

Cota: 10.000 unidades/dia, ~1.600 por upload (≈6 uploads/dia). A medição de
desempenho custa 1 unidade por chamada e roda a cada 6h dentro de
`PUBLISH_JANELA_DIAS` (7 dias). Detalhes e tabela de falhas:
[`docs/PUBLICACAO.md`](docs/PUBLICACAO.md).

## Disco: vídeos e retenção

Cada job da Fábrica deixa o MP4 em `data/media/<workspace>/`. Duas alavancas:

```env
MEDIA_MAX_MB=200          # teto por arquivo (0 = não baixa, mantém só a URL)
RETENTION_DIAS=90         # janela de retenção dos JSONs
RETENTION_INTERVALO_H=6   # frequência da poda automática
```

Acompanhe com `curl localhost:8000/api/maintenance/status` (mostra MB em disco,
contagens e o último relatório). Para backup, `data/media/` é o que importa de
verdade: o resto é reconstruível. Se o disco da VPS for pequeno, use
`MEDIA_MAX_MB=50` e uma janela menor.

## Rotinas úteis

```bash
sudo systemctl restart mineraai      # reiniciar após mudanças
sudo journalctl -u mineraai -f       # acompanhar logs em tempo real
cd /opt/mineraai && git pull         # atualizar para a versão mais nova
```

## Checklist final

- [ ] `curl https://seu-dominio.com.br/api/status` responde `modo: híbrido`
- [ ] Dashboard abre no navegador
- [ ] `GET /api/integrations` lista os 13 cards e o `.env` foi carregado
- [ ] Teste individual de cada integração retorna ok (ou explica o que falta)
- [ ] Um job da Fábrica com `mode: "sync"` devolve o MP4 (requer RunPod)
- [ ] Canal do YouTube autorizado (`📺 Canal` mostra o nome do canal)
- [ ] Um job publicado aparece em **Publicações** com views iniciais
- [ ] `.venv/bin/python -m server.tests_unified` e `-m server.tests_integracoes` passam na VPS
