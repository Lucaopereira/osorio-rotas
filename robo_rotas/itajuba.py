"""Itajubá para o simulador de rotas: a loja, os bairros onde o Osório entrega e o ritmo de pedidos.

Nada aqui é endereço de cliente. Os pontos são o centro de cada bairro, tirados do OpenStreetMap
(Nominatim, 18/11/2026). O peso de cada bairro é quantas entregas foram para ele no Cardápio Web
(2.243 pedidos de entrega, 18/07 a 08/11/2026, iFood Burguer, Marmita e site; o Zé não diz o bairro, e por
isso usa a mesma divisão).

O ritmo por hora é `pedidos_media` de `docs/dados/motoboys.json` (entregas da casa por hora, média de 05/10 a
08/11/2026, sem 12/10 e 02/11), copiado aqui para o robô rodar na VPS sem a pasta do pipeline.
"""

# Rua Antônio Simão Mauad, 596, Pinheirinho (endereço da nota fiscal de compra do Empório). O OpenStreetMap
# não tem o número: o ponto é a rua a uns 600 m da ponta do Centro, onde a numeração começa. APROXIMADO:
# trocar pelo `mapa.loja` da tela do Ricardo quando tivermos o número dele.
LOJA = (-22.4187, -45.4540)
LOJA_ENDERECO = "Rua Antônio Simão Mauad, 596, Pinheirinho"

# (bairro, lat, lon, entregas no Cardápio Web). Ficaram de fora 6 nomes que o mapa não achou ou que são
# ambíguos (Costa, Vila Isabel, Nossa Senhora do Carmo, Cantina, Califórnia, Moquém): 3% das entregas.
BAIRROS = [
    ("Centro", -22.42367, -45.45609, 344),
    ("Cruzeiro", -22.41870, -45.44437, 306),
    ("Pinheirinho", -22.41542, -45.45239, 274),
    ("Varginha", -22.42862, -45.44011, 234),
    ("N. Sra. da Agonia", -22.41429, -45.44348, 174),
    ("Boa Vista", -22.42176, -45.46518, 138),
    ("São Vicente", -22.43175, -45.45733, 88),
    ("Morro Chic", -22.41669, -45.45925, 85),
    ("Estiva", -22.42070, -45.44202, 82),
    ("Avenida", -22.42947, -45.46296, 65),
    ("Porto Velho", -22.42820, -45.45053, 47),
    ("Medicina", -22.43841, -45.45471, 44),
    ("Santo Antônio", -22.43474, -45.46504, 35),
    ("Oriente", -22.42264, -45.44836, 31),
    ("Vila Rubens", -22.41592, -45.46926, 30),
    ("Rebourgeon", -22.44879, -45.47536, 24),
    ("BPS", -22.41451, -45.45347, 23),
    ("Vila Poddis", -22.43153, -45.46734, 17),
    ("São Sebastião", -22.43165, -45.44246, 16),
    ("Santa Rita de Cássia", -22.43706, -45.43808, 15),
    ("Novo Horizonte", -22.41057, -45.47884, 14),
    ("N. Sra. de Fátima", -22.44201, -45.43726, 10),
    ("Santos Dumont", -22.42221, -45.48289, 10),
    ("Jardim Bernadete", -22.43925, -45.47215, 9),
    ("Água Preta", -22.41814, -45.47216, 9),
    ("Mário Anselmo", -22.41737, -45.44324, 9),
    ("São Judas Tadeu", -22.42431, -45.46971, 7),
    ("Anhumas", -22.44730, -45.45874, 5),
    ("Açude", -22.42235, -45.49764, 5),
    ("Piedade", -22.44577, -45.48655, 4),
    ("Santa Luzia", -22.43988, -45.46515, 3),
    ("Santa Rosa", -22.44930, -45.41986, 3),
    ("Distrito Industrial", -22.42645, -45.48185, 3),
]

# Entregas da casa por canal em 05/10 a 08/11 (motoboys.json, `por_canal`). iFood Bebidas fica de fora: quem
# entrega é o iFood.
CANAIS = {"Zé": 1767, "iFood Burguer": 960, "iFood Marmita": 765, "Site": 34}

# Entregas por hora, média do dia da semana (motoboys.json, `pedidos_media`). A chave é a hora do relógio.
PEDIDOS_HORA = {
    "segunda": {10: 0.0, 11: 2.0, 12: 3.7, 13: 2.7, 14: 2.7, 15: 0.3, 16: 1.3, 17: 2.7, 18: 6.7, 19: 9.3, 20: 10.3, 21: 9.0, 22: 9.0, 23: 6.3, 0: 0.0, 1: 0.0},
    "terça": {10: 1.0, 11: 4.6, 12: 5.2, 13: 2.8, 14: 1.8, 15: 0.2, 16: 2.0, 17: 2.0, 18: 4.8, 19: 10.2, 20: 11.8, 21: 8.6, 22: 7.0, 23: 3.8, 0: 0.0, 1: 0.0},
    "quarta": {10: 1.4, 11: 5.0, 12: 5.6, 13: 2.4, 14: 1.8, 15: 1.4, 16: 1.2, 17: 3.4, 18: 7.0, 19: 10.0, 20: 11.6, 21: 9.8, 22: 5.0, 23: 5.0, 0: 0.0, 1: 0.0},
    "quinta": {10: 0.2, 11: 5.4, 12: 4.6, 13: 2.6, 14: 2.4, 15: 1.6, 16: 2.2, 17: 5.0, 18: 12.0, 19: 12.0, 20: 14.2, 21: 11.8, 22: 8.2, 23: 8.6, 0: 0.2, 1: 0.0},
    "sexta": {10: 0.8, 11: 4.2, 12: 7.4, 13: 4.4, 14: 5.2, 15: 3.2, 16: 6.0, 17: 9.8, 18: 13.0, 19: 20.4, 20: 19.6, 21: 16.8, 22: 10.6, 23: 8.8, 0: 4.8, 1: 0.4},
    "sábado": {10: 0.8, 11: 10.8, 12: 10.8, 13: 10.0, 14: 10.6, 15: 5.4, 16: 6.0, 17: 8.0, 18: 14.0, 19: 16.0, 20: 22.2, 21: 16.0, 22: 8.0, 23: 9.0, 0: 4.8, 1: 0.0},
    "domingo": {10: 2.4, 11: 11.4, 12: 12.8, 13: 14.4, 14: 11.8, 15: 7.4, 16: 7.2, 17: 8.0, 18: 13.4, 19: 15.8, 20: 14.8, 21: 14.8, 22: 9.8, 23: 6.4, 0: 0.0, 1: 0.0},
}

# Medido no Cardápio Web (pedido do iFood, 03/10 a 08/11/2026, motoboys.json `tempos`): do pedido pronto até
# entregue, em minutos. Mediana e 3 em cada 4. Serve para conferir se o simulador anda na velocidade certa.
MEDIDO_PRONTO_PORTA = (12, 23)

# Fundo do mapa: a mesma imagem da tela do Ricardo (OpenStreetMap, zoom 14), com o canto em pixels do mundo.
FUNDO = {"arquivo": "itajuba_z14.png", "z": 14, "px0": 1566720, "py0": 2364416, "w": 1536, "h": 1536}
