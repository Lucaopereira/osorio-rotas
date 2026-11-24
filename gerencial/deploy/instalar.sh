#!/usr/bin/env bash
# Instala o servidor gerencial numa VPS Ubuntu (22.04 ou 24.04). Roda como root; rodar de novo atualiza o código.
#   python -m gerencial.publicar root@IP --codigo     (no PC: manda gerencial/ e robo_rotas/ para /root/osorio)
#   ssh root@IP 'bash /root/osorio/gerencial/deploy/instalar.sh'
# Sem domínio, usa IP.sslip.io (o próprio IP vira nome e o HTTPS funciona). Com domínio: DOMINIO=gestao.exemplo.com.br
# Gera as duas senhas, o segredo e a chave do robô NA PRÓPRIA VPS e mostra uma vez. Nada disso vai para o repositório.
set -euo pipefail
ORIGEM="$(cd "$(dirname "$0")/../.." && pwd)"
IP=$(curl -fsS https://api.ipify.org || hostname -I | awk '{print $1}')
DOMINIO=${DOMINIO:-${IP//./-}.sslip.io}

apt-get update -q
apt-get install -y -q python3 python3-venv debian-keyring debian-archive-keyring apt-transport-https curl gnupg ufw
if ! command -v caddy >/dev/null; then
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q && apt-get install -y -q caddy
fi

id robo >/dev/null 2>&1 || adduser --disabled-password --gecos "" robo
mkdir -p /home/robo/app /home/robo/dados/paineis
for pacote in gerencial robo_rotas; do
  rm -rf "/home/robo/app/$pacote" && cp -r "$ORIGEM/$pacote" "/home/robo/app/$pacote"
done
rm -rf /home/robo/app/*/deploy /home/robo/app/*/testes /home/robo/app/*/__pycache__ /home/robo/app/*/tela.db* /home/robo/app/gerencial/dados
[ -d /home/robo/venv ] || python3 -m venv /home/robo/venv
/home/robo/venv/bin/pip install -q -r "$ORIGEM/gerencial/deploy/requirements.txt"
chown -R robo:robo /home/robo/app /home/robo/dados /home/robo/venv

NOVO=0
if [ ! -f /etc/osorio-gerencial.env ]; then
  NOVO=1
  umask 077
  gera() { python3 -c "import secrets; print(secrets.$1)"; }
  cat > /etc/osorio-gerencial.env <<ENV
GERENCIAL_SENHA_LOJA=$(gera 'token_urlsafe(9)')
GERENCIAL_SENHA_GESTAO=$(gera 'token_urlsafe(12)')
GERENCIAL_SEGREDO=$(gera 'token_hex(32)')
ROBO_TOKEN=$(gera 'token_hex(32)')
GERENCIAL_BANCO=/home/robo/dados/tela.db
GERENCIAL_PAINEIS=/home/robo/dados/paineis
GERENCIAL_HTTPS=1
ENV
  chown root:robo /etc/osorio-gerencial.env && chmod 640 /etc/osorio-gerencial.env
fi

# a tela sozinha (robo_rotas/deploy) é substituída por este servidor: mesma porta, mesma API
if systemctl list-unit-files | grep -q '^waisorio.service'; then systemctl disable --now waisorio || true; fi
cp "$ORIGEM/gerencial/deploy/osorio-gerencial.service" /etc/systemd/system/osorio-gerencial.service
sed "s/{\$DOMINIO}/$DOMINIO/" "$ORIGEM/gerencial/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now osorio-gerencial
systemctl restart osorio-gerencial caddy
ufw allow OpenSSH >/dev/null && ufw allow 80/tcp >/dev/null && ufw allow 443/tcp >/dev/null && ufw --force enable >/dev/null

sleep 3
curl -fsS http://127.0.0.1:8080/saude >/dev/null && echo "Servidor gerencial: ok"
echo "Endereço: https://$DOMINIO"
if [ "$NOVO" = 1 ]; then
  echo "Senhas e chave do robô (aparecem só agora; ficam em /etc/osorio-gerencial.env):"
  grep -E '^(GERENCIAL_SENHA_LOJA|GERENCIAL_SENHA_GESTAO|ROBO_TOKEN)=' /etc/osorio-gerencial.env
fi
