# Servidor gerencial

Um endereço só para o que precisa rodar sem o PC ligado: o despacho em tempo real, a tela de rotas, o simulador de
rotas e os painéis.
Flask, um processo, SQLite. Feito em 18/11/2026.

| Quem | Senha | Vê |
|---|---|---|
| Loja (tablet do caixa, motoboys) | `GERENCIAL_SENHA_LOJA` | despacho (ao vivo e treino) e tela de rotas |
| Ricardo e Lucas | `GERENCIAL_SENHA_GESTAO` | rotas, simulador, painéis (os painéis têm folha com nome) |
| Robô de rotas | `ROBO_TOKEN` | grava o painel de rotas, lê os toques da loja |

A tela de rotas é a mesma de `robo_rotas/servidor.py` (HTML do Ricardo sem mudança, ponte para o banco) e a API
também (`/api/estado`, `/api/eventos`, `/api/painel/atual`, `/api/motoboys/<id>`): `robo_rotas/tela_api.py` e
`tela/ponte.js` funcionam sem mudar nada. Este servidor substitui o `waisorio.service` na VPS.

## Despacho em tempo real (`/despacho/real` e `/despacho/treino`, 19 e 20/11)

- **Dois modos que não se misturam:** Ao vivo (noite de verdade, relógio de verdade) e Treino (relógio próprio:
  parar, 1×/5×/10×/20×, +5 min; a noite anda minuto a minuto por dentro, então acelerar não distorce a espera).
- **Endereço de verdade:** rua e número com sugestão enquanto digita, link de localização colado do WhatsApp, ou só o
  bairro. Tudo pelo mapa local de Itajubá (`robo_rotas/mapa.py`, OpenStreetMap baixado uma vez por
  `python -m robo_rotas.mapa_dados`): o endereço do cliente não sai do servidor. Precisão: a rua (o mapa não tem o
  número da casa).
- **Rota e tempo pelas ruas** (menor caminho na malha de 24 mil trechos), desenhada no mapa; a moto anda pela rota.
- **Regras da reunião** (`regras.sugerir`, máximo 2 por saída). A loja troca o motoboy de qualquer pedido na lista
  (fica marcado com alfinete) ou devolve para o robô.
- **Cenários de treino** (`robo_rotas/cenarios.py`): noites reais tiradas das bases (hora, canal, bairro e tempo de
  cozinha do iFood pelo Cardápio Web; bairro do Zé sorteado pela frequência real, marcado), teste rápido (3 motoboys,
  4 pedidos), planilha importada (modelo com lista suspensa em `/api/despacho/modelo.xlsx`) e pedido digitado.
  Piloto automático: o motoboy sai sozinho quando o robô manda.
- **Resultado da noite** (tempo até a porta, atrasados, comida fria, espera, pedidos por saída, km) e a noite em
  Excel. Botão de rota no Google Maps e "copiar rota" para mandar ao motoboy. Som quando alguém deve sair.

## No PC

```
set GERENCIAL_SENHA_LOJA=...  (8+ caracteres)
set GERENCIAL_SENHA_GESTAO=... (diferente da loja)
set GERENCIAL_SEGREDO=...      (24+)
set ROBO_TOKEN=...             (24+)
python -m gerencial            # http://127.0.0.1:8080; painéis = pasta da reunião da semana
python -m unittest discover -s gerencial/testes -t .
```

## Na VPS (Ubuntu 22.04 ou 24.04)

```
python -m gerencial.publicar root@IP --codigo           # manda gerencial/ e robo_rotas/
ssh root@IP 'bash /root/osorio/gerencial/deploy/instalar.sh'
python -m gerencial.publicar root@IP                    # depois de cada python -m pipeline: os painéis
```

O instalador põe Python com venv (Flask, gunicorn, Pillow), Caddy com HTTPS automático (sem domínio:
`IP-com-traços.sslip.io`), o serviço `osorio-gerencial`, e abre só 22, 80 e 443. As senhas, o segredo e a chave do
robô são gerados **na VPS** (`/etc/osorio-gerencial.env`) e aparecem uma vez. Rodar de novo atualiza o código e
mantém senhas, banco e painéis.

**Um processo só (`gunicorn -w 1 -k gthread --threads 32`):** a tela de rotas espera a próxima mudança do banco
dentro do processo; com dois processos, a tela de um não acorda com a gravação do outro.

## Onde hospedar

- **VPS com acesso root** (DigitalOcean, Hostinger VPS, HostGator VPS, Contabo, Oracle grátis): serve. O instalador
  é para Ubuntu; se o painel da hospedagem oferecer AlmaLinux ou CentOS com cPanel, escolher a imagem Ubuntu limpa.
- **Hospedagem compartilhada (HostGator e parecidas, planos de site):** não serve. Não deixa um processo Python
  rodando o tempo todo, e a tela de rotas e o robô precisam disso. Serve para o site institucional, que é outro
  projeto.

## O que falta

- O robô de rotas ainda não lê pedido de verdade (ver `robo_rotas/README.md`, "O que trava").
- A publicação dos painéis é manual (`gerencial.publicar`). Quando o pipeline rodar na própria VPS (banco de dados
  em janeiro), ela some.
