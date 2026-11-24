"""Regras de rota da reunião 13 (12/11/2026), em código e sem IA.

Entra: os pedidos que ainda estão na loja e os motoboys do turno. Sai: a sugestão de saída de cada
motoboy no formato que a tela Waisorio do Ricardo lê (`saidas[]` e o `sug` de cada cartão do quadro).

As regras, ditas pelo Ricardo na reunião (27:03 a 45:03):
  1. Um pedido por motoboy.
  2. Dois só se não houver motoboy parado (ou se o pedido ia atrasar esperando).
  3. Três só em último caso, com as paradas muito perto uma da outra.
  4. Não misturar bebida com lanche. Bebida pequena pode, no compartimento de cima (regra da tela, 14/11).
  5. Peso: duas caixas de litrão enchem a moto.
  6. Juntar não pode fazer o primeiro pedido da saída atrasar.

O robô só sugere. Quem põe o pedido na caixa do motoboy é a loja (Ricardo, 14/11).
Localização: o centro do bairro, nunca o endereço do cliente.
"""
from __future__ import annotations

import itertools
import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Parâmetros: tudo aqui, nada chumbado no meio da conta. Conferir com o Ricardo e os motoboys.
VEL_KMH = 25.0          # velocidade média de moto na cidade
FATOR_RUA = 1.35        # rua não é linha reta: distância real ≈ 1,35 × a reta
PARADA_MIN = 3          # entregar na porta, receber, voltar para a moto
PESO_MAX = 2.0          # em caixas de litrão (regra 5)
PERTO_KM = 0.8          # três paradas só se todas ficam a até 800 m uma da outra (regra 3)
ESPERA_MAX = 10         # o pedido pronto pode esperar até 10 min pelo próximo motoboy antes de juntar
PIORA_MAX = 12          # juntar não pode atrasar a chegada de um pedido em mais que 12 min
MAX_PARADAS = 3         # reunião: três só em último caso. O Lucas quer simular também com no máximo dois (18/11)


@dataclass
class Pedido:
    ref: str
    lat: float                # centro do bairro
    lon: float
    pronto_em: int            # minutos a partir de agora até ficar pronto (0 = pronto)
    prazo_em: int             # minutos a partir de agora até o prazo do canal
    comida: bool = False
    gelado: bool = False
    pequeno: bool = False     # bebida pequena (long neck, lata): vai em cima da bag
    peso: float = 0.0         # em caixas de litrão
    extra: dict = field(default_factory=dict)   # campos que a tela mostra (canal, rotulo, num_fim, bairro...)


@dataclass
class Motoboy:
    nome: str
    cor: int = 0
    livre_em: int = 0         # minutos até estar na loja (0 = está na loja)
    fora: bool = False        # "Não está na loja" na tela: fora da sugestão


_local = threading.local()


@contextmanager
def roteador(r):
    """Dentro do `with`, as distâncias saem pelas ruas de verdade (`mapa.Mapa`), só nesta thread."""
    antes = getattr(_local, "r", None)
    _local.r = r
    try:
        yield
    finally:
        _local.r = antes


def reta(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distância em linha reta, em km (haversine)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distância pela rua: a malha de ruas, se houver um roteador ligado; senão, a reta vezes o fator de rua."""
    r = getattr(_local, "r", None)
    if r is not None:
        return r.km(a, b)
    return reta(a, b) * FATOR_RUA


def minutos(dist_km: float) -> float:
    return dist_km / VEL_KMH * 60


def pode_juntar(grupo: list[Pedido], max_paradas: int = MAX_PARADAS, misturar: bool = False) -> bool:
    if len(grupo) > max_paradas:
        return False
    if sum(p.peso for p in grupo) > PESO_MAX:
        return False
    comida = any(p.comida for p in grupo)
    bebida_grande = any(not p.comida and not p.pequeno for p in grupo)
    if comida and bebida_grande and not misturar:     # regra 4 (`misturar` só para medir quanto ela custa)
        return False
    if len(grupo) == 3:                               # regra 3
        retas = [reta((a.lat, a.lon), (b.lat, b.lon)) for a, b in itertools.combinations(grupo, 2)]
        if max(retas) > PERTO_KM:
            return False
    return True


@dataclass
class Rota:
    paradas: list[Pedido]
    sai: float
    chega: list[float]
    volta: float

    @property
    def atrasos(self) -> list[float]:
        return [max(0.0, c - p.prazo_em) for c, p in zip(self.chega, self.paradas)]


def rota(grupo: list[Pedido], loja: tuple[float, float], livre_em: float) -> Rota:
    """Melhor ordem das paradas (até 3: testa todas), saindo quando o motoboy está livre e tudo pronto."""
    sai = max([livre_em] + [p.pronto_em for p in grupo])
    melhor = None
    for ordem in itertools.permutations(grupo):
        t, aqui, chega = sai, loja, []
        for p in ordem:
            t += minutos(km(aqui, (p.lat, p.lon))) + PARADA_MIN
            chega.append(t)
            aqui = (p.lat, p.lon)
        volta = t + minutos(km(aqui, loja))
        r = Rota(list(ordem), sai, chega, volta)
        nota = (round(sum(r.atrasos), 3), round(max(r.atrasos), 3), round(volta, 3))
        if melhor is None or nota < melhor[0]:
            melhor = (nota, r)
    return melhor[1]


def sugerir(pedidos: list[Pedido], motoboys: list[Motoboy], loja: tuple[float, float], max_paradas: int = MAX_PARADAS,
            fixos: dict[str, str] | None = None, misturar: bool = False):
    """Uma saída por motoboy nesta rodada. Devolve (saídas {nome: Rota}, pedidos sem motoboy).

    `fixos` ({pedido: motoboy}) é o que já foi combinado: a loja tocou "fixar" na tela, ou o robô avisou o motoboy
    quando o pedido chegou. Esses pedidos ficam com o motoboy deles e os outros se encaixam em volta.
    """
    motos = sorted((m for m in motoboys if not m.fora), key=lambda m: (m.livre_em, m.nome))
    nomes = {m.nome for m in motos}
    fixos = {r: n for r, n in (fixos or {}).items() if n in nomes}
    ida = lambda p: minutos(km(loja, (p.lat, p.lon))) + PARADA_MIN
    saidas: dict[str, list[Pedido]] = {}
    for p in sorted(pedidos, key=lambda p: p.ref):
        if p.ref in fixos:
            saidas.setdefault(fixos[p.ref], []).append(p)
    fila = sorted((p for p in pedidos if p.ref not in fixos), key=lambda p: (p.prazo_em - p.pronto_em - ida(p), p.ref))
    livre = {m.nome: m.livre_em for m in motos}
    sem = []
    for p in fila:
        vagos = [m for m in motos if m.nome not in saidas]
        # regra 1: motoboy parado (na loja quando o pedido fica pronto) leva sozinho
        parado = next((m for m in vagos if m.livre_em <= p.pronto_em), None)
        if parado:
            saidas[parado.nome] = [p]
            continue
        sozinho = vagos[0] if vagos else None
        r_so = rota([p], loja, sozinho.livre_em) if sozinho else None
        espera_longa = r_so is None or r_so.atrasos[0] > 0 or r_so.sai - p.pronto_em > ESPERA_MAX
        junto = None
        if espera_longa:
            # regras 2 e 3: juntar com uma saída já sugerida; dois antes de três
            opcoes = []
            for nome, grupo in saidas.items():
                g = grupo + [p]
                if not pode_juntar(g, max_paradas, misturar):
                    continue
                antes, depois = rota(grupo, loja, livre[nome]), rota(g, loja, livre[nome])
                chegada_antes = {q.ref: c for q, c in zip(antes.paradas, antes.chega)}
                piora = max(c - chegada_antes[q.ref] for q, c in zip(depois.paradas, depois.chega) if q.ref in chegada_antes)
                novos_atrasos = [a for q, a in zip(depois.paradas, depois.atrasos)
                                 if q.ref != p.ref and a > dict(zip([x.ref for x in antes.paradas], antes.atrasos))[q.ref]]
                if novos_atrasos or piora > PIORA_MAX:     # regra 6
                    continue
                opcoes.append((len(g), sum(depois.atrasos), depois.volta, nome))
            if opcoes:
                junto = min(opcoes)
        if junto and (r_so is None or junto[1] < sum(r_so.atrasos) or r_so.sai - p.pronto_em > ESPERA_MAX):
            saidas[junto[3]].append(p)
        elif sozinho:
            saidas[sozinho.nome] = [p]
        else:
            sem.append(p)
    return {n: rota(g, loja, livre[n]) for n, g in saidas.items()}, sem


def para_tela(saidas: dict[str, Rota], motoboys: list[Motoboy], agora: datetime) -> list[dict]:
    """`saidas[]` no formato da tela Waisorio: quando (agora, espera, depois), sai, livre, volta, min, paradas."""
    hm = lambda m: (agora + timedelta(minutes=round(m))).strftime("%H:%M")
    por_nome = {m.nome: m for m in motoboys}
    out = []
    for nome, r in saidas.items():
        m = por_nome[nome]
        quando = "depois" if m.livre_em > 0 else ("agora" if r.sai <= 0 else "espera")
        comida = any(p.comida for p in r.paradas)
        paradas = [{**p.extra, "ref": p.ref, "chega": hm(c), "atraso": round(a), "gelado": p.gelado, "pequeno": p.pequeno}
                   for p, c, a in zip(r.paradas, r.chega, r.atrasos)]
        out.append({"moto": nome, "cor": m.cor, "quando": quando, "sai": hm(r.sai), "livre": hm(m.livre_em),
                    "volta": hm(r.volta), "min": round(r.volta - r.sai),
                    "gelado_em_cima": comida and any(p.gelado for p in r.paradas), "paradas": paradas})
    ordem = {"agora": 0, "espera": 1, "depois": 2}
    return sorted(out, key=lambda s: (ordem[s["quando"]], s["sai"], s["moto"]))


def sugestao_dos_cartoes(saidas: dict[str, Rota], agora: datetime) -> dict[str, dict]:
    """O `sug` de cada cartão do quadro: {ref: {moto, sai, quando, ordem}}."""
    out = {}
    for nome, r in saidas.items():
        quando = "agora" if r.sai <= 0 else "depois"
        sai = (agora + timedelta(minutes=round(r.sai))).strftime("%H:%M")
        for i, p in enumerate(r.paradas, 1):
            out[p.ref] = {"moto": nome, "sai": sai, "quando": quando, "ordem": i}
    return out
