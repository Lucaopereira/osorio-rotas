# Osório: rotas dos motoboys

Código do despacho e do robô de rotas do Empório Osório (Itajubá-MG). Mantido pelo Lucas; o Ricardo e o Claude dele
leem, testam no PC e propõem mudança.

## O que é cada parte

| Pasta | O que faz |
|---|---|
| `robo_rotas/regras.py` | As regras de rota da reunião de 12/11/2026, em código, sem IA. Parâmetros no topo do arquivo. |
| `robo_rotas/despacho.py` | O despacho: pedido entra, o robô escolhe o motoboy; modos ao vivo e treino. |
| `robo_rotas/mapa.py`, `mapa_dados.py`, `dados/itajuba_ruas.json.gz` | Ruas de Itajubá (OpenStreetMap) para endereço, rota e tempo. Roda sem internet. |
| `robo_rotas/cenarios/` | Noites reais para treino (hora, canal, número do pedido, bairro, tipo). Sem nome nem endereço de cliente. |
| `robo_rotas/simulador.py` | Simulação de uma noite com as regras, para comparar jeitos de despachar. |
| `robo_rotas/tela/` | A tela de rotas do Ricardo (Waisorio), sem mudança, servida pelo servidor. |
| `gerencial/` | O servidor (Flask) que junta despacho, tela de rotas, simulador e painéis, com duas senhas (loja e gestão). |
| `*/deploy/` | Instalador para o servidor (VPS Ubuntu). |

## Como rodar no PC

```
pip install flask numpy scipy openpyxl pillow
python -m unittest discover -s robo_rotas/testes -t .
python -m unittest discover -s gerencial/testes -t .
```

Para abrir o servidor no PC, defina quatro variáveis (valores inventados, só para o teste local) e rode `python -m gerencial`
(abre em http://127.0.0.1:8080): `GERENCIAL_SENHA_LOJA` e `GERENCIAL_SENHA_GESTAO` (8+ caracteres, diferentes),
`GERENCIAL_SEGREDO` e `ROBO_TOKEN` (24+). Detalhe em `gerencial/README.md`.

## Regras para quem mexe aqui (inclusive agentes)

1. **Nunca grave senha, token, chave de API, login de iFood ou Zé em arquivo deste repositório**, nem em commit, nem em
   mensagem. Senhas do servidor são geradas no próprio servidor (`/etc/osorio-gerencial.env`).
2. **Não instale nem atualize o servidor** (`instalar.sh`, `python -m gerencial.publicar`, `ssh`) sem combinar com o Lucas.
   É a operação da loja: se cair numa sexta, os motoboys ficam sem rota.
3. **Mudança vira proposta, não vai direto na `main`.** Crie um branch, rode os testes e abra um pull request explicando o
   porquê (o que a loja viu, em que noite). Mudança de regra de rota passa pelo Ricardo e pelo Lucas antes.
4. **Endereço de cliente não sai do servidor.** O mapa é local; nada de mandar endereço para serviço de fora (Google, API
   de mapa). O despacho apaga o endereço quando a noite fecha.
5. **Não coloque base de venda, folha, nota fiscal ou planilha do Empório aqui.** Este repositório é só o código das rotas.
6. **A tela de rotas (`robo_rotas/tela/index.html`) é a do Ricardo.** Mudança nela, só a pedido dele.

## O que ainda falta

- O servidor no ar (falta a conta da VPS).
- O robô ler os pedidos sozinho: iFood, depois Zé, Cardápio Web e WhatsApp. Ver "O que trava" em `robo_rotas/README.md`.
- Uma noite de teste com a loja digitando os pedidos, para calibrar os parâmetros de `regras.py`.

Decisões em aberto do Ricardo: com motoboy de menos, o robô junta dois pedidos ou não; e se dois pedidos longe um do
outro podem sair juntos (a regra dos 800 m foi dita para três).
