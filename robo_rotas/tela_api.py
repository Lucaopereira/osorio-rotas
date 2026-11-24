"""O lado do robô: grava o `painel/atual` na tela da VPS e lê os toques da loja.

    TELA_URL=https://...  ROBO_TOKEN=...  python -m robo_rotas.tela_api exemplo   # painel de teste, pedidos inventados
    python -m robo_rotas.tela_api eventos                                       # toques desde o último painel
    python -m robo_rotas.tela_api limpar                                        # tira o painel de teste

A chave do robô fica no `.env` da VPS, nunca no repositório.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime

from robo_rotas.regras import Motoboy, Pedido, para_tela, sugerir, sugestao_dos_cartoes


def _pede(metodo: str, caminho: str, corpo=None, url=None, token=None):
    url = (url or os.environ.get("TELA_URL") or "http://127.0.0.1:8080").rstrip("/")
    token = token or os.environ.get("ROBO_TOKEN")
    if not token:
        raise SystemExit("Falta ROBO_TOKEN no ambiente.")
    dados = None if corpo is None else json.dumps(corpo, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url + caminho, data=dados, method=metodo,
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


def enviar_painel(painel: dict, **kw):
    return _pede("PUT", "/api/painel/atual", painel, **kw)


def ler_eventos(desde: float = 0, **kw) -> list[dict]:
    return _pede("GET", f"/api/eventos?desde={desde}", **kw)["eventos"]


def ler_motoboys(**kw) -> list[dict]:
    return _pede("GET", "/api/motoboys", **kw)["motoboys"]


# ---------- painel de teste ----------
# Pedidos e lugares inventados: servem só para ver a tela funcionando na VPS. Nenhum é de cliente.
LOJA = (-22.4256, -45.4528)
LUGARES = {"Bairro A": (-22.4300, -45.4600), "Bairro B": (-22.4180, -45.4470), "Bairro C": (-22.4380, -45.4500),
           "Bairro D": (-22.4210, -45.4650), "Bairro E": (-22.4120, -45.4560)}
CANAIS = {"iFood-B": ("iFood Burguer", "iF"), "Ze": ("Zé Delivery", "Zé"), "iFood-M": ("Marmita", "MA")}


def painel_exemplo(agora: datetime | None = None) -> dict:
    agora = agora or datetime.now()
    hm = lambda m: datetime.fromtimestamp(agora.timestamp() + m * 60).strftime("%H:%M")
    brutos = [("t1", "iFood-B", "4821", "Bairro A", 0, 35, dict(comida=True)),
              ("t2", "Ze", "7710", "Bairro B", 0, 30, dict(gelado=True, peso=0.5)),
              ("t3", "iFood-B", "4825", "Bairro A", 4, 40, dict(comida=True)),
              ("t4", "Ze", "7713", "Bairro D", 0, 28, dict(gelado=True, pequeno=True, peso=0.1)),
              ("t5", "iFood-M", "0193", "Bairro C", 6, 45, dict(comida=True))]
    pedidos = []
    for ref, canal, num, bairro, pronto, prazo, kw in brutos:
        nome_canal, rotulo = CANAIS[canal]
        lat, lon = LUGARES[bairro]
        extra = {"canal": canal, "nome_canal": nome_canal, "rotulo": rotulo, "num": num, "num_ini": num[:-2],
                 "num_fim": num[-2:], "bairro": bairro, "bairro_ok": True, "prazo": hm(prazo), "lat": lat, "lon": lon}
        pedidos.append(Pedido(ref, lat, lon, pronto, prazo, extra=extra, **kw))
    motos = [Motoboy("Teste1", cor=0), Motoboy("Teste2", cor=1), Motoboy("Teste3", cor=2, livre_em=12)]
    saidas, sem = sugerir(pedidos, motos, LOJA)
    sug = sugestao_dos_cartoes(saidas, agora)
    quadro = []
    for p in pedidos:
        quadro.append({**p.extra, "ref": p.ref, "st": "producao" if p.pronto_em > 0 else "pronto",
                       "pronto_hora": hm(p.pronto_em), "pronto_real": p.pronto_em == 0, "gelado": p.gelado,
                       **({"sug": sug[p.ref]} if p.ref in sug else {})})
    lat, lon = LUGARES["Bairro E"]
    rua = [{"moto": "Teste3", "cor": 2, "saiu": hm(-8), "volta": hm(12), "pct": 40, "tarde": False,
            "paradas": [{"canal": "Ze", "rotulo": "Zé", "num_fim": "02", "bairro": "Bairro E", "lat": lat, "lon": lon,
                         "entregue": False}]}]
    return {
        "dia": agora.strftime("%Y-%m-%d"), "agora": agora.strftime("%H:%M"), "gerado": agora.strftime("%H:%M:%S"),
        "gerado_ms": int(agora.timestamp() * 1000), "eventos_ate": int(time.time() * 1000) - 1,
        "replay": True, "exemplo": "Teste da cópia na VPS: pedidos e bairros inventados. Nada aqui é de cliente.",
        "max_saida": 3, "esperando": len(pedidos), "na_loja": 2, "na_rua": 1,
        "motoboys": [{"nome": m.nome, "cor": m.cor, "onde": "rua" if m.livre_em else "loja",
                      **({"volta": hm(m.livre_em)} if m.livre_em else {})} for m in motos],
        "saidas": para_tela(saidas, motos, agora), "rua": rua, "quadro": quadro, "parceiras": [], "ze_sem_nome": [],
        "atencao": [f"{len(sem)} pedido(s) sem motoboy nesta rodada"] if sem else [],
        "mapa": {"loja": list(LOJA), "bairros": [[n, la, lo] for n, (la, lo) in LUGARES.items()]},
    }


def main(argv=sys.argv[1:]):
    cmd = argv[0] if argv else ""
    if cmd == "exemplo":
        enviar_painel(painel_exemplo())
        print("Painel de teste gravado.")
    elif cmd == "eventos":
        for e in ler_eventos(float(argv[1]) if len(argv) > 1 else 0):
            print(json.dumps(e, ensure_ascii=False))
    elif cmd == "limpar":
        _pede("DELETE", "/api/painel/atual")
        print("Painel apagado: a tela volta a esperar a primeira rodada.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
