"""Endereço e rota pelas ruas de Itajubá, sem chamar ninguém de fora.

Lê `dados/itajuba_ruas.json.gz` (OpenStreetMap, baixado por `mapa_dados.py`):
  - `Mapa.buscar("rua antonio si")` sugere ruas enquanto a pessoa digita, com o bairro de cada trecho;
  - `Mapa.localizar("Rua Antônio Simão Mauad, 596", bairro)` devolve o ponto da rua no bairro (o mapa não tem o
    número da casa: a precisão é a rua, uns 100 a 300 m), ou o ponto de um link de localização colado do WhatsApp
    ou do Google Maps;
  - `Mapa.km(a, b)` e `Mapa.caminho(a, b)`: distância e trajeto pelas ruas (menor caminho na malha; mão de direção
    não entra: moto, cidade pequena).
O endereço do cliente nunca sai do servidor.
"""
from __future__ import annotations

import difflib
import gzip
import json
import math
import re
import threading
import unicodedata
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree

ARQUIVO = Path(__file__).parent / "dados" / "itajuba_ruas.json.gz"
ABREV = {"r": "rua", "av": "avenida", "avn": "avenida", "tv": "travessa", "trav": "travessa", "pc": "praca",
         "pca": "praca", "pr": "praca", "al": "alameda", "rod": "rodovia", "estr": "estrada", "dr": "doutor",
         "dra": "doutora", "prof": "professor", "profa": "professora", "cel": "coronel", "cap": "capitao",
         "gal": "general", "gen": "general", "maj": "major", "pe": "padre", "sto": "santo", "sta": "santa",
         "s": "sao", "n": "nossa", "sra": "senhora", "nsa": "nossa", "eng": "engenheiro", "ver": "vereador",
         "dep": "deputado", "pres": "presidente", "mal": "marechal", "ten": "tenente", "lot": "loteamento",
         "jd": "jardim", "vl": "vila", "res": "residencial"}
TIPOS = {"rua", "avenida", "travessa", "praca", "alameda", "rodovia", "estrada", "beco", "largo", "via", "viela"}
COORD = re.compile(r"(-2[12]\.\d{3,})\s*,\s*(-4[45]\.\d{3,})")


def normal(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(ABREV.get(t, t) for t in s.split())


def _nucleo(nome_normal: str) -> str:
    """Sem o tipo da via e sem 'de/da/do': 'rua antonio simao mauad' -> 'antonio simao mauad'."""
    t = [x for x in nome_normal.split() if x not in ("de", "da", "do", "das", "dos", "e")]
    return " ".join(t[1:] if t and t[0] in TIPOS else t)


def _metros(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


class Mapa:
    def __init__(self, arquivo: Path = ARQUIVO):
        with gzip.open(arquivo, "rt", encoding="utf-8") as f:
            d = json.load(f)
        self.nos = np.array(d["nos"], dtype=float)
        self.bairros = {nome: (la, lo) for nome, la, lo in d["bairros"]}
        self._bairro_normal = {normal(n): n for n in self.bairros}
        ar = np.array(d["arestas"], dtype=float)
        n = len(self.nos)
        a, b, w = ar[:, 0].astype(int), ar[:, 1].astype(int), ar[:, 2]
        self.grafo = csr_matrix((np.r_[w, w], (np.r_[a, b], np.r_[b, a])), shape=(n, n))
        _, comp = connected_components(self.grafo, directed=False)
        maior = np.bincount(comp).argmax()
        self._ok = np.where(comp == maior)[0]            # só a malha principal: ponto solto não tem caminho
        self._cos = math.cos(math.radians(float(self.nos[:, 0].mean())))
        self._arvore = cKDTree(np.c_[self.nos[self._ok, 0], self.nos[self._ok, 1] * self._cos])
        self._trava = threading.Lock()
        self._cache: OrderedDict = OrderedDict()
        # ruas agrupadas por (nome, bairro): um ponto de referência por trecho de bairro
        grupos: dict = {}
        for nome, bairro, ids in d["ruas"]:
            grupos.setdefault((nome, bairro), []).extend(ids)
        self.ruas = []
        for (nome, bairro), ids in grupos.items():
            pts = self.nos[ids]
            centro = pts.mean(axis=0)
            ref = ids[int(np.argmin(((pts - centro) ** 2).sum(axis=1)))]
            nn = normal(nome)
            self.ruas.append({"rua": nome, "bairro": bairro, "lat": float(self.nos[ref, 0]), "lon": float(self.nos[ref, 1]),
                              "normal": nn, "nucleo": _nucleo(nn), "pontos": len(ids)})

    # ---------- bairro ----------
    def bairro_oficial(self, nome: str) -> str | None:
        """'Bps', 'Nossa Sra. Da Agonia', 'N. Sra. da Agonia' -> o nome do mapa. None se não parece com nenhum."""
        n = normal(nome)
        if not n:
            return None
        if n in self._bairro_normal:
            return self._bairro_normal[n]
        sem = re.sub(r"^(loteamento|jardim|vila|residencial|bairro) ", "", n)
        for chave, oficial in self._bairro_normal.items():
            if sem == re.sub(r"^(loteamento|jardim|vila|residencial|bairro) ", "", chave):
                return oficial
        perto = difflib.get_close_matches(n, list(self._bairro_normal), n=1, cutoff=0.78)
        return self._bairro_normal[perto[0]] if perto else None

    # ---------- endereço ----------
    @staticmethod
    def separar(texto: str) -> tuple[str, str | None]:
        """'Rua X, 596' -> ('Rua X', '596'). O número fica guardado para o motoboy; o mapa não usa."""
        m = re.search(r"[, ]\s*(?:n[ºo°]?\.?\s*)?(\d{1,5})\s*[a-zA-Z]?\s*(?:[,-].*)?$", texto.strip())
        if m and m.start() > 2:
            return texto[:m.start()].strip(" ,-"), m.group(1)
        return texto.strip(), None

    def buscar(self, texto: str, bairro: str | None = None, limite: int = 8) -> list[dict]:
        rua, _ = self.separar(texto)
        q = normal(rua)
        qn = _nucleo(q)
        if len(qn) < 2:
            return []
        toks = qn.split()
        b = self.bairro_oficial(bairro) if bairro else None
        achados = []
        for r in self.ruas:
            nt = r["nucleo"].split()
            if not all(any(w.startswith(t) for w in nt) for t in toks):
                continue
            nota = (r["nucleo"] == qn) * 3 + r["nucleo"].startswith(qn) * 2 + (r["normal"].startswith(q)) \
                + (b == r["bairro"]) * 4 + min(r["pontos"], 40) / 100 - len(nt) / 50
            achados.append((nota, r))
        achados.sort(key=lambda x: -x[0])
        return [{k: r[k] for k in ("rua", "bairro", "lat", "lon")} for _, r in achados[:limite]]

    def localizar(self, texto: str, bairro: str | None = None) -> dict | None:
        """Ponto do endereço: coordenada colada, ou rua no bairro. None se não achar."""
        texto = str(texto or "").strip()
        m = COORD.search(texto)
        if m:
            la, lo = float(m.group(1)), float(m.group(2))
            perto = min(self.bairros, key=lambda n: _metros((la, lo), self.bairros[n]))
            return {"lat": la, "lon": lo, "rua": None, "bairro": perto, "precisao": "ponto", "numero": None}
        if not texto:
            return None
        rua, numero = self.separar(texto)
        achados = self.buscar(rua, bairro, limite=1)
        if not achados:
            return None
        r = achados[0]
        return {**r, "precisao": "rua", "numero": numero}

    # ---------- rota ----------
    def no_proximo(self, p) -> int:
        _, i = self._arvore.query([p[0], p[1] * self._cos])
        return int(self._ok[i])

    def _de(self, origem: int):
        with self._trava:
            if origem in self._cache:
                self._cache.move_to_end(origem)
                return self._cache[origem]
        dist, pred = dijkstra(self.grafo, directed=False, indices=origem, return_predecessors=True)
        with self._trava:
            self._cache[origem] = (dist, pred)
            while len(self._cache) > 160:
                self._cache.popitem(last=False)
        return dist, pred

    def km(self, a, b) -> float:
        na, nb = self.no_proximo(a), self.no_proximo(b)
        d = self._de(na)[0][nb]
        if not np.isfinite(d):
            return _metros(a, b) * 1.35 / 1000
        return (d + _metros(a, self.nos[na]) + _metros(b, self.nos[nb])) / 1000

    def caminho(self, a, b, max_pontos: int = 60) -> list[list[float]]:
        na, nb = self.no_proximo(a), self.no_proximo(b)
        _, pred = self._de(na)
        cam, i = [], nb
        while i != na and i >= 0 and len(cam) < 5000:
            cam.append(i)
            i = pred[i]
        if i != na:
            return [list(a), list(b)]
        cam.append(na)
        pts = self.nos[cam[::-1]].tolist()
        if len(pts) > max_pontos:
            passo = math.ceil(len(pts) / max_pontos)
            pts = pts[::passo] + [pts[-1]]
        return [list(a)] + [[round(x, 5), round(y, 5)] for x, y in pts] + [list(b)]


@lru_cache(maxsize=1)
def carregar() -> Mapa | None:
    """O mapa, ou None se o arquivo não existe (aí tudo cai para o centro do bairro e linha reta)."""
    return Mapa() if ARQUIVO.exists() else None
