"""Simulador de rotas: uma noite inventada em Itajubá, com o robô decidindo a cada minuto.

    python -m robo_rotas.simulador                                   # sexta, 18h à 1h, 4 motoboys, no máximo 2 por saída
    python -m robo_rotas.simulador --dia sábado --motoboys 3 --max 3 --semente 7
    python -m robo_rotas.simulador --pagina simulador-de-rotas.html  # a página com o mapa e a noite passo a passo

Os pedidos são inventados: o ritmo por hora é o das entregas de verdade (05/10 a 08/11/2026), o bairro é sorteado
pela frequência real do Cardápio Web, e o endereço é um ponto qualquer em volta do centro do bairro. O robô decide
com o centro do bairro, como vai decidir de verdade (a tela nunca recebe o endereço do cliente); o motoboy anda até
o endereço inventado.

Quatro jeitos de despachar, rodados na mesma noite:
  um    um pedido por saída, sempre.
  dois  as regras da reunião de 12/11 com no máximo dois por saída (pedido do Lucas, 18/11).
  tres  as regras da reunião como foram ditas: três só em último caso, com as paradas a até 800 m.
  hoje  parecido com o que acontece hoje (suposição): o motoboy espera juntar o que fica pronto e sai com até
        cinco pedidos, misturando lanche e bebida.

As regras (um por motoboy parado, dois só sem ninguém parado, não misturar lanche com bebida grande, duas caixas de
litrão enchem a moto, juntar não atrasa o primeiro) moram em `regras.py`: o simulador usa a mesma função que o robô.
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import sys
from dataclasses import dataclass, field

from robo_rotas import itajuba, regras
from robo_rotas.regras import Motoboy, Pedido, km, minutos

# ---------- Suposições (nenhuma é medida, a não ser onde está escrito). Conferir com o Ricardo e os motoboys. ----------
PREPARO_COZINHA = (17, 4)   # min, média e desvio. A média é medida (Cardápio Web, pedido do iFood, criado a pronto)
PREPARO_ZE = (5, 1.5)       # separar a bebida do Zé: suposição, igual a `pipeline/motoboys.py`
PRAZO = {"iFood Burguer": 45, "iFood Marmita": 45, "Site": 50, "Zé": 35}   # min do pedido até a porta
TAMANHO_ZE = [  # (o que é, peso em caixas de litrão, vai em cima da bag, peso no sorteio)
    ("poucas latas", 0.1, True, 15),
    ("fardo ou garrafas", 0.5, False, 50),
    ("uma caixa de litrão", 1.0, False, 25),
    ("duas caixas de litrão", 2.0, False, 10),
]
PESO_COMIDA = 0.2
ESPALHA_KM = 0.3            # endereço inventado: desvio de 300 m em volta do centro do bairro
TRANSITO = 0.15             # cada trecho leva até 15% a menos ou a mais que a conta
FRIA_MIN = 25               # comida que passa mais de 25 min entre ficar pronta e chegar na porta: chega fria
HOJE_ESPERA = 8             # "hoje": sai quando o pedido pronto mais antigo espera 8 min, ou com 5 pedidos
HOJE_MAX = 5

POLITICAS = {  # chave: (nome na página, pedidos por saída, fica com quem foi avisado na chegada, mistura lanche e bebida)
    "um": ("Um por saída", 1, True, False),
    "dois": ("Regras, até 2", 2, True, False),
    "tres": ("Regras, até 3", 3, True, False),
    "hoje": ("Parecido com hoje", None, False, True),
    # só para medir o custo de duas escolhas: refazer tudo a cada minuto e liberar a mistura
    "dois_solto": ("Regras, até 2, refazendo tudo a cada minuto", 2, False, False),
    "dois_mistura": ("Regras, até 2, misturando lanche e bebida", 2, True, True),
}
ROTULO = {"iFood Burguer": "iF", "iFood Marmita": "MA", "Zé": "Zé", "Site": "SI"}


@dataclass
class PedidoSim:
    ref: str
    num: str
    canal: str
    criado: float             # minutos desde o começo da noite
    bairro: str
    lat: float                # endereço inventado (onde o motoboy vai)
    lon: float
    clat: float               # centro do bairro (o que o robô enxerga)
    clon: float
    comida: bool
    gelado: bool
    pequeno: bool
    peso: float
    tamanho: str
    pronto: float             # quando fica pronto de verdade
    previsto: float           # quando a cozinha diz que fica
    prazo: float
    sugestoes: list = field(default_factory=list)   # [(minuto, motoboy ou None)], só quando muda
    moto: str | None = None
    saiu: float | None = None
    chegou: float | None = None
    juntos: int = 0
    fixo: str | None = None   # o motoboy que foi avisado quando o pedido chegou
    trocas: int = 0           # quantas vezes o robô tirou o pedido de quem tinha sido avisado


@dataclass
class MotoSim:
    nome: str
    cor: int
    volta: float = 0.0        # quando chega na loja de verdade
    volta_prev: float = 0.0   # quando o robô acha que ele chega
    trechos: list = field(default_factory=list)     # (início, fim, lat0, lon0, lat1, lon1, ref)
    km: float = 0.0


@dataclass
class Noite:
    pedidos: list
    motos: list
    saidas: list              # {moto, sai, volta, refs}
    politica: str
    max_paradas: int | None


# ---------- os pedidos ----------
def horas(ini: int, fim: int) -> list[int]:
    """Horas do relógio da noite: `fim` pode passar de 24 (1h da manhã = 25)."""
    return [h % 24 for h in range(ini, fim)]


def gerar_pedidos(dia: str = "sexta", ini: int = 18, fim: int = 25, semente: int = 1, escala: float = 1.0) -> list[PedidoSim]:
    """Pedidos de uma noite: chegada aleatória no ritmo médio de cada hora desse dia da semana."""
    rnd = random.Random(f"pedidos-{dia}-{semente}")
    ritmo = itajuba.PEDIDOS_HORA[dia]
    canais, pesos_canal = zip(*itajuba.CANAIS.items())
    pesos_bairro = [b[3] for b in itajuba.BAIRROS]
    out = []
    for i, h in enumerate(horas(ini, fim)):
        taxa = ritmo.get(h, 0.0) * escala / 60
        if taxa <= 0:
            continue
        t = i * 60 + rnd.expovariate(taxa)
        while t < (i + 1) * 60:
            canal = rnd.choices(canais, pesos_canal)[0]
            nome, blat, blon, _ = rnd.choices(itajuba.BAIRROS, pesos_bairro)[0]
            lat = blat + rnd.gauss(0, ESPALHA_KM) / 111.0
            lon = blon + rnd.gauss(0, ESPALHA_KM) / (111.0 * math.cos(math.radians(blat)))
            comida = canal != "Zé"
            if comida:
                media, desvio = PREPARO_COZINHA
                tamanho, peso, pequeno = ("marmita" if canal == "iFood Marmita" else "lanche"), PESO_COMIDA, False
            else:
                media, desvio = PREPARO_ZE
                tamanho, peso, pequeno, _ = rnd.choices(TAMANHO_ZE, [x[3] for x in TAMANHO_ZE])[0]
            preparo = max(media * 0.4, rnd.gauss(media, desvio))
            out.append(PedidoSim(
                ref=f"p{len(out) + 1:03d}", num=f"{rnd.randrange(1000, 9999)}", canal=canal, criado=round(t, 2),
                bairro=nome, lat=lat, lon=lon, clat=blat, clon=blon, comida=comida, gelado=not comida,
                pequeno=pequeno, peso=peso, tamanho=tamanho, pronto=round(t + preparo, 2), previsto=round(t + media, 2),
                prazo=round(t + PRAZO[canal], 2)))
            t += rnd.expovariate(taxa)
    return out


def _copia(pedidos: list[PedidoSim]) -> list[PedidoSim]:
    return [PedidoSim(**{k: v for k, v in p.__dict__.items() if k not in ("sugestoes", "fixo", "trocas")}) for p in pedidos]


# ---------- a noite ----------
def _anota(p: PedidoSim, t: float, moto: str | None):
    if not p.sugestoes or p.sugestoes[-1][1] != moto:
        p.sugestoes.append((t, moto))


def _sair(t: float, m: MotoSim, grupo: list[PedidoSim], duracao_prev: float, fila: list, rnd, saidas: list):
    """O motoboy sai com o grupo, na ordem dada, e anda até cada endereço de verdade."""
    aqui, tt = itajuba.LOJA, t
    for p in grupo:
        d = km(aqui, (p.lat, p.lon))
        dur = minutos(d) * rnd.uniform(1 - TRANSITO, 1 + TRANSITO)
        m.trechos.append((tt, tt + dur, aqui[0], aqui[1], p.lat, p.lon, p.ref))
        tt += dur
        p.moto, p.saiu, p.chegou, p.juntos = m.nome, t, tt, len(grupo)
        m.trechos.append((tt, tt + regras.PARADA_MIN, p.lat, p.lon, p.lat, p.lon, p.ref))
        tt += regras.PARADA_MIN
        m.km += d
        aqui = (p.lat, p.lon)
        fila.remove(p)
    d = km(aqui, itajuba.LOJA)
    dur = minutos(d) * rnd.uniform(1 - TRANSITO, 1 + TRANSITO)
    m.trechos.append((tt, tt + dur, aqui[0], aqui[1], itajuba.LOJA[0], itajuba.LOJA[1], None))
    m.km += d
    m.volta, m.volta_prev = tt + dur, t + duracao_prev
    saidas.append({"moto": m.nome, "sai": t, "volta": m.volta, "refs": [p.ref for p in grupo]})


def _rodada_robo(t, fila, motos, rnd, saidas, max_paradas, fixar, misturar):
    """Uma rodada do robô: as regras sugerem, e sai quem está na loja com a saída pronta.

    Com `fixar`, o motoboy sugerido quando o pedido chega fica com ele. Só troca se o pedido já está pronto, o motoboy
    dele ainda está na rua e tem outro parado na loja sem nada para levar.
    """
    por_ref = {p.ref: p for p in fila}
    moto = {m.nome: m for m in motos}
    if fixar:
        ocupados = {p.fixo for p in fila if p.fixo}
        parado_sem_nada = any(m.volta <= t and m.nome not in ocupados for m in motos)
        for p in fila:
            if p.fixo and parado_sem_nada and t >= p.pronto and moto[p.fixo].volta > t:
                p.fixo, p.trocas = None, p.trocas + 1
    fixos = {p.ref: p.fixo for p in fila if p.fixo}
    vistos = [Pedido(p.ref, p.clat, p.clon, 0 if t >= p.pronto else max(1.0, p.previsto - t), p.prazo - t,
                     comida=p.comida, gelado=p.gelado, pequeno=p.pequeno, peso=p.peso) for p in fila]
    ms = [Motoboy(m.nome, m.cor, livre_em=0 if m.volta <= t else max(1.0, m.volta_prev - t)) for m in motos]
    sug, sem = regras.sugerir(vistos, ms, itajuba.LOJA, max_paradas, fixos, misturar)
    for nome, r in sug.items():
        for q in r.paradas:
            p = por_ref[q.ref]
            if not fixar and p.sugestoes and p.sugestoes[-1][1] not in (None, nome):
                p.trocas += 1
            _anota(p, t, nome)
            if fixar:
                p.fixo = nome
    for q in sem:
        _anota(por_ref[q.ref], t, None)
    for nome in sorted(sug):
        r, m = sug[nome], moto[nome]
        grupo = [por_ref[q.ref] for q in r.paradas]
        if m.volta > t or r.sai > 0 or any(t < p.pronto for p in grupo):
            continue
        _sair(t, m, grupo, r.volta - r.sai, fila, rnd, saidas)


def _rodada_hoje(t, fila, motos, rnd, saidas):
    """Suposição do jeito de hoje: espera juntar, leva até cinco, mistura tudo, rota pela parada mais perto."""
    prontos = sorted((p for p in fila if t >= p.pronto), key=lambda p: p.pronto)
    for m in sorted(motos, key=lambda m: (m.volta, m.nome)):
        if m.volta > t or not prontos:
            continue
        if len(prontos) < HOJE_MAX and t - prontos[0].pronto < HOJE_ESPERA:
            continue
        grupo, peso = [], 0.0
        for p in prontos:
            if len(grupo) < HOJE_MAX and peso + p.peso <= regras.PESO_MAX:
                grupo.append(p)
                peso += p.peso
        ordem, aqui, resto = [], itajuba.LOJA, list(grupo)
        while resto:
            p = min(resto, key=lambda q: km(aqui, (q.lat, q.lon)))
            ordem.append(p)
            resto.remove(p)
            aqui = (p.lat, p.lon)
        for p in ordem:
            _anota(p, t, m.nome)
        prev = regras.rota([Pedido(p.ref, p.clat, p.clon, 0, 0) for p in ordem], itajuba.LOJA, 0).volta
        _sair(t, m, ordem, prev, fila, rnd, saidas)
        prontos = [p for p in prontos if p not in grupo]


def simular(pedidos: list[PedidoSim], n_motos: int, politica: str = "dois", semente: int = 1) -> Noite:
    """A noite minuto a minuto. Os pedidos são copiados: a mesma lista serve para comparar os jeitos."""
    peds = sorted(_copia(pedidos), key=lambda p: p.criado)
    _, max_paradas, fixar, misturar = POLITICAS[politica]
    rnd = random.Random(f"transito-{semente}-{n_motos}-{politica}")
    motos = [MotoSim(f"Moto {i + 1}", i) for i in range(n_motos)]
    fila, saidas, k, t = [], [], 0, 0.0
    while k < len(peds) or fila:
        while k < len(peds) and peds[k].criado <= t:
            fila.append(peds[k])
            k += 1
        if fila:
            if politica == "hoje":
                _rodada_hoje(t, fila, motos, rnd, saidas)
            else:
                _rodada_robo(t, fila, motos, rnd, saidas, max_paradas, fixar, misturar)
        t += 1.0
        if t > 24 * 60:
            raise RuntimeError("a noite não termina: algum pedido nunca sai")
    return Noite(peds, motos, saidas, politica, max_paradas)


# ---------- o que mede ----------
def _pct(n, d):
    return 100.0 * n / d if d else 0.0


def resumo(noite: Noite) -> dict:
    P = noite.pedidos
    por_ref = {p.ref: p for p in P}
    total = [p.chegou - p.criado for p in P]
    comida = [p for p in P if p.comida]
    grande = lambda p: not p.comida and not p.pequeno
    mistura = sum(1 for s in noite.saidas
                  if any(por_ref[r].comida for r in s["refs"]) and any(grande(por_ref[r]) for r in s["refs"]))
    pesada = sum(1 for s in noite.saidas if sum(por_ref[r].peso for r in s["refs"]) > regras.PESO_MAX + 1e-9)
    tam = [len(s["refs"]) for s in noite.saidas]
    na_chegada = [p for p in P if p.sugestoes and p.sugestoes[0][1] and p.sugestoes[0][0] - p.criado < 1]
    primeiro = lambda p: next((m for _, m in p.sugestoes if m), None)
    return {
        "pedidos": len(P),
        "saidas": len(noite.saidas),
        "por_saida": statistics.mean(tam) if tam else 0,
        "pct_juntos": _pct(sum(1 for p in P if p.juntos >= 2), len(P)),
        "pct_tres_mais": _pct(sum(1 for p in P if p.juntos >= 3), len(P)),
        "tempo_medio": statistics.mean(total),
        "tempo_p90": sorted(total)[int(0.9 * (len(total) - 1))],
        "pct_atrasado": _pct(sum(1 for p in P if p.chegou > p.prazo), len(P)),
        "atraso_medio": statistics.mean([p.chegou - p.prazo for p in P if p.chegou > p.prazo] or [0]),
        "pct_fria": _pct(sum(1 for p in comida if p.chegou - p.pronto > FRIA_MIN), len(comida)),
        "espera_pronto": statistics.mean(p.saiu - p.pronto for p in P),
        "saidas_mistura": mistura,
        "saidas_pesadas": pesada,
        "km": sum(m.km for m in noite.motos),
        "pct_sugerido_na_chegada": _pct(len(na_chegada), len(P)),
        "pct_manteve_sugestao": _pct(sum(1 for p in P if primeiro(p) == p.moto), len(P)) if noite.politica != "hoje" else None,
        "trocas": sum(p.trocas for p in P),
        "ultima_entrega": max(p.chegou for p in P),
    }


def cenarios(dia="sexta", ini=18, fim=25, motos=(2, 3, 4, 5, 6, 8), sementes=range(1, 11), politicas=tuple(POLITICAS)):
    """Média de várias noites sorteadas para cada número de motoboys e cada jeito de despachar."""
    noites = {s: gerar_pedidos(dia, ini, fim, s) for s in sementes}
    out = {}
    for n in motos:
        for pol in politicas:
            rs = [resumo(simular(noites[s], n, pol, s)) for s in sementes]
            out[(n, pol)] = {k: (statistics.mean(r[k] for r in rs) if rs[0][k] is not None else None) for k in rs[0]}
    return out, noites


def _hm(ini: int, m: float) -> str:
    tot = int(round(ini * 60 + m)) % (24 * 60)
    return f"{tot // 60:02d}:{tot % 60:02d}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Simulador de rotas do Osório (pedidos inventados).")
    ap.add_argument("--dia", default="sexta", choices=list(itajuba.PEDIDOS_HORA))
    ap.add_argument("--ini", type=int, default=18, help="hora em que a noite começa")
    ap.add_argument("--fim", type=int, default=25, help="hora em que para de chegar pedido (25 = 1h)")
    ap.add_argument("--motoboys", type=int, default=4)
    ap.add_argument("--max", type=int, default=2, choices=(1, 2, 3), help="pedidos por saída nas regras")
    ap.add_argument("--semente", type=int, default=1, help="outra semente, outra noite")
    ap.add_argument("--pagina", help="grava a página com o mapa e a comparação neste caminho")
    ap.add_argument("--noites", type=int, default=10, help="noites sorteadas para a comparação da página")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.pagina:
        from robo_rotas.simulador_pagina import gravar
        print(f"Página gravada em {gravar(a.pagina, ini=a.ini, fim=a.fim, noites=a.noites)}")
        return
    peds = gerar_pedidos(a.dia, a.ini, a.fim, a.semente)
    pol = {1: "um", 2: "dois", 3: "tres"}[a.max]
    print(f"{a.dia}, {a.ini}h às {a.fim % 24}h, {len(peds)} pedidos inventados, {a.motoboys} motoboys, loja em {itajuba.LOJA_ENDERECO}\n")
    linhas = [("", "Tempo médio", "9 em 10 até", "Atrasados", "Comida fria", "Por saída", "Mistura", "km")]
    for chave in (pol, "hoje"):
        r = resumo(simular(peds, a.motoboys, chave, a.semente))
        linhas.append((POLITICAS[chave][0], f"{r['tempo_medio']:.0f} min", f"{r['tempo_p90']:.0f} min", f"{r['pct_atrasado']:.0f}%",
                       f"{r['pct_fria']:.0f}%", f"{r['por_saida']:.1f}", str(r["saidas_mistura"]), f"{r['km']:.0f}"))
    larg = [max(len(l[i]) for l in linhas) for i in range(len(linhas[0]))]
    for l in linhas:
        print("  ".join(c.ljust(w) for c, w in zip(l, larg)))
    noite = simular(peds, a.motoboys, pol, a.semente)
    r0 = resumo(noite)
    print(f"\nAvisado na chegada: {r0['pct_sugerido_na_chegada']:.0f}% dos pedidos; ficou com quem foi avisado: "
          f"{r0['pct_manteve_sugestao']:.0f}%.")
    print(f"\nAs primeiras saídas ({POLITICAS[pol][0]}):")
    por_ref = {p.ref: p for p in noite.pedidos}
    for s in noite.saidas[:12]:
        ps = [por_ref[r] for r in s["refs"]]
        desc = " + ".join(f"{ROTULO[p.canal]} {p.num} ({p.bairro}, {p.tamanho})" for p in ps)
        print(f"  {_hm(a.ini, s['sai'])} {s['moto']} sai com {desc}, volta {_hm(a.ini, s['volta'])}")


if __name__ == "__main__":
    main()
