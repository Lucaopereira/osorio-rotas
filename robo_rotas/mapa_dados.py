"""Baixa as ruas e os bairros de Itajubá do OpenStreetMap, uma vez, e grava num arquivo local.

    python -m robo_rotas.mapa_dados          # grava robo_rotas/dados/itajuba_ruas.json.gz

Depois disso o servidor acha o endereço e calcula a rota pelas ruas sem chamar ninguém de fora: o endereço do
cliente nunca sai do servidor. Dados © colaboradores do OpenStreetMap, licença ODbL.
"""
from __future__ import annotations

import gzip
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ARQUIVO = Path(__file__).parent / "dados" / "itajuba_ruas.json.gz"
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter")
VIAS = ("trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|"
        "residential|living_street|road|service|pedestrian")
CONSULTA = f"""[out:json][timeout:180];
area["name"="Itajubá"]["boundary"="administrative"]["admin_level"="8"]->.a;
(way(area.a)["highway"~"^({VIAS})$"];);
out geom;
node(area.a)["place"~"^(suburb|neighbourhood|quarter)$"];
out;
"""


def _metros(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def baixar() -> dict:
    corpo = urllib.parse.urlencode({"data": CONSULTA}).encode()
    erro = None
    for url in OVERPASS:   # servidores públicos do OpenStreetMap: se um estiver ocupado, tenta o próximo
        try:
            req = urllib.request.Request(url, data=corpo, headers={"User-Agent": "mapa-rotas-itajuba/1.0"})
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read())
        except Exception as e:
            erro = e
            print(f"  {url}: {e}")
    raise SystemExit(f"Nenhum servidor do OpenStreetMap respondeu: {erro}")


def montar(bruto: dict) -> dict:
    nos, idx, arestas, ruas = [], {}, set(), []
    bairros = [(e["tags"]["name"], round(e["lat"], 6), round(e["lon"], 6)) for e in bruto["elements"]
               if e["type"] == "node" and e.get("tags", {}).get("name")]

    def no(osm_id, lat, lon):
        if osm_id not in idx:
            idx[osm_id] = len(nos)
            nos.append([round(lat, 6), round(lon, 6)])
        return idx[osm_id]

    for e in bruto["elements"]:
        if e["type"] != "way" or "geometry" not in e:
            continue
        ids = [no(n, g["lat"], g["lon"]) for n, g in zip(e["nodes"], e["geometry"])]
        for a, b in zip(ids, ids[1:]):
            if a != b:
                arestas.add((min(a, b), max(a, b)))
        nome = e.get("tags", {}).get("name")
        if nome and e["tags"].get("highway") != "service":
            meio = nos[ids[len(ids) // 2]]
            bairro = min(bairros, key=lambda b: _metros(meio, b[1:]))[0] if bairros else ""
            ruas.append([nome, bairro, ids])
    arestas = sorted(arestas)
    return {"fonte": "OpenStreetMap (ODbL)", "nos": nos,
            "arestas": [[a, b, round(_metros(nos[a], nos[b]), 1)] for a, b in arestas],
            "ruas": ruas, "bairros": bairros}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    dados = montar(baixar())
    ARQUIVO.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(ARQUIVO, "wt", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(dados['nos'])} pontos, {len(dados['arestas'])} trechos, {len(dados['ruas'])} ruas com nome, "
          f"{len(dados['bairros'])} bairros -> {ARQUIVO} ({ARQUIVO.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
