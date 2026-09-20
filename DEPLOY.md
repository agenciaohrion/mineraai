# 🚀 Deploy na VPS Contabo (guia passo a passo)

Dois caminhos para levar o repositório à sua VPS:

## Opção A — via Git (recomendado)

O código está em `github.com/agenciaohrion/mineraai`. Na VPS:

```bash
# 1) dependências básicas (Ubuntu/Debian da Contabo)
sudo apt update && sudo apt install -y git python3 python3-venv python3-pip

# 2) clonar (branch da sessão; se o PR #1 for mergeado, use main)
cd /opt
sudo git clone https://github.com/agenciaohrion/mineraai.git
sudo chown -R $USER:$USER /opt/mineraai
cd /opt/mineraai
git checkout arena/01a0ab0a-mineraai

# 3) configurar chaves/APIs (opcional — sem nada roda em modo demo + coleta)
cp .env.example .env
nano .env    # YOUTUBE_API_KEY, N8N_WEBHOOK_URL, MINERAAI_PUBLIC_URL etc.

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

## Conectar o n8n / agente Hermes

1. Com o MineraAI público (ex.: `https://seu-dominio.com.br`), vá em
   **APIs & Conexões** e preencha:
   - `MINERAAI_PUBLIC_URL` = `https://seu-dominio.com.br`
   - `N8N_WEBHOOK_URL` = webhook do seu agente/workflow n8n
   - `N8N_TOKEN` = um segredo qualquer (use o mesmo nos callbacks)
2. Teste com o botão **Testar conexão**.
3. Importe os workflows de `n8n/` no n8n e defina `MINERAAI_URL`
   (env do n8n) = `https://seu-dominio.com.br`.

## Rotinas úteis

```bash
sudo systemctl restart mineraai      # reiniciar após mudanças
sudo journalctl -u mineraai -f       # acompanhar logs em tempo real
cd /opt/mineraai && git pull         # atualizar para a versão mais nova
```

## Checklist final

- [ ] `curl https://seu-dominio.com.br/api/status` responde `modo: híbrido`
- [ ] Dashboard abre no navegador
- [ ] Teste de conexão n8n retorna ok
- [ ] Um job da Fábrica de Vídeos chega ao webhook do n8n
