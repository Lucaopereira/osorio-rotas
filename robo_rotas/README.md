# Robô de rotas

Prioridade 1 da reunião 13 (12/11/2026). A tela já existe: **Waisorio**, o artefato que o Ricardo montou em
14/11 (https://claude.ai/artifact/ND39JSeJEHZgpLA6NorsBW), com Painel, Saídas, Quadro, Mapa e Motoboys. Ela
lê um documento só (`painel/atual` no banco do artefato) e grava os toques da loja em `eventos` e o
cadastro em `motoboys`. O que falta é quem preenche `painel/atual` a cada rodada, fora do PC do Ricardo.

## O que já está aqui

`regras.py`: as seis regras da reunião em código, sem IA, com os parâmetros no topo
(velocidade, fator de rua, peso, distância para três paradas, espera máxima). `sugerir()` devolve uma
saída por motoboy e os pedidos sem motoboy; `para_tela()` monta o `saidas[]` da tela e
`sugestao_dos_cartoes()` monta o `sug` de cada cartão do quadro.

```
python -m unittest discover -s robo_rotas/testes -t .
```

Uma regra por teste: um por motoboy parado, dois só sem ninguém parado, três só com as paradas a até
800 m, lanche não vai com bebida grande, bebida pequena vai em cima, duas caixas de litrão vão sozinhas,
juntar não atrasa quem já estava na saída, motoboy "fora da loja" não entra.

## Por que a rodada é código e não IA

A meta é atualizar a cada 30 s a 1 min. Numa noite de 6 horas são 360 a 720 rodadas. Se cada rodada for uma
conversa com o Claude, o plano do Ricardo, que já está perto do limite, acaba na primeira semana. As regras
são fixas: código decide em milissegundos e dá sempre a mesma resposta para a mesma situação. O Claude
entra para mudar regra, não para rodar a regra.

## De onde a tela tira cada dado (lido do código dela em 15/11)

A tela é um HTML só. Ela não busca base nenhuma: lê três coisas do banco do próprio artefato e grava duas.

| O quê | Quem grava | Regra do banco | O que tem |
|---|---|---|---|
| `painel/atual` | o agente do Ricardo, a cada rodada | lê quem vê, **grava só o dono** | tudo o que aparece: `saidas[]`, `rua[]`, `quadro[]`, `parceiras[]`, `motoboys[]`, `ze_sem_nome[]`, `mapa` (loja e centro dos bairros), `atencao[]`, `agora`, `gerado`, `eventos_ate`, `replay`, `exemplo` |
| `eventos` | a loja, tocando na tela | grava quem pode usar | `saiu`, `voltou`, `fora`, `entrou`, `saiu_turno`, `pequeno`, `entregador` (código do Zé = motoboy), `fixar`, `soltar`, `pronto`, `producao`, com `hora` e `criado`; a tela mostra os 30 últimos |
| `motoboys` | a loja, na aba Motoboys | grava quem pode usar | só o primeiro nome |

O agente lê o Gestor do iFood pelo Claude in Chrome, lê o Zé (o código do entregador liga o pedido ao
motoboy), aplica os eventos em ordem de `criado` desde `eventos_ate`, roda as regras dele (o código cita
pelo menos a "regra 18") e grava o `painel/atual`. O fundo do mapa é OpenStreetMap baixado em 14/11
(`scripts/mapa_fundo.py` no repositório dele). No aparelho só fica o "Limpar rotas".

**Conseguimos mexer?** No HTML, sim: o Lucas tem acesso de edição e pode publicar outra versão. Não
fazemos isso sem combinar, porque é a tela de operação do Ricardo e o agente dele a mantém. **No banco,
não:** o painel só aceita gravação da conta do Ricardo, e o banco do artefato não abre para conta de
outra organização (testado em 15/11: nem leitura). Um programa na VPS não tem como gravar ali.

**Por isso:** a mesma tela servida pela VPS, com login. O HTML troca `claude.use("db")` por uma leitura
do servidor; `painel/atual` vem do robô, e os toques (`eventos`, `motoboys`) vão para o servidor. Os nomes
dos campos ficam iguais, então o agente do Ricardo e o robô falam a mesma língua.

**Uma fonte que encurta o caminho:** desde 03/10 o Cardápio Web recebe também o pedido do iFood (Burguer e
Marmita), com hora de criado, pronto e fechado, e o bairro. Ler o Cardápio Web ao vivo pode dar iFood e site
numa leitura só. Conferir se ele tem integração para isso antes de partir para as requisições do iFood.

## A cópia da tela na VPS (16/11)

`tela/index.html` é o HTML do Ricardo **sem mudança nenhuma**, copiado do artefato em 16/11 (versão
1794701471-6790, sha256 `ffcf3020…a8d64b`), com as duas imagens do mapa e o logo. `servidor.py` serve a tela e
põe antes do script dela um `tela/ponte.js`, que responde ao `claude.use("db")` com as mesmas funções do banco do
artefato (`doc().onSnapshot`, `collection().orderBy().limit()`, `add`, `set`, `delete`) e fala com o servidor.
Quando o Ricardo mudar a tela dele, basta copiar o `index.html` novo para cá.

- **Login:** uma senha da loja, pedida uma vez por aparelho (sessão de 30 dias, cookie assinado). Senha errada 8
  vezes no mesmo endereço trava 15 min.
- **Quem grava o quê, como no artefato:** `painel/atual` só o robô (chave `ROBO_TOKEN`); `eventos` e `motoboys`
  a loja logada. Evento de tipo desconhecido e nome de motoboy com mais de uma palavra são recusados. Evento
  mais velho que 7 dias sai do banco.
- **Atualização:** a tela pergunta ao servidor e ele segura a resposta até algo mudar (até 25 s). O painel novo
  aparece na hora, sem recarregar.
- **O robô:** `tela_api.enviar_painel(painel)`, `tela_api.ler_eventos(desde)`, `tela_api.ler_motoboys()`.
  `python -m robo_rotas.tela_api exemplo` grava um painel de teste (pedidos e bairros inventados) e `limpar` apaga.
- Banco: SQLite num arquivo só. Só biblioteca padrão do Python.

Testado no PC em 16/11 (`python -m unittest discover -s robo_rotas/testes -t .`, 19 testes): login, painel do
robô aparecendo sem recarregar, as cinco abas, mapa com o fundo, cadastro de motoboy, toque de dois passos
("Tirar do turno") e o robô lendo esse toque.

**Subir na VPS:** criar o droplet (Ubuntu LTS, US$ 6, chave SSH, ver robo_notas/README.md) e rodar:

```
scp -r robo_rotas root@IP:/root/
ssh root@IP 'bash /root/robo_rotas/deploy/instalar.sh'
```

O instalador põe Python, Caddy (HTTPS automático) e o serviço `waisorio`, abre só as portas 22, 80 e 443, e gera
a senha da loja e a chave do robô **na própria VPS** (`/etc/waisorio.env`), mostrando as duas uma vez. Sem
domínio, o endereço é `https://IP-COM-TRAÇOS.sslip.io`. Rodar de novo atualiza o código e mantém senha e banco.

## Simulador de rotas (18/11)

`simulador.py` monta uma noite inventada em Itajubá e roda o robô minuto a minuto, com a mesma `regras.sugerir`
que vai para o servidor. `itajuba.py` tem a loja (Rua Antônio Simão Mauad, 596, pela nota fiscal; ponto
aproximado), o centro de 33 bairros (OpenStreetMap) com o peso de cada um pelas entregas do Cardápio Web, e o
ritmo de entregas por hora de cada dia da semana (`motoboys.json`). O endereço do pedido é inventado em volta do
centro do bairro; o robô decide pelo centro, o motoboy anda até o endereço.

```
python -m robo_rotas.simulador                                  # sexta, 18h à 1h, 4 motoboys, no terminal
python -m robo_rotas.simulador --dia sábado --motoboys 3 --max 3
python -m pipeline --rotas                                      # simulador-de-rotas.html na pasta da reunião
```

Jeitos comparados: um por saída, regras até 2, regras até 3, e "parecido com hoje" (espera juntar e sai com até
cinco, misturando; suposição a partir da fala do Ricardo). Duas variações só para medir custo: refazer tudo a cada
minuto (sem manter o motoboy avisado) e liberar a mistura de lanche com bebida.

**O pedido fica com o motoboy avisado quando chegou** (`sugerir(..., fixos=)`, o mesmo que o "fixar" da tela). Só
troca se o pedido está pronto, o motoboy dele está na rua e tem outro parado na loja sem nada. Sem isso o robô troca
o motoboy de 7 em cada 10 pedidos depois de avisar.

Conferência: o jeito parecido com o de hoje simulado dá 14 min do pronto à porta (mediana) e 20 min em 3 de cada 4;
o medido no Cardápio Web é 12 e 23. A velocidade de 25 km/h com a rua 1,35 vez a reta anda perto do real.

## Quantos motoboys por horário

`python -m pipeline --motoboys` (`pipeline/motoboys.py`) grava `motoboys-por-horario.html` na pasta da
reunião. Simulação do despacho, um pedido por saída: o menor número em que nenhum pronto espera mais de
10 min. 8 no pico (20h de sexta a domingo), 11 nos feriados de segunda. A volta de 20 min é suposição
até o centro de cada bairro entrar.

## O que trava, em ordem

1. **A tela na VPS.** Pronta em 16/11 (acima), testada no PC. Falta o droplet existir para rodar o instalador.
2. **Ler os pedidos sem navegador.** O agente do Ricardo lê o Gestor do iFood pelo Claude in Chrome, que
   não roda na VPS. Precisa das requisições de rede de cada plataforma (decisão de arquitetura 2):
   iFood primeiro (login por código no e-mail), depois Zé (senha e código do entregador), Cardápio Web,
   WhatsApp por último (junto com o atendente).
3. **Centro de cada bairro.** A tela já recebe `mapa.bairros` do agente do Ricardo: reaproveitar a mesma
   lista para a distância.
4. **Calibrar os parâmetros** com uma noite em modo sombra: o robô sugere, ninguém usa, e no fim comparamos
   com o que os motoboys fizeram.

Credencial de plataforma nunca no repositório: fica no `.env` da VPS, fora do git.
