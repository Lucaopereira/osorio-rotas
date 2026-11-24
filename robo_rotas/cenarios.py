"""Cenários de treino para o despacho: noites reais tiradas das bases, e um teste rápido feito à mão.

    python -m robo_rotas.cenarios          # grava robo_rotas/cenarios/*.json (roda no PC, lê C:/tmp_pr)

Cada pedido de uma noite real tem a hora em que chegou de verdade e o canal de verdade. O resto:
  - iFood Burguer e Marmita entregues pela casa: bairro e tempo de cozinha do Cardápio Web (o pedido do iFood casa
    com o Cardápio Web pelo número curto, desde 03/10);
  - site (Cardápio Web): bairro de verdade;
  - Zé: o relatório não diz o bairro, então ele é sorteado pela frequência real de entrega (marcado); o tamanho sai
    do valor do pedido (até R$ 40 poucas latas, até R$ 120 fardo, até R$ 220 uma caixa de litrão, acima duas).
Nenhum dado de cliente: só hora, canal, número do pedido, bairro e tipo. Rua não entra.
O número de motoboys sugerido é o de pessoas diferentes que entregaram pedido do Zé naquela noite (mínimo 3).
"""
from __future__ import annotations

import json
import random
import sys
from datetime import timedelta
from pathlib import Path

PASTA = Path(__file__).parent / "cenarios"
JANELA = (17, 26)        # 17h até 2h do dia seguinte

TESTE_RAPIDO = {
    "nome": "teste-rapido",
    "titulo": "Teste rápido: 3 motoboys, 4 pedidos de uma vez",
    "descricao": "Quatro pedidos chegam juntos em ruas de bairros diferentes, com 3 motoboys na loja. "
                 "Serve para ver a regra de um pedido por motoboy e quem fica esperando.",
    "motoboys": 3,
    "pedidos": [
        {"t": 0, "canal": "iFood Burguer", "num": "4821", "endereco": "Rua Coronel Rennó", "tipo": "lanche"},
        {"t": 0, "canal": "Zé", "num": "7710", "endereco": "Avenida BPS", "tipo": "uma caixa de litrão"},
        {"t": 1, "canal": "iFood Marmita", "num": "0193", "endereco": "Rua Vereador José Lino da Costa", "tipo": "marmita"},
        {"t": 2, "canal": "Zé", "num": "7713", "endereco": "Rua Antônio Simão Mauad", "bairro": "Centro", "tipo": "poucas latas"},
    ],
}


def _tipo_ze(valor: float) -> str:
    return ("poucas latas" if valor <= 40 else "fardo ou garrafas" if valor <= 120
            else "uma caixa de litrão" if valor <= 220 else "duas caixas de litrão")


def gerar(noites: int = 4) -> list[Path]:
    import pandas as pd
    from pipeline import motoboys as MB, util as u
    from pipeline.config import BASES
    from robo_rotas import itajuba, mapa

    M = mapa.carregar()
    oficial = lambda b: (M.bairro_oficial(b) if M else None) or str(b).strip().title()

    # Cardápio Web: bairro e tempo de cozinha
    cw = []
    for p in MB._todos("CARDÁPIO WEB/PEDIDOS 2026"):
        d = pd.read_excel(p)
        d["loja"] = "iFood Marmita" if "Marmita" in p else "iFood Burguer"
        cw.append(d)
    cw = pd.concat(cw, ignore_index=True).drop_duplicates("Id do pedido")
    cw = cw[cw["Tipo"] == "Delivery"].copy()
    for c in ("Data de criação", "Pedido pronto"):
        cw[c] = pd.to_datetime(cw[c], errors="coerce")
    cw["prep"] = (cw["Pedido pronto"] - cw["Data de criação"]).dt.total_seconds() / 60
    cw["curto"] = pd.to_numeric(cw["Código externo do pedido"], errors="coerce").astype("Int64").astype(str)
    cw["dia"] = cw["Data de criação"].dt.date

    # iFood entregue pela casa, com o número curto
    ifd = []
    for loja in ("BURGUER", "MARMITA"):
        for p in MB._todos(f"IFOOD/{loja}/PEDIDOS 2026"):
            d = u.ler_com_cabecalho(p, 0)
            if "ID CURTO DO PEDIDO" not in d.columns or "PRODUTO LOGISTICO" not in d.columns:
                continue
            d["canal"] = f"iFood {loja.title()}"
            ifd.append(d)
    ifd = pd.concat(ifd, ignore_index=True).drop_duplicates("ID COMPLETO DO PEDIDO")
    ifd["dt"] = pd.to_datetime(ifd["DATA E HORA DO PEDIDO"], dayfirst=True, errors="coerce")
    ifd = ifd[(ifd["TIPO DE ENTREGA"] == "ENTREGA") & ~ifd["PRODUTO LOGISTICO"].isin(MB.IFOOD_LOGISTICA_IFOOD)
              & (ifd["STATUS FINAL DO PEDIDO"] != "CANCELADO")].copy()
    ifd["curto"] = pd.to_numeric(ifd["ID CURTO DO PEDIDO"].astype(str).str.extract(r"(\d+)")[0], errors="coerce") \
        .astype("Int64").astype(str)
    ifd["dia"] = ifd["dt"].dt.date
    ifd = ifd.merge(cw[["loja", "curto", "dia", "Bairro", "prep"]].rename(columns={"loja": "canal"}),
                    on=["canal", "curto", "dia"], how="left")

    site = cw[cw["Canal"] == "Site"].rename(columns={"Data de criação": "dt"})

    # Zé: hora, valor, quem entregou
    ze = MB._ze()
    ze_ids = []
    for p in MB._todos("ZÉ DELIVERY/RELATÓRIO GERAL DE VENDAS 2026"):
        d = u.ler_com_cabecalho(p, 0)
        ze_ids.append(d)
    ze = pd.concat(ze_ids, ignore_index=True).drop_duplicates("No. do Pedido")
    ze["dt"] = pd.to_datetime(ze["Data do Pedido"].astype(str) + " " + ze["Horário do Pedido"].astype(str),
                              dayfirst=True, errors="coerce")
    ze = ze[ze["Categoria de Entrega"].astype(str).str.strip() == "Entrega"].copy()
    ze["pedido"] = ze["No. do Pedido"].astype(str)
    valores = []
    for p in MB._todos("ZÉ DELIVERY/PEDIDOS ENTREGUES 2026"):
        r = pd.read_excel(p, header=None)
        cab = r.index[r.iloc[:, 2].astype(str).str.strip() == "Data do pedido"]
        if not len(cab):
            continue
        d = r.iloc[cab[0] + 1:].copy()
        d.columns = [str(c).strip() for c in r.iloc[cab[0]]]
        d = d.loc[:, ~d.columns.duplicated()]
        if "Sub-total (R$)" in d.columns:
            valores.append(pd.DataFrame({"pedido": d["Pedido"].astype(str), "valor": pd.to_numeric(d["Sub-total (R$)"], errors="coerce")}))
    if valores:
        ze = ze.merge(pd.concat(valores).drop_duplicates("pedido"), on="pedido", how="left")
    else:
        ze["valor"] = None
    quem = MB._ze_quem_entregou()

    pesos = {}
    for nome, _, _, n in itajuba.BAIRROS:
        pesos[oficial(nome)] = pesos.get(oficial(nome), 0) + n

    # noites: as de mais entregas entre as semanas com Cardápio Web completo (sexta, sábado, terça, domingo)
    todos = pd.concat([ifd[["dt"]], site[["dt"]], ze[["dt"]]]).dropna()
    todos["noite"] = (todos["dt"] - pd.Timedelta(hours=6)).dt.date
    todos = todos[todos["dt"] >= pd.Timestamp("2026-10-05")]
    por_noite = todos.groupby("noite").size()
    nomes_dia = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    escolha = []
    for dia_semana in (4, 5, 1, 6):
        cands = por_noite[[n.weekday() == dia_semana for n in por_noite.index]]
        if len(cands):
            escolha.append(cands.idxmax() if dia_semana in (4, 5) else cands.index[(cands - cands.median()).abs().argmin()])
    escolha = escolha[:noites]

    saidas = []
    PASTA.mkdir(exist_ok=True)
    for noite in escolha:
        ini = pd.Timestamp(noite) + pd.Timedelta(hours=JANELA[0])
        fim = pd.Timestamp(noite) + pd.Timedelta(hours=JANELA[1])
        rnd = random.Random(str(noite))
        ped = []
        for _, r in ifd[(ifd["dt"] >= ini) & (ifd["dt"] < fim)].iterrows():
            b = oficial(r["Bairro"]) if isinstance(r["Bairro"], str) else None
            prep = r["prep"] if pd.notna(r["prep"]) and 3 <= r["prep"] <= 60 else None
            ped.append({"dt": r["dt"], "canal": r["canal"], "num": str(r["curto"])[-4:],
                        "bairro": b or rnd.choices(list(pesos), list(pesos.values()))[0], "bairro_sorteado": b is None,
                        "tipo": "marmita" if r["canal"] == "iFood Marmita" else "lanche",
                        **({"preparo": round(float(prep), 1)} if prep else {})})
        for _, r in site[(site["dt"] >= ini) & (site["dt"] < fim)].iterrows():
            ped.append({"dt": r["dt"], "canal": "Site", "num": str(r["Número do pedido"]), "bairro": oficial(r["Bairro"]),
                        "bairro_sorteado": False, "tipo": "marmita" if r["loja"] == "iFood Marmita" else "lanche"})
        for _, r in ze[(ze["dt"] >= ini) & (ze["dt"] < fim)].iterrows():
            v = r.get("valor")
            ped.append({"dt": r["dt"], "canal": "Zé", "num": str(r["pedido"])[-4:],
                        "bairro": rnd.choices(list(pesos), list(pesos.values()))[0], "bairro_sorteado": True,
                        "tipo": _tipo_ze(float(v)) if pd.notna(v) else "fardo ou garrafas"})
        if not ped:
            continue
        ped.sort(key=lambda p: p["dt"])
        t0 = ped[0]["dt"]
        q = quem[(quem["dt"] >= ini) & (quem["dt"] < fim)]["quem"].dropna().nunique() if len(quem) else 0
        nome_dia = nomes_dia[pd.Timestamp(noite).weekday()]
        cen = {
            "nome": f"noite-{noite:%Y-%m-%d}",
            "titulo": f"Noite real: {nome_dia} {noite:%d/%m} ({len(ped)} entregas)",
            "descricao": (f"Os pedidos de entrega da casa de {nome_dia}, {noite:%d/%m/%Y}, na hora em que chegaram. "
                          f"Naquela noite {q} pessoas diferentes entregaram pedido do Zé. "
                          f"Bairro do Zé sorteado pela frequência real (o relatório dele não diz o bairro)."),
            "motoboys": max(3, int(q)),
            "inicio": f"{t0:%H:%M}",
            "pedidos": [{"t": round((p["dt"] - t0).total_seconds() / 60, 1), **{k: v for k, v in p.items() if k != "dt"}}
                        for p in ped],
        }
        arq = PASTA / f"{cen['nome']}.json"
        arq.write_text(json.dumps(cen, ensure_ascii=False, indent=1), encoding="utf-8")
        saidas.append(arq)
        print(f"  {cen['titulo']}, {cen['motoboys']} motoboys, bairro real em "
              f"{sum(not p['bairro_sorteado'] for p in ped)} de {len(ped)}")
    arq = PASTA / "teste-rapido.json"
    arq.write_text(json.dumps(TESTE_RAPIDO, ensure_ascii=False, indent=1), encoding="utf-8")
    saidas.append(arq)
    return saidas


def listar() -> list[dict]:
    out = []
    for p in sorted(PASTA.glob("*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        out.append({"nome": c["nome"], "titulo": c["titulo"], "descricao": c.get("descricao", ""),
                    "motoboys": c.get("motoboys", 3), "pedidos": len(c["pedidos"])})
    return sorted(out, key=lambda c: (c["nome"] != "teste-rapido", c["nome"]))


def abrir(nome: str) -> dict:
    p = PASTA / f"{nome}.json"
    if not p.exists() or p.parent != PASTA:
        raise FileNotFoundError(nome)
    return json.loads(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for p in gerar():
        print(p)
