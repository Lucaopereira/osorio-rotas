#!/usr/bin/env bash
# Instala a tela Waisorio numa VPS Ubuntu nova. Roda como root, uma vez:
#   scp -r robo_rotas root@IP:/root/  &&  ssh root@IP 'bash /root/robo_rotas/deploy/instalar.sh'
# Sem domínio, usa IP.sslip.io (o próprio IP vira nome e o HTTPS funciona). Com domínio: DOMINIO=tela.exemplo.com.br
# Gera a senha da loja e a chave do robô na própria VPS e mostra uma vez. Nada disso vai para o repositório.
set -euo pipefail

IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
DOMINIO=${DOMINIO:-${IP//./-}.sslip.io}

apt-get update -q
apt-get install -y -q python3 debian-keyring debian-archive-keyring apt-transport-https curl gnupg ufw
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

id robo >/dev/null 2>&1 || adduser --disabled-password --gecos "" robo
mkdir -p /home/robo/app /home/robo/dados
rm -rf /home/robo/app/robo_rotas && cp -r "$(dirname "$0")/.." /home/robo/app/robo_rotas
rm -rf /home/robo/app/robo_rotas/deploy /home/robo/app/robo_rotas/testes /home/robo/app/robo_rotas/tela.db* /home/robo/app/robo_rotas/__pycache__
chown -R robo:robo /home/robo/app /home/robo/dados

NOVO=0
if [ ! -f /etc/waisorio.env ]; then
  NOVO=1
  umask 077
  cat > /etc/waisorio.env <<ENV
TELA_SENHA=$(python3 -c 'import secrets; print(secrets.token_urlsafe(9))')
TELA_SEGREDO=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
ROBO_TOKEN=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
TELA_BANCO=/home/robo/dados/tela.db
TELA_PORTA=8080
TELA_HTTPS=1
ENV
  chown root:robo /etc/waisorio.env && chmod 640 /etc/waisorio.env
fi

cp "$(dirname "$0")/waisorio.service" /etc/systemd/system/waisorio.service
sed "s/{\$DOMINIO}/$DOMINIO/" "$(dirname "$0")/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now waisorio
systemctl restart waisorio caddy

ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && ufw --force enable >/dev/null

sleep 2
curl -fsS http://127.0.0.1:8080/saude >/dev/null && echo "Servidor da tela: ok"
echo "Endereço: https://$DOMINIO"
if [ "$NOVO" = 1 ]; then
  echo "Senha da loja e chave do robô (aparecem só agora; ficam em /etc/waisorio.env):"
  grep -E '^(TELA_SENHA|ROBO_TOKEN)=' /etc/waisorio.env
fi
