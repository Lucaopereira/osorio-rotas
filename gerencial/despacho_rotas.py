"""Rotas do despacho no servidor gerencial: os dois modos (real e treino), busca de rua, cenários e planilhas."""
from __future__ import annotations

import csv
import io
import threading
import time

from flask import Response, jsonify, request, send_file

from robo_rotas import cenarios as cen_mod, despacho as D, mapa as mapa_mod
from robo_rotas.despacho import Despacho, ErroDespacho


def registrar(app, banco, papel, precisa, erro, json_corpo):
    despachos = {e: Despacho(banco, e) for e in D.ESPACOS}
    app.extensions["despachos"] = despachos
    trava = threading.Lock()   # uma ação de cada vez: dois toques ao mesmo tempo não dividem o mesmo pedido
    paginas = {}

    @app.get("/despacho")
    @app.get("/despacho/<any(real, treino):espaco>")
    def despacho_tela(espaco="real"):
        if (bloqueio := precisa("loja", "gestao")):
            return bloqueio
        if espaco not in paginas:
            from gerencial.despacho_pagina import pagina
            paginas[espaco] = pagina(espaco)
        return paginas[espaco]

    def _desp(espaco, funcao, so_treino=False):
        if papel() is None:
            return erro(401, "not_granted")
        if espaco not in despachos or (so_treino and espaco != "treino"):
            return erro(404, "not_found")
        try:
            with trava:
                volta = funcao(despachos[espaco])
                return jsonify(volta if isinstance(volta, dict) else despachos[espaco].estado())
        except ErroDespacho as e:
            return jsonify({"erro": str(e)}), 400

    E = "/api/despacho/<any(real, treino):espaco>"

    @app.get(E + "/estado")
    def d_estado(espaco):
        return _desp(espaco, lambda d: d.estado())

    @app.post(E + "/pedido")
    def d_pedido(espaco):
        c = json_corpo()
        if c is None:
            return erro(400, "json")
        num = lambda k: float(c[k]) if str(c.get(k) or "").replace(".", "", 1).isdigit() else None
        return _desp(espaco, lambda d: d.novo_pedido(c.get("canal"), c.get("num"), c.get("tipo"), c.get("endereco"),
                                                     c.get("bairro"), num("preparo_min"), num("prazo_min")))

    @app.post(E + "/simular")
    def d_simular(espaco):
        return _desp(espaco, lambda d: d.pedido_simulado(), so_treino=True)

    @app.post(E + "/<any(pronto, cancelar):acao>/<ref>")
    def d_pedido_acao(espaco, acao, ref):
        return _desp(espaco, lambda d: d.marcar_pronto(ref) if acao == "pronto" else d.cancelar(ref))

    @app.post(E + "/fixar/<ref>")
    def d_fixar(espaco, ref):
        c = json_corpo() or {}
        return _desp(espaco, lambda d: d.fixar(ref, c.get("moto") or None))

    @app.post(E + "/moto")
    def d_moto_novo(espaco):
        c = json_corpo() or {}
        return _desp(espaco, lambda d: d.novo_motoboy(str(c.get("nome") or "")))

    @app.post(E + "/moto/<id_>/<any(saiu, voltou, pausar, tirar):acao>")
    def d_moto(espaco, id_, acao):
        f = {"saiu": "saiu", "voltou": "voltou", "pausar": "pausar_motoboy", "tirar": "tirar_motoboy"}[acao]
        return _desp(espaco, lambda d: getattr(d, f)(id_))

    @app.post(E + "/relogio/<acao>")
    def d_relogio(espaco, acao):
        c = json_corpo() or {}
        acoes = {"avancar": lambda d: d.avancar(max(1, min(120, int(c.get("min") or 5)))),
                 "velocidade": lambda d: d.velocidade(int(c.get("vel") or 1)),
                 "pausar": lambda d: d.pausar(True), "tocar": lambda d: d.pausar(False),
                 "real": lambda d: d.relogio_real()}
        if acao not in acoes:
            return erro(404, "not_found")
        return _desp(espaco, acoes[acao], so_treino=True)

    @app.post(E + "/piloto")
    def d_piloto(espaco):
        c = json_corpo() or {}
        return _desp(espaco, lambda d: d.piloto(bool(c.get("ligado"))), so_treino=True)

    @app.post(E + "/limpar")
    def d_limpar(espaco):
        return _desp(espaco, lambda d: d.limpar(tudo=False))

    @app.get("/api/despacho/cenarios")
    def d_cenarios():
        if papel() is None:
            return erro(401, "not_granted")
        return jsonify({"cenarios": cen_mod.listar()})

    @app.post(E + "/cenario")
    def d_cenario(espaco):
        c = json_corpo() or {}
        try:
            cen = cen_mod.abrir(str(c.get("nome") or ""))
        except FileNotFoundError:
            return erro(404, "cenario")
        mot = c.get("motoboys")
        return _desp(espaco, lambda d: d.carregar_cenario(cen, int(mot) if str(mot or "").isdigit() else None,
                                                          piloto=bool(c.get("piloto", True))), so_treino=True)

    @app.post(E + "/importar")
    def d_importar(espaco):
        if papel() is None:
            return erro(401, "not_granted")
        f = request.files.get("arquivo")
        if not f:
            return jsonify({"erro": "Escolha a planilha."}), 400
        try:
            linhas = ler_planilha(f)
        except Exception as e:
            return jsonify({"erro": f"Não consegui ler a planilha ({type(e).__name__}). Use o modelo em .xlsx ou um .csv."}), 400
        cen, problemas = D.ler_planilha(linhas)
        if not cen:
            return jsonify({"erro": " ".join(problemas[:5])}), 400
        mot = request.form.get("motoboys")
        r = _desp(espaco, lambda d: d.carregar_cenario(cen, int(mot) if str(mot or "").isdigit() else None), so_treino=True)
        if isinstance(r, Response) and r.status_code == 200:
            dados = r.get_json()
            dados["importados"], dados["problemas"] = len(cen["pedidos"]), problemas
            return jsonify(dados)
        return r

    @app.get("/api/despacho/modelo.xlsx")
    def d_modelo():
        if papel() is None:
            return erro(401, "not_granted")
        return xlsx(modelo_planilha(), "modelo-pedidos.xlsx")

    @app.get(E + "/exportar.xlsx")
    def d_exportar(espaco):
        if papel() is None:
            return erro(401, "not_granted")
        with trava:
            linhas, resumo = despachos[espaco].exportar(), despachos[espaco].resumo()
        return xlsx(planilha_noite(linhas, resumo), f"noite-{espaco}-{time.strftime('%Y-%m-%d')}.xlsx")

    @app.get("/api/mapa/buscar")
    def mapa_buscar():
        if papel() is None:
            return erro(401, "not_granted")
        m = mapa_mod.carregar()
        q = str(request.args.get("q") or "")[:120]
        if not m or len(q.strip()) < 2:
            return jsonify({"ruas": []})
        if mapa_mod.COORD.search(q):
            return jsonify({"ruas": [], "ponto": m.localizar(q)})
        toks = mapa_mod.normal(q).split()
        bairros = [b for b in sorted(D.BAIRROS) if toks and all(any(w.startswith(t) for w in mapa_mod.normal(b).split()) for t in toks)]
        return jsonify({"ruas": m.buscar(q, request.args.get("bairro") or None), "bairros": bairros[:3]})


# ---------- planilhas ----------
def ler_planilha(arquivo) -> list[dict]:
    """Primeira aba do .xlsx (ou um .csv) em linhas cabeçalho -> valor."""
    nome = (arquivo.filename or "").lower()
    bruto = arquivo.read(3_000_000)
    if nome.endswith(".csv"):
        texto = bruto.decode("utf-8-sig", errors="replace")
        sep = ";" if texto.count(";") > texto.count(",") else ","
        return list(csv.DictReader(io.StringIO(texto), delimiter=sep))
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(bruto), read_only=True, data_only=True).worksheets[0]
    linhas = list(ws.iter_rows(values_only=True))
    cab = [str(c or "").strip() for c in linhas[0]]
    return [dict(zip(cab, l)) for l in linhas[1:]]


def xlsx(wb, nome):
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=nome,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _cabecalho(ws, larguras):
    from openpyxl.styles import Font, PatternFill
    for i, w in enumerate(larguras, start=1):
        c = ws.cell(row=1, column=i)
        c.font, c.fill = Font(bold=True), PatternFill("solid", fgColor="FBEDD2")
        ws.column_dimensions[c.column_letter].width = w
    ws.freeze_panes = "A2"


def modelo_planilha():
    """Planilha para preencher pedidos de treino, com lista suspensa de canal, tipo e bairro."""
    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    ws = wb.active
    ws.title = "Pedidos"
    ws.append(D.COLUNAS)
    for e in [("19:02", "iFood Burguer", "4821", "Rua Coronel Rennó, 210", "", "lanche", "", ""),
              ("19:03", "Zé", "7710", "Avenida BPS", "", "uma caixa de litrão", "", ""),
              ("19:05", "iFood Marmita", "0193", "", "Medicina", "marmita", "", ""),
              ("19:06", "WhatsApp", "", "Rua Antônio Simão Mauad, 1200", "Centro", "fardo ou garrafas", "5", "40")]:
        ws.append(list(e))
    _cabecalho(ws, [8, 16, 10, 38, 22, 22, 13, 11])
    listas = wb.create_sheet("Listas")
    for i, (titulo, valores) in enumerate([("Canal", D.CANAIS), ("Tipo", list(D.TIPOS)), ("Bairro", sorted(D.BAIRROS))], start=1):
        listas.cell(row=1, column=i, value=titulo)
        for j, v in enumerate(valores, start=2):
            listas.cell(row=j, column=i, value=v)
    for col, letra, n in (("B", "A", len(D.CANAIS)), ("F", "B", len(D.TIPOS)), ("E", "C", len(D.BAIRROS))):
        dv = DataValidation(type="list", formula1=f"=Listas!${letra}$2:${letra}${n + 1}", allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{col}2:{col}500")
    como = wb.create_sheet("Como preencher")
    for linha in ["Uma linha por pedido. Hora, Canal e Tipo são obrigatórios; Endereço ou Bairro, pelo menos um.",
                  "Hora: a hora em que o pedido chegou (19:05). O treino começa na primeira hora da planilha.",
                  "Endereço: rua e número (o mapa acha a rua), ou cole o link de localização do WhatsApp.",
                  "Bairro: se não souber a rua, ou para ajudar quando a mesma rua passa por mais de um bairro.",
                  "Cozinha e Prazo em minutos: em branco usa o padrão (lanche 18, marmita 15, bebida 5; prazo pelo canal).",
                  "Depois: no despacho, modo Treino, botão Importar planilha."]:
        como.append([linha])
    como.column_dimensions["A"].width = 110
    return wb


def planilha_noite(linhas, resumo):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Pedidos"
    if linhas:
        ws.append(list(linhas[0].keys()))
        for l in linhas:
            ws.append(list(l.values()))
        _cabecalho(ws, [8, 14, 9, 20, 34, 20, 11, 12, 8, 10, 8, 8, 9, 11, 9, 9, 10])
    r = wb.create_sheet("Resultado")
    rot = {"pedidos": "Pedidos", "entregues": "Entregues", "tempo_medio": "Tempo médio até a porta (min)",
           "atrasados": "Atrasados", "atrasados_pct": "Atrasados (%)", "frias": "Comida fria", "frias_pct": "Comida fria (%)",
           "espera_media": "Espera do pronto até sair (min)", "saidas": "Saídas", "por_saida": "Pedidos por saída",
           "km": "Km rodados"}
    for k, v in resumo.items():
        r.append([rot.get(k, k), v])
    r.column_dimensions["A"].width = 34
    return wb
