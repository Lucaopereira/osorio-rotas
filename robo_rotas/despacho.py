"""Despacho em tempo real: o pedido chega, o robô escolhe o motoboy na hora, com as regras da reunião de 12/11.

Dois espaços que nunca se misturam, no mesmo banco SQLite (`servidor.Banco`):
  - "real": a noite de verdade, no relógio de verdade;
  - "treino": para testar e treinar a equipe. Tem relógio próprio (parar, acelerar 5x/10x/20x, adiantar), cenários
    (noites reais tiradas das bases, planilha importada, pedidos digitados) e piloto automático (o motoboy sai
    sozinho quando o robô manda sair).

O pedido entra com canal, número, tipo e o endereço: rua (com ou sem número), link de localização colado do
WhatsApp, ou só o bairro. O endereço é achado no mapa local de Itajubá (`mapa.py`, OpenStreetMap) e nunca sai do
servidor. A distância e o tempo são pelas ruas. As regras são as de `regras.sugerir`: um pedido por motoboy parado,
dois só sem ninguém parado, no máximo 2 por saída, lanche não vai com bebida grande, duas caixas de litrão enchem a
moto, e quem foi avisado fica com o pedido. A loja pode mudar o motoboy de qualquer pedido na mão.
"""
from __future__ import annotations

import random
import re
import secrets
import time
from datetime import datetime

from robo_rotas import itajuba, mapa, regras
from robo_rotas.regras import Motoboy, Pedido

MAX_POR_SAIDA = 2
PREPARO_MIN = {"lanche": 18, "marmita": 15, "bebida": 5}   # lanche e marmita: mediana do iFood no Cardápio Web
PRAZO_MIN = {"iFood Burguer": 45, "iFood Marmita": 45, "Zé": 35, "Site": 50, "WhatsApp": 50}
CANAIS = list(PRAZO_MIN)
TIPOS = {  # tipo: (comida, bebida pequena que vai em cima da bag, peso em caixas de litrão)
    "lanche": (True, False, 0.2),
    "marmita": (True, False, 0.2),
    "poucas latas": (False, True, 0.1),
    "fardo ou garrafas": (False, False, 0.5),
    "uma caixa de litrão": (False, False, 1.0),
    "duas caixas de litrão": (False, False, 2.0),
}
FRIA_MIN = 25                    # comida que leva mais de 25 min do pronto até a porta chega fria
ENTREGUE_NA_TELA_MIN = 40        # pedido entregue some da lista depois de 40 min (continua no resultado)
NOMES_TREINO = ["Alan", "Beto", "Caio", "Davi", "Enzo", "Fábio", "Gabi", "Hugo", "Ivo", "Juca"]
ESPACOS = ("real", "treino")


class ErroDespacho(ValueError):
    pass


def _bairros() -> dict:
    """Centro de cada bairro: os do mapa (OpenStreetMap) mais os do simulador que o mapa não tem (BPS, Água Preta)."""
    M = mapa.carregar()
    out = dict(M.bairros) if M else {}
    for nome, la, lo, _ in itajuba.BAIRROS:
        if not M or M.bairro_oficial(nome) is None:
            out[nome] = (la, lo)
    return out


BAIRROS = _bairros()


def bairro_valido(nome) -> str | None:
    if not nome:
        return None
    nome = str(nome).strip()
    if nome in BAIRROS:
        return nome
    M = mapa.carregar()
    b = M.bairro_oficial(nome) if M else None
    if b:
        return b
    tira = lambda x: re.sub(r"^(loteamento|jardim|vila|residencial|bairro) ", "", mapa.normal(x))
    n = tira(nome)
    return next((k for k in BAIRROS if tira(k) == n), None)


def _hm(ms):
    return time.strftime("%H:%M", time.localtime(ms / 1000)) if ms else None


class Despacho:
    def __init__(self, banco, espaco: str = "treino"):
        if espaco not in ESPACOS:
            raise ErroDespacho("Espaço desconhecido.")
        self.b, self.espaco = banco, espaco
        self.cP, self.cM, self.cR, self.cC, self.cS = (f"despacho.{espaco}.{x}" for x in
                                                        ("pedidos", "motos", "relogio", "cenario", "saidas"))
        self.mapa = mapa.carregar()

    # ---------- relógio ----------
    def _relogio(self) -> dict | None:
        return self.b.get(self.cR, "atual") if self.espaco == "treino" else None

    def agora(self) -> float:
        r = self._relogio()
        real = time.time() * 1000
        if not r:
            return real
        return r["virt0"] + (0 if r["pausado"] else (real - r["real0"]) * r["vel"])

    def _rebase(self, **mudou):
        if self.espaco != "treino":
            raise ErroDespacho("O relógio só muda no treino.")
        r = self._relogio() or {"vel": 1, "pausado": False, "ultimo": self.agora()}
        self.b.set(self.cR, "atual", {**r, "real0": time.time() * 1000, "virt0": self.agora(), **mudou})

    def avancar(self, minutos: float):
        self._rebase()
        r = self._relogio()
        self.b.set(self.cR, "atual", dict(r, virt0=r["virt0"] + minutos * 60000))

    def velocidade(self, vel: float):
        if vel not in (1, 5, 10, 20):
            raise ErroDespacho("Velocidade 1, 5, 10 ou 20.")
        self._rebase(vel=vel)

    def pausar(self, pausado: bool):
        self._rebase(pausado=bool(pausado))

    def relogio_real(self):
        self.b.delete(self.cR, "atual")

    # ---------- motoboys ----------
    def motos(self) -> dict:
        return {m["id"]: m["dados"] for m in self.b.lista(self.cM)}

    def novo_motoboy(self, nome: str):
        nome = (nome or "").strip()
        if not nome or len(nome) > 20 or " " in nome:
            raise ErroDespacho("Só o primeiro nome do motoboy.")
        motos = self.motos()
        if mapa.normal(nome) in motos:
            raise ErroDespacho("Esse motoboy já está no turno.")
        cores = {m.get("cor") for m in motos.values()}
        cor = next((c for c in range(8) if c not in cores), len(motos) % 8)
        self.b.set(self.cM, mapa.normal(nome), {"nome": nome, "cor": cor, "status": "loja", "volta_prev": None,
                                                 "saida": [], "entregas": 0})

    def tirar_motoboy(self, id_: str):
        m = self._moto(id_)
        if m["status"] == "rua":
            raise ErroDespacho("Ele está na rua: espere voltar.")
        self.b.delete(self.cM, id_)
        self._soltar_de(id_)

    def pausar_motoboy(self, id_: str):
        m = self._moto(id_)
        if m["status"] == "rua":
            raise ErroDespacho("Só dá para pausar quem está na loja.")
        self.b.set(self.cM, id_, dict(m, status="fora" if m["status"] == "loja" else "loja"))
        if m["status"] == "loja":
            self._soltar_de(id_)

    def _moto(self, id_):
        m = self.motos().get(id_)
        if not m:
            raise ErroDespacho("Motoboy não encontrado.")
        return m

    def _soltar_de(self, id_):
        for p in self._pedidos().values():
            if p.get("moto") == id_ and p["status"] in ("cozinha", "pronto"):
                self._grava(dict(p, moto=None, manual=False))

    # ---------- pedidos ----------
    def _pedidos(self) -> dict:
        return {p["id"]: p["dados"] for p in self.b.lista(self.cP)}

    def _grava(self, p: dict):
        self.b.set(self.cP, p["ref"], p)

    def localizar(self, endereco=None, bairro=None) -> dict:
        """Ponto do pedido: a rua (ou a coordenada colada) se achar, senão o centro do bairro."""
        b = bairro_valido(bairro) if bairro else None
        if bairro and not b:
            raise ErroDespacho(f"Bairro '{bairro}' não está no mapa de Itajubá.")
        endereco = str(endereco or "").strip()
        if endereco and self.mapa:
            achou = self.mapa.localizar(endereco, b)
            if achou:
                return {"lat": achou["lat"], "lon": achou["lon"], "bairro": b or achou["bairro"],
                        "rua": achou["rua"], "numero": achou["numero"], "precisao": achou["precisao"], "aviso": None}
        if b:
            la, lo = BAIRROS[b]
            aviso = "Não achei a rua no mapa: usei o centro do bairro." if endereco else None
            return {"lat": la, "lon": lo, "bairro": b, "rua": None, "numero": None, "precisao": "bairro", "aviso": aviso}
        if endereco:
            raise ErroDespacho("Não achei esse endereço. Escolha uma rua da lista ou informe o bairro.")
        raise ErroDespacho("Informe a rua ou o bairro.")

    def _criar(self, canal, num, tipo, endereco=None, bairro=None, preparo_min=None, prazo_min=None,
               criado=None, origem="loja", bairro_sorteado=False) -> tuple[dict, str | None]:
        if canal not in PRAZO_MIN:
            raise ErroDespacho("Canal desconhecido.")
        if tipo not in TIPOS:
            raise ErroDespacho("Tipo de pedido desconhecido.")
        loc = self.localizar(endereco, bairro)
        comida, pequeno, peso = TIPOS[tipo]
        num = "".join(ch for ch in str(num or "") if ch.isalnum())[:12] or str(random.randint(1000, 9999))
        prep = preparo_min if preparo_min not in (None, "") else PREPARO_MIN[tipo if comida else "bebida"]
        p = {"ref": "p" + secrets.token_hex(5), "num": num, "canal": canal, "tipo": tipo, "comida": comida,
             "gelado": not comida, "pequeno": pequeno, "peso": peso, "criado": criado or self.agora(),
             "preparo_min": float(prep), "prazo_min": float(prazo_min if prazo_min not in (None, "") else PRAZO_MIN[canal]),
             "endereco": endereco or None, **{k: loc[k] for k in ("lat", "lon", "bairro", "rua", "numero", "precisao")},
             "bairro_sorteado": bool(bairro_sorteado), "origem": origem, "pronto_marcado": None, "status": "cozinha",
             "moto": None, "manual": False, "saiu": None, "chega_prev": None, "entregue": None}
        self._grava(p)
        return p, loc["aviso"]

    def novo_pedido(self, canal, num, tipo, endereco=None, bairro=None, preparo_min=None, prazo_min=None) -> dict:
        p, aviso = self._criar(canal, num, tipo, endereco, bairro, preparo_min, prazo_min)
        est = self.estado()
        return {"pedido": next(x for x in est["pedidos"] if x["ref"] == p["ref"]), "aviso": aviso, "estado": est}

    def pedido_simulado(self, semente=None) -> dict:
        """Um pedido inventado (canal e bairro pela frequência real), para testar a tela."""
        if self.espaco != "treino":
            raise ErroDespacho("Pedido inventado só no treino.")
        rnd = random.Random(semente)
        canal = rnd.choices(list(itajuba.CANAIS), list(itajuba.CANAIS.values()))[0]
        bairro = bairro_valido(rnd.choices([b[0] for b in itajuba.BAIRROS], [b[3] for b in itajuba.BAIRROS])[0])
        tipo = (rnd.choices(["poucas latas", "fardo ou garrafas", "uma caixa de litrão", "duas caixas de litrão"],
                            [15, 50, 25, 10])[0] if canal == "Zé" else "marmita" if canal == "iFood Marmita" else "lanche")
        return self.novo_pedido(canal, str(rnd.randint(1000, 9999)), tipo, bairro=bairro)

    def marcar_pronto(self, ref: str):
        p = self._pedidos().get(ref)
        if not p or p["status"] not in ("cozinha", "pronto"):
            raise ErroDespacho("Pedido não está na cozinha.")
        if p["status"] == "cozinha":
            self._grava(dict(p, pronto_marcado=self.agora(), status="pronto"))

    def cancelar(self, ref: str):
        p = self._pedidos().get(ref)
        if not p or p["status"] == "rua":
            raise ErroDespacho("Pedido na rua não cancela por aqui.")
        self.b.delete(self.cP, ref)

    def fixar(self, ref: str, moto: str | None):
        """A loja escolhe o motoboy na mão (ou devolve para o robô com None)."""
        p = self._pedidos().get(ref)
        if not p or p["status"] not in ("cozinha", "pronto"):
            raise ErroDespacho("Só dá para trocar o motoboy de pedido que ainda não saiu.")
        if moto:
            m = self._moto(moto)
            if m["status"] == "fora":
                raise ErroDespacho("Esse motoboy está pausado.")
        self._grava(dict(p, moto=moto or None, manual=bool(moto)))

    def _pronto_em(self, p) -> float:
        return p.get("pronto_marcado") or p["criado"] + p["preparo_min"] * 60000

    # ---------- o que acontece sozinho ----------
    def _voltou(self, id_, m, agora):
        pedidos = self._pedidos()
        for ref in m.get("saida", []):
            p = pedidos.get(ref)
            if p and p["status"] == "rua":
                self._grava(dict(p, status="entregue", entregue=min(agora, p.get("chega_prev") or agora)))
        self.b.set(self.cM, id_, dict(m, status="loja", volta_prev=None, saida=[], pernas=[],
                                      entregas=m.get("entregas", 0) + len(m.get("saida", []))))

    def voltou(self, id_: str):
        m = self._moto(id_)
        if m["status"] != "rua":
            raise ErroDespacho("Esse motoboy não está na rua.")
        self._voltou(id_, m, self.agora())

    def _injetar(self, agora):
        c = self.b.get(self.cC, "atual")
        if not c:
            return
        i, mudou, fora = c["proximo"], False, list(c.get("fora", []))
        while i < len(c["pedidos"]) and c["inicio"] + c["pedidos"][i]["t"] * 60000 <= agora:
            q = c["pedidos"][i]
            try:
                self._criar(q["canal"], q.get("num"), q["tipo"], q.get("endereco"), q.get("bairro"), q.get("preparo"),
                            q.get("prazo"), criado=c["inicio"] + q["t"] * 60000, origem="cenario",
                            bairro_sorteado=q.get("bairro_sorteado", False))
            except ErroDespacho as e:     # não some calado: a tela mostra o que ficou de fora e por quê
                fora.append(f"{q['canal']} {q.get('num') or ''}: {e}")
            i, mudou = i + 1, True
        if mudou:
            self.b.set(self.cC, "atual", dict(c, proximo=i, fora=fora))

    def _atualiza(self, agora: float):
        for id_, m in self.motos().items():
            if m["status"] == "rua" and m.get("volta_prev") and agora >= m["volta_prev"]:
                self._voltou(id_, m, agora)
        self._injetar(agora)
        for p in self._pedidos().values():
            if p["status"] == "cozinha" and agora >= self._pronto_em(p):
                self._grava(dict(p, status="pronto", pronto_marcado=self._pronto_em(p)))
            elif p["status"] == "rua" and p.get("chega_prev") and agora >= p["chega_prev"]:
                self._grava(dict(p, status="entregue", entregue=p["chega_prev"]))

    # ---------- a rodada do robô ----------
    def _rodada(self, agora: float):
        pedidos = {r: p for r, p in self._pedidos().items() if p["status"] in ("cozinha", "pronto")}
        motos = self.motos()
        livres = [i for i, m in motos.items() if m["status"] == "loja" and not any(p.get("moto") == i for p in pedidos.values())]
        for p in pedidos.values():
            dono = motos.get(p.get("moto") or "")
            if not p.get("moto"):
                continue
            perdeu = dono is None or dono["status"] == "fora"
            robo_troca = not p.get("manual") and livres and p["status"] == "pronto" and dono["status"] == "rua"
            if perdeu or robo_troca:
                p.update(moto=None, manual=False)
                self._grava(p)
        vistos = [Pedido(p["ref"], p["lat"], p["lon"],
                         0 if agora >= self._pronto_em(p) else max(1.0, (self._pronto_em(p) - agora) / 60000),
                         (p["criado"] + p["prazo_min"] * 60000 - agora) / 60000,
                         comida=p["comida"], gelado=p["gelado"], pequeno=p["pequeno"], peso=p["peso"])
                  for p in pedidos.values()]
        ms = [Motoboy(i, m.get("cor", 0),
                      livre_em=0 if m["status"] == "loja" else max(1.0, ((m.get("volta_prev") or agora) - agora) / 60000),
                      fora=m["status"] == "fora") for i, m in motos.items()]
        fixos = {r: p["moto"] for r, p in pedidos.items() if p.get("moto")}
        with regras.roteador(self.mapa):
            sug, sem = regras.sugerir(vistos, ms, itajuba.LOJA, MAX_POR_SAIDA, fixos)
        for i, r in sug.items():
            for q in r.paradas:
                if pedidos[q.ref].get("moto") != i:
                    pedidos[q.ref]["moto"] = i
                    self._grava(pedidos[q.ref])
        return sug, [q.ref for q in sem]

    def _sair(self, id_, m, refs, agora):
        pedidos = self._pedidos()
        grupo = [pedidos[r] for r in refs]
        vistos = [Pedido(p["ref"], p["lat"], p["lon"], 0, (p["criado"] + p["prazo_min"] * 60000 - agora) / 60000)
                  for p in grupo]
        with regras.roteador(self.mapa):
            rota = regras.rota(vistos, itajuba.LOJA, 0)
            pontos = [itajuba.LOJA] + [(q.lat, q.lon) for q in rota.paradas] + [itajuba.LOJA]
            km = sum(regras.km(a, b) for a, b in zip(pontos, pontos[1:]))
        pernas, t, aqui = [], agora, itajuba.LOJA
        for q, c in zip(rota.paradas, rota.chega):
            chega = agora + c * 60000
            ida = chega - regras.PARADA_MIN * 60000
            pernas.append({"de": t, "ate": ida, "pts": self._caminho(aqui, (q.lat, q.lon))})
            pernas.append({"de": ida, "ate": chega, "pts": [[q.lat, q.lon]]})
            self._grava(dict(pedidos[q.ref], status="rua", moto=id_, saiu=agora, chega_prev=chega))
            t, aqui = chega, (q.lat, q.lon)
        volta = agora + rota.volta * 60000
        pernas.append({"de": t, "ate": volta, "pts": self._caminho(aqui, itajuba.LOJA)})
        self.b.set(self.cM, id_, dict(m, status="rua", saiu=agora, volta_prev=volta, saida=[q.ref for q in rota.paradas],
                                      pernas=pernas))
        self.b.set(self.cS, secrets.token_hex(5), {"moto": id_, "sai": agora, "volta": volta, "km": round(km, 2),
                                                   "refs": [q.ref for q in rota.paradas]})

    def _caminho(self, a, b):
        return self.mapa.caminho(a, b) if self.mapa else [list(a), list(b)]

    def saiu(self, id_: str):
        """O motoboy saiu com a saída que o robô montou para ele (só os pedidos já prontos)."""
        agora = self.agora()
        self._atualiza(agora)
        m = self._moto(id_)
        if m["status"] != "loja":
            raise ErroDespacho("Esse motoboy não está na loja.")
        sug, _ = self._rodada(agora)
        r = sug.get(id_)
        pedidos = self._pedidos()
        prontos = [q.ref for q in (r.paradas if r else []) if agora >= self._pronto_em(pedidos[q.ref])]
        if not prontos:
            raise ErroDespacho("Nada pronto para ele levar agora.")
        self._sair(id_, m, prontos, agora)

    def _piloto(self, agora, sug):
        c = self.b.get(self.cC, "atual")
        if self.espaco != "treino" or not c or not c.get("piloto"):
            return False
        motos, pedidos, saiu = self.motos(), self._pedidos(), False
        for i, r in sug.items():
            m = motos.get(i)
            if m and m["status"] == "loja" and r.sai <= 0 and all(agora >= self._pronto_em(pedidos[q.ref]) for q in r.paradas):
                self._sair(i, m, [q.ref for q in r.paradas], agora)
                saiu = True
        return saiu

    # ---------- cenários ----------
    def carregar_cenario(self, cen: dict, motoboys: int | None = None, piloto: bool = True):
        if self.espaco != "treino":
            raise ErroDespacho("Cenário só no treino.")
        if not cen.get("pedidos"):
            raise ErroDespacho("Cenário sem pedidos.")
        self.limpar(tudo=True)
        n = max(1, min(int(motoboys or cen.get("motoboys") or 3), len(NOMES_TREINO)))
        for nome in NOMES_TREINO[:n]:
            self.novo_motoboy(nome)
        hoje = datetime.now()
        hh, mm = (int(x) for x in str(cen.get("inicio") or "19:00").split(":")[:2])
        inicio = hoje.replace(hour=hh, minute=mm, second=0, microsecond=0).timestamp() * 1000
        self.b.set(self.cR, "atual", {"real0": time.time() * 1000, "virt0": inicio, "vel": 5, "pausado": True,
                                      "ultimo": inicio})
        pedidos = sorted(cen["pedidos"], key=lambda q: float(q["t"]))
        self.b.set(self.cC, "atual", {"nome": cen.get("nome"), "titulo": cen.get("titulo") or "Cenário",
                                      "descricao": cen.get("descricao", ""), "inicio": inicio, "pedidos": pedidos,
                                      "proximo": 0, "piloto": bool(piloto), "motoboys": n})

    def piloto(self, ligado: bool):
        c = self.b.get(self.cC, "atual") or {"nome": None, "titulo": "Pedidos digitados", "descricao": "", "inicio": self.agora(),
                                             "pedidos": [], "proximo": 0, "motoboys": len(self.motos())}
        self.b.set(self.cC, "atual", dict(c, piloto=bool(ligado)))

    def limpar(self, tudo: bool = False):
        """Encerra a noite: apaga pedidos e saídas, motoboys voltam para a loja (no treino, `tudo` tira os motoboys)."""
        for col in (self.cP, self.cS):
            for d in self.b.lista(col):
                self.b.delete(col, d["id"])
        self.b.delete(self.cC, "atual")
        for id_, m in self.motos().items():
            if tudo:
                self.b.delete(self.cM, id_)
            else:
                self.b.set(self.cM, id_, dict(m, status="loja", volta_prev=None, saida=[], pernas=[], entregas=0))

    # ---------- resultado ----------
    def resumo(self) -> dict:
        ps = list(self._pedidos().values())
        ent = [p for p in ps if p["status"] == "entregue" and p.get("entregue")]
        com = [p for p in ent if p["comida"]]
        saidas = [s["dados"] for s in self.b.lista(self.cS)]
        tempo = [(p["entregue"] - p["criado"]) / 60000 for p in ent]
        atras = [p for p in ent if p["entregue"] > p["criado"] + p["prazo_min"] * 60000]
        fria = [p for p in com if p["entregue"] - self._pronto_em(p) > FRIA_MIN * 60000]
        espera = [((p.get("saiu") or 0) - self._pronto_em(p)) / 60000 for p in ent if p.get("saiu")]
        media = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
        return {"pedidos": len(ps), "entregues": len(ent), "tempo_medio": media(tempo),
                "atrasados": len(atras), "atrasados_pct": round(100 * len(atras) / len(ent)) if ent else None,
                "frias": len(fria), "frias_pct": round(100 * len(fria) / len(com)) if com else None,
                "espera_media": media(espera), "saidas": len(saidas),
                "por_saida": round(sum(len(s["refs"]) for s in saidas) / len(saidas), 2) if saidas else None,
                "km": round(sum(s["km"] for s in saidas), 1)}

    def exportar(self) -> list[dict]:
        motos = self.motos()
        nome = lambda i: motos.get(i, {}).get("nome", i or "")
        linhas = []
        for p in sorted(self._pedidos().values(), key=lambda p: p["criado"]):
            ent = p.get("entregue")
            linhas.append({"Chegou": _hm(p["criado"]), "Canal": p["canal"], "Número": p["num"], "Tipo": p["tipo"],
                           "Endereço": p.get("endereco") or "", "Bairro": p["bairro"], "Achado pela": p["precisao"],
                           "Cozinha prevista (min)": p["preparo_min"], "Pronto": _hm(self._pronto_em(p)),
                           "Motoboy": nome(p.get("moto")), "Escolha": "loja" if p.get("manual") else "robô",
                           "Saiu": _hm(p.get("saiu")), "Entregue": _hm(ent),
                           "Tempo total (min)": round((ent - p["criado"]) / 60000) if ent else None,
                           "Prazo (min)": p["prazo_min"],
                           "Atraso (min)": max(0, round((ent - p["criado"]) / 60000 - p["prazo_min"])) if ent else None,
                           "Situação": p["status"]})
        return linhas

    # ---------- o que a tela mostra ----------
    def _passo(self, t):
        self._atualiza(t)
        sug, sem = self._rodada(t)
        if self._piloto(t, sug):
            sug, sem = self._rodada(t)
        return sug, sem

    def estado(self) -> dict:
        agora = self.agora()
        r = self._relogio()
        if r and r.get("ultimo") and r["ultimo"] < agora:
            # o relógio do treino pode pular minutos entre uma consulta e outra (acelerado ou adiantado): a noite anda
            # minuto a minuto por dentro, senão o motoboy só "sairia" no fim do pulo
            t, n = r["ultimo"], 0
            while t + 60000 < agora and n < 600:
                t += 60000
                n += 1
                self._passo(t)
        if r:
            self.b.set(self.cR, "atual", dict(self._relogio(), ultimo=agora))
        sug, sem = self._passo(agora)
        pedidos, motos = self._pedidos(), self.motos()
        saidas = {}
        for i, r in sug.items():
            pts = [itajuba.LOJA] + [(q.lat, q.lon) for q in r.paradas]
            saidas[i] = {"sai": _hm(agora + r.sai * 60000), "sai_ms": agora + r.sai * 60000,
                         "agora": r.sai <= 0 and motos[i]["status"] == "loja",
                         "volta": _hm(agora + r.volta * 60000), "paradas": [q.ref for q in r.paradas],
                         "chega": {q.ref: _hm(agora + c * 60000) for q, c in zip(r.paradas, r.chega)},
                         "atraso": {q.ref: round(a) for q, a in zip(r.paradas, r.atrasos)},
                         "trajeto": [pt for a, b in zip(pts, pts[1:]) for pt in self._caminho(a, b)]
                         if motos[i]["status"] == "loja" else []}
        lista = []
        for p in sorted(pedidos.values(), key=lambda p: p["criado"]):
            if p["status"] == "entregue" and agora - (p.get("entregue") or agora) > ENTREGUE_NA_TELA_MIN * 60000:
                continue
            s = saidas.get(p.get("moto") or "") if p["status"] in ("cozinha", "pronto") else None
            lista.append(dict(p, criado_hm=_hm(p["criado"]), prazo_ms=p["criado"] + p["prazo_min"] * 60000,
                              prazo_hm=_hm(p["criado"] + p["prazo_min"] * 60000), pronto_ms=self._pronto_em(p),
                              pronto_hm=_hm(self._pronto_em(p)), sai_hm=s["sai"] if s else None,
                              chega_hm=s["chega"].get(p["ref"]) if s else _hm(p.get("chega_prev") or p.get("entregue")),
                              atraso=s["atraso"].get(p["ref"]) if s else None,
                              junto=len(s["paradas"]) if s else None, sem_motoboy=p["ref"] in sem))
        r = self._relogio()
        c = self.b.get(self.cC, "atual")
        return {"espaco": self.espaco, "agora": agora, "agora_hm": _hm(agora),
                "relogio": {"vel": r["vel"], "pausado": r["pausado"]} if r else {"vel": 1, "pausado": False},
                "cenario": {"titulo": c["titulo"], "descricao": c.get("descricao", ""), "chegaram": c["proximo"],
                            "total": len(c["pedidos"]), "piloto": c.get("piloto", False), "fora": c.get("fora", []),
                            "fim": c["proximo"] >= len(c["pedidos"]) and not any(p["status"] != "entregue" for p in pedidos.values())}
                if c else None,
                "pedidos": lista, "saidas": saidas, "loja": list(itajuba.LOJA), "resumo": self.resumo(),
                "motos": [dict(m, id=i, volta_hm=_hm(m.get("volta_prev"))) for i, m in sorted(motos.items(), key=lambda x: x[1].get("cor", 0))],
                "max_por_saida": MAX_POR_SAIDA, "mapa_ruas": self.mapa is not None}


# ---------- planilha de pedidos (importar) ----------
_CANAL = {"ifood": "iFood Burguer", "ifood burguer": "iFood Burguer", "ifood burger": "iFood Burguer", "burguer": "iFood Burguer",
          "burger": "iFood Burguer", "marmita": "iFood Marmita", "ifood marmita": "iFood Marmita", "ze": "Zé",
          "ze delivery": "Zé", "site": "Site", "cardapio web": "Site", "whatsapp": "WhatsApp", "whats": "WhatsApp",
          "zap": "WhatsApp"}
_TIPO = {"lanche": "lanche", "hamburguer": "lanche", "burger": "lanche", "burguer": "lanche", "marmita": "marmita",
         "latas": "poucas latas", "lata": "poucas latas", "poucas latas": "poucas latas", "fardo": "fardo ou garrafas",
         "garrafa": "fardo ou garrafas", "garrafas": "fardo ou garrafas", "fardo ou garrafas": "fardo ou garrafas",
         "caixa": "uma caixa de litrao", "1 caixa": "uma caixa de litrao", "litrao": "uma caixa de litrao",
         "uma caixa de litrao": "uma caixa de litrao", "2 caixas": "duas caixas de litrao",
         "duas caixas": "duas caixas de litrao", "duas caixas de litrao": "duas caixas de litrao"}
COLUNAS = ["Hora", "Canal", "Número", "Endereço", "Bairro", "Tipo", "Cozinha (min)", "Prazo (min)"]


def _minutos(v) -> float | None:
    if v is None or str(v).strip() == "":
        return None
    if hasattr(v, "hour"):
        return v.hour * 60 + v.minute + getattr(v, "second", 0) / 60
    s = str(v).strip()
    for sep in (":", "h", "."):
        if sep in s:
            a, b = (s.split(sep) + ["0"])[:2]
            if a.strip().isdigit() and (b.strip()[:2] or "0").isdigit():
                return int(a) * 60 + int(b.strip()[:2] or 0)
    try:
        f = float(s.replace(",", "."))
        return f * 24 * 60 if f < 1 else f        # Excel guarda hora como fração do dia
    except ValueError:
        return None


def ler_planilha(linhas: list[dict]) -> tuple[dict, list[str]]:
    """Linhas (cabeçalho -> valor) viram um cenário. Devolve (cenário, problemas por linha)."""
    chave = {mapa.normal(c): c for c in (linhas[0].keys() if linhas else [])}
    col = lambda *nomes: next((chave[mapa.normal(n)] for n in nomes if mapa.normal(n) in chave), None)
    cH, cC, cN, cE, cB, cT, cP, cZ = (col("Hora", "Horário", "Chegou"), col("Canal"), col("Número", "Numero", "Pedido"),
                                      col("Endereço", "Endereco", "Rua"), col("Bairro"), col("Tipo", "O que é", "Categoria"),
                                      col("Cozinha (min)", "Cozinha", "Preparo"), col("Prazo (min)", "Prazo"))
    if not cH or not cC or not cT:
        return {}, ["A planilha precisa das colunas Hora, Canal e Tipo (baixe o modelo)."]
    ok, problemas = [], []
    for i, l in enumerate(linhas, start=2):
        if all(str(v or "").strip() == "" for v in l.values()):
            continue
        t = _minutos(l.get(cH))
        canal = _CANAL.get(mapa.normal(l.get(cC)))
        tipo = _TIPO.get(mapa.normal(l.get(cT)))
        tipo = next((k for k in TIPOS if mapa.normal(k) == tipo), None) if tipo else None
        end = str(l.get(cE) or "").strip() if cE else ""
        bairro = str(l.get(cB) or "").strip() if cB else ""
        erro = ("hora" if t is None else "canal" if not canal else "tipo" if not tipo
                else "endereço ou bairro" if not end and not bairro else None)
        if bairro and not bairro_valido(bairro):
            erro = erro or f"bairro '{bairro}' não está no mapa"
        if erro:
            problemas.append(f"Linha {i}: {erro}.")
            continue
        prep = l.get(cP) if cP else None
        ok.append({"t": t, "canal": canal, "num": str(l.get(cN) or "").split(".")[0] if cN else "", "tipo": tipo,
                   "endereco": end or None, "bairro": bairro_valido(bairro) if bairro else None,
                   **({"preparo": float(str(prep).replace(",", "."))} if str(prep or "").strip() else {}),
                   **({"prazo": float(str(l.get(cZ)).replace(",", "."))} if cZ and str(l.get(cZ) or "").strip() else {})})
    if not ok:
        return {}, problemas or ["Nenhum pedido na planilha."]
    t0 = min(q["t"] for q in ok)
    for q in ok:
        q["t"] = round(q["t"] - t0, 1)
    return {"nome": "planilha", "titulo": f"Planilha importada ({len(ok)} pedidos)",
            "descricao": "Pedidos da planilha, na hora de cada linha.", "inicio": f"{int(t0 // 60) % 24:02d}:{int(t0 % 60):02d}",
            "pedidos": ok}, problemas
