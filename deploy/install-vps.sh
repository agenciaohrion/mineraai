#!/usr/bin/env bash
# ============================================================
# MineraAI — instalador one-shot para VPS (Contabo/Ubuntu/Debian)
# Uso: dentro do repositório clonado →  ./deploy/install-vps.sh
# ============================================================
set -e
cd "$(dirname "$0")/.."

echo "==> [1/5] Dependências Python"
command -v python3 >/dev/null || { echo "Instale python3 primeiro: sudo apt install -y python3 python3-venv"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "==> [2/5] Arquivo de configuração"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    .env criado — edite depois com suas chaves (nano .env)"
fi

echo "==> [3/5] Serviço systemd (roda 24/7)"
if command -v systemctl >/dev/null 2>&1; then
  USER_ATUAL=$(whoami)
  REPO_DIR=$(pwd)
  sed "s|/opt/mineraai|$REPO_DIR|g; s|User=www-data|User=$USER_ATUAL|" \
      deploy/mineraai.service | sudo tee /etc/systemd/system/mineraai.service > /dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable mineraai > /dev/null 2>&1 || true
  sudo systemctl restart mineraai
  sleep 2
  if systemctl is-active --quiet mineraai; then
    echo "    serviço ativo ✔"
  else
    echo "    ⚠ serviço não subiu — veja: sudo journalctl -u mineraai -n 30"
  fi
else
  echo "    systemd indisponível — subindo em background"
  nohup ./run.sh > mineraai.log 2>&1 &
fi

echo "==> [4/5] Teste de saúde"
sleep 2
STATUS=$(curl -s --max-time 8 http://127.0.0.1:8000/api/status || echo "")
if [ -n "$STATUS" ]; then
  echo "    API respondeu ✔ — $STATUS" | head -c 220; echo
else
  echo "    ⚠ API não respondeu ainda (aguarde: sudo journalctl -u mineraai -f)"
fi

echo "==> [5/5] Acesso"
IP_PUBLICO=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "    Local:   http://127.0.0.1:8000"
echo "    Rede:    http://$IP_PUBLICO:8000"
echo ""
echo "Próximos passos (opcionais):"
echo "  • Chaves/APIs: edite .env e rode  sudo systemctl restart mineraai"
echo "  • Domínio + HTTPS: veja deploy/mineraai.example.nginx.conf + DEPLOY.md"
echo "  • Libere a porta no firewall da Contabo:  sudo ufw allow 8000/tcp"
