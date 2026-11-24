"""Servidor gerencial do Osório: a tela de rotas, o simulador e os painéis num endereço só, com duas senhas.

    python -m gerencial                          # no PC: http://127.0.0.1:8080
    gunicorn -w 1 -k gthread --threads 32 'gerencial.app:criar()'   # na VPS (ver gerencial/README.md)

Quem vê o quê:
  senha da loja     só a tela de rotas (o tablet do caixa, os motoboys)
  senha da gestão   tudo: rotas, simulador e painéis (Ricardo e Lucas). Os painéis têm folha com nome.
  chave do robô     grava o painel de rotas e lê os toques da loja (mesma API de `robo_rotas/tela_api.py`)

A tela de rotas é a mesma de `robo_rotas/servidor.py`: o HTML do Ricardo sem mudança, com a ponte para o banco
SQLite do servidor. As rotas da API (`/api/estado`, `/api/eventos`, `/api/painel/atual`, `/api/motoboys/<id>`) são
as mesmas, então o robô e a ponte não mudam.

**Um processo só (`-w 1`):** a leitura da tela espera a próxima mudança do banco dentro do processo. Com mais de um
processo, a tela de um não acorda com a gravação do outro. Para muitos aparelhos, mais threads, não mais processos.

Configuração por variável de ambiente, nunca no repositório:
  GERENCIAL_SENHA_LOJA, GERENCIAL_SENHA_GESTAO   (8+ caracteres, diferentes)
  GERENCIAL_SEGREDO, ROBO_TOKEN                   (24+ caracteres)
  GERENCIAL_BANCO      SQLite da tela de rotas (padrão: gerencial/dados/tela.db)
  GERENCIAL_PAINEIS    pasta com os painéis em HTML (padrão: a pasta da reunião da semana, no PC)
  GERENCIAL_HTTPS=1    atrás do HTTPS (cookie Secure)
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, request, send_file

from robo_rotas import servidor as tela
from robo_rotas import simulador as S

RAIZ = Path(__file__).resolve().parent.parent
SESSAO_DIAS = 30
PAPEIS = ("loja", "gestao")
NOME_PAINEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,120}\.(html|xlsx)$")
CSP_GESTAO = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
              "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
              "form-action 'self'")


class Config:
    def __init__(self, env=os.environ):
        faltam = [k for k in ("GERENCIAL_SENHA_LOJA", "GERENCIAL_SENHA_GESTAO", "GERENCIAL_SEGREDO", "ROBO_TOKEN") if not env.get(k)]
        if faltam:
            raise SystemExit("Faltam variáveis de ambiente: " + ", ".join(faltam) + ". Ver gerencial/README.md.")
        if min(len(env["GERENCIAL_SENHA_LOJA"]), len(env["GERENCIAL_SENHA_GESTAO"])) < 8:
            raise SystemExit("Senha com menos de 8 caracteres.")
        if env["GERENCIAL_SENHA_LOJA"] == env["GERENCIAL_SENHA_GESTAO"]:
            raise SystemExit("A senha da loja e a da gestão precisam ser diferentes: a loja não pode abrir os painéis.")
        if min(len(env["GERENCIAL_SEGREDO"]), len(env["ROBO_TOKEN"])) < 24:
            raise SystemExit("Segredo e chave do robô com menos de 24 caracteres.")
        self.senhas = {"loja": env["GERENCIAL_SENHA_LOJA"].encode(), "gestao": env["GERENCIAL_SENHA_GESTAO"].encode()}
        self.segredo = env["GERENCIAL_SEGREDO"].encode()
        self.robo = env["ROBO_TOKEN"].encode()
        self.https = env.get("GERENCIAL_HTTPS") == "1"
        self.banco = env.get("GERENCIAL_BANCO") or str(Path(__file__).parent / "dados" / "tela.db")
        self.paineis = Path(env.get("GERENCIAL_PAINEIS") or _paineis_padrao())


def _paineis_padrao() -> Path:
    try:
        from pipeline.config import ENTREGA_ATUAL
        return Path(ENTREGA_ATUAL)
    except Exception:
        return Path(__file__).parent / "dados" / "paineis"


# ---------- sessão: papel e validade assinados ----------
def assina(segredo: bytes, papel: str, ate: int) -> str:
    msg = f"{papel}.{ate}"
    return f"{msg}.{hmac.new(segredo, msg.encode(), hashlib.sha256).hexdigest()}"


def papel_da_sessao(segredo: bytes, valor: str | None) -> str | None:
    partes = (valor or "").split(".")
    if len(partes) != 3 or partes[0] not in PAPEIS or not partes[1].isdigit() or int(partes[1]) < time.time():
        return None
    return partes[0] if hmac.compare_digest(assina(segredo, partes[0], int(partes[1])), valor) else None


# ---------- páginas ----------
ESTILO = """<style>:root{--bg:#f4f5f7;--card:#fff;--ink:#141920;--muted:#5a6472;--line:#d8dde4;--acc:#b4441c;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0f1216;--card:#181c22;--ink:#e8ecf1;--muted:#9aa4b1;--line:#2b313a;--acc:#e0713f;color-scheme:dark}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
.wrap{max-width:860px;margin:0 auto;padding:24px 16px 48px}h1{font-size:28px;margin:0 0 4px}p.sub{color:var(--muted);margin:0 0 20px}
.grade{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,240px),1fr));gap:12px}
a.cartao{display:block;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;color:inherit;text-decoration:none}
a.cartao b{display:block;font-size:18px;margin-bottom:4px}a.cartao span{color:var(--muted);font-size:14px}
ul.lista{list-style:none;padding:0;margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px}
ul.lista li{border-bottom:1px solid var(--line);padding:10px 14px}ul.lista li:last-child{border:0}ul.lista a{color:inherit}
ul.lista small{color:var(--muted);margin-left:8px}.topo{display:flex;justify-content:space-between;gap:12px;align-items:baseline}
.topo a{color:var(--muted);font-size:14px}form.entrar{max-width:340px;margin:12vh auto 0}
input,button{font:inherit}input[type=password]{width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;background:transparent;color:var(--ink)}
button{margin-top:12px;width:100%;font-weight:600;padding:12px;border:0;border-radius:10px;background:var(--acc);color:#fff}
.erro{color:var(--acc);min-height:1.4em;margin-top:10px}</style>"""


def _pagina(titulo: str, corpo: str) -> str:
    return (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{html.escape(titulo)}</title>{ESTILO}</head>'
            f'<body><div class="wrap">{corpo}</div></body></html>')


def _entrar_html(erro: str = "") -> str:
    return _pagina("Osório", f'<form class="entrar" method="post" action="/entrar"><h1>Osório</h1>'
                   f'<p class="sub">Senha da loja ou da gestão. Cada aparelho pede uma vez.</p>'
                   f'<input type="password" name="senha" autocomplete="current-password" autofocus required aria-label="Senha">'
                   f'<button>Entrar</button><div class="erro">{html.escape(erro)}</div></form>')


def criar(env=os.environ) -> Flask:
    cfg = Config(env)
    Path(cfg.banco).parent.mkdir(parents=True, exist_ok=True)
    banco = tela.Banco(cfg.banco)
    tela_html = tela.tela_html()
    falhas: dict[str, list] = {}
    simulacao = {"html": None, "rodando": False, "erro": None}
    trava_sim = threading.Lock()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = tela.TAM_PAINEL + 10_000
    app.extensions["banco_rotas"] = banco

    # ---------- quem é ----------
    def papel():
        return papel_da_sessao(cfg.segredo, request.cookies.get("sessao"))

    def robo():
        a = request.headers.get("Authorization") or ""
        return a.startswith("Bearer ") and hmac.compare_digest(a[7:].encode(), cfg.robo)

    def ip():
        if request.remote_addr == "127.0.0.1" and request.headers.get("X-Forwarded-For"):
            return request.headers["X-Forwarded-For"].split(",")[0].strip()
        return request.remote_addr or "?"

    def erro(codigo, code):
        return jsonify({"code": code}), codigo

    def json_corpo():
        """Só JSON: formulário de outro site não manda isso sem o navegador perguntar antes."""
        if not (request.content_type or "").startswith("application/json"):
            return None
        obj = request.get_json(silent=True)
        return obj if isinstance(obj, dict) else None

    def precisa(*papeis):
        p = papel()
        if p is None:
            return redirect("/entrar")
        if p not in papeis:
            abort(403)
        return None

    @app.after_request
    def cabecalhos(r: Response):
        r.headers.setdefault("Cache-Control", "no-store")
        r.headers["X-Content-Type-Options"] = "nosniff"
        r.headers["Referrer-Policy"] = "no-referrer"
        r.headers["Content-Security-Policy"] = tela.CSP if request.path.startswith(("/rotas", "/api")) else CSP_GESTAO
        return r

    # ---------- entrada ----------
    @app.get("/saude")
    def saude():
        return Response("ok", mimetype="text/plain")

    @app.get("/entrar")
    def entrar_form():
        return _entrar_html()

    @app.post("/entrar")
    def entrar():
        agora, quem = time.time(), ip()
        n, ate = falhas.get(quem, [0, 0])
        if ate > agora:
            return _entrar_html("Muitas tentativas. Espere 15 minutos."), 429
        dada = hashlib.sha256((request.form.get("senha") or "").encode()).digest()
        achou = next((p for p in PAPEIS if hmac.compare_digest(dada, hashlib.sha256(cfg.senhas[p]).digest())), None)
        if not achou:
            n += 1
            falhas[quem] = [0, agora + tela.TRAVA_S] if n >= tela.TENTATIVAS_MAX else [n, 0]
            time.sleep(1)
            return _entrar_html("Senha errada."), 401
        falhas.pop(quem, None)
        r = redirect("/despacho" if achou == "loja" else "/")
        r.set_cookie("sessao", assina(cfg.segredo, achou, int(agora + SESSAO_DIAS * 86400)), max_age=SESSAO_DIAS * 86400,
                     httponly=True, samesite="Strict", secure=cfg.https, path="/")
        return r

    @app.get("/sair")
    def sair():
        r = redirect("/entrar")
        r.delete_cookie("sessao", path="/")
        return r

    @app.get("/")
    def inicio():
        p = papel()
        if p is None:
            return redirect("/entrar")
        if p == "loja":
            return redirect("/despacho")
        return _pagina("Osório", '<div class="topo"><h1>Osório</h1><a href="/sair">Sair</a></div>'
                       '<p class="sub">Servidor gerencial: o que roda sem o PC ligado.</p><div class="grade">'
                       '<a class="cartao" href="/rotas/"><b>Tela de rotas</b><span>Pedidos, quadro por motoboy e mapa. '
                       'A loja entra só aqui.</span></a>'
                       '<a class="cartao" href="/despacho"><b>Despacho</b><span>Chegou o pedido: o robô escolhe o '
                       'motoboy na hora, com as regras da reunião.</span></a>'
                       '<a class="cartao" href="/simulador"><b>Simulador de rotas</b><span>Uma noite inventada com as regras '
                       'da reunião, por número de motoboys.</span></a>'
                       '<a class="cartao" href="/paineis/"><b>Painéis</b><span>Rentabilidade, gestão, equipe e as páginas '
                       'da semana.</span></a></div>')

    # ---------- tela de rotas (mesma API de robo_rotas/servidor.py) ----------
    @app.get("/rotas")
    def rotas_barra():
        return redirect("/rotas/")

    @app.get("/rotas/")
    def rotas():
        return precisa("loja", "gestao") or Response(tela_html, mimetype="text/html")

    @app.get("/rotas/<nome>")
    @app.get("/<any('ponte.js'):nome>")
    def rotas_estatico(nome):
        if (bloqueio := precisa("loja", "gestao")):
            return bloqueio
        if nome not in tela.ESTATICOS:
            abort(404)
        r = send_file(tela.PASTA / nome, mimetype=tela.ESTATICOS[nome])
        if nome.endswith(".png"):
            r.headers["Cache-Control"] = "private, max-age=3600"
        return r

    @app.get("/api/estado")
    def estado():
        if papel() is None:
            return erro(401, "not_granted")
        v = request.args.get("v", "0")
        v = int(v) if v.isdigit() else 0
        if v and v == banco.versao:
            banco.espera(v, tela.ESPERA_S)
        return jsonify(banco.estado())

    @app.get("/api/eventos")
    def eventos_robo():
        if not robo():
            return erro(403, "permission_denied")
        try:
            desde = float(request.args.get("desde") or 0)
        except ValueError:
            return erro(400, "desde")
        return jsonify({"eventos": [dict(e["dados"], id=e["id"]) for e in banco.eventos(desde)]})

    @app.post("/api/eventos")
    def evento_loja():
        if papel() is None:
            return erro(401, "not_granted")
        ev = json_corpo()
        if ev is None or len(json.dumps(ev)) > tela.TAM_EVENTO:
            return erro(400, "json")
        if ev.get("tipo") not in tela.TIPOS_EVENTO or not isinstance(ev.get("criado"), (int, float)):
            return erro(400, "evento_invalido")
        id_ = secrets.token_hex(10)
        banco.set("eventos", id_, ev)
        return jsonify({"id": id_})

    @app.route("/api/painel/atual", methods=["PUT", "DELETE"])
    def painel():
        if not robo():
            return erro(403, "permission_denied")
        if request.method == "DELETE":
            banco.delete("painel", "atual")
            return jsonify({"ok": True})
        dados = json_corpo()
        if dados is None:
            return erro(400, "json")
        banco.set("painel", "atual", dados)
        banco.limpa_eventos()
        return jsonify({"ok": True})

    @app.get("/api/motoboys")
    def motoboys_robo():
        if not robo():
            return erro(403, "permission_denied")
        return jsonify({"motoboys": [dict(m["dados"], id=m["id"]) for m in banco.lista("motoboys")]})

    @app.route("/api/motoboys/<id_>", methods=["PUT", "DELETE"])
    def motoboy(id_):
        if papel() is None:
            return erro(401, "not_granted")
        if not tela.ID_OK.match(id_):
            return erro(400, "id")
        if request.method == "DELETE":
            banco.delete("motoboys", id_)
            return jsonify({"ok": True})
        dados = json_corpo()
        if dados is None:
            return erro(400, "json")
        nome = str(dados.get("nome") or "")
        if not re.fullmatch(r"[A-Za-zÀ-ÿ']{2,30}", nome):
            return erro(400, "nome")
        banco.set("motoboys", id_, {"nome": nome, "criado": dados.get("criado") or int(time.time() * 1000)})
        return jsonify({"ok": True})

    # ---------- simulador ----------
    def _gera_simulacao():
        from robo_rotas.simulador_pagina import dados, pagina
        try:
            simulacao["html"] = pagina(dados())
            simulacao["erro"] = None
        except Exception as e:   # mostra na página em vez de derrubar o servidor
            simulacao["erro"] = f"{type(e).__name__}: {e}"
        finally:
            simulacao["rodando"] = False

    def _dispara():
        with trava_sim:
            if simulacao["rodando"]:
                return
            simulacao["rodando"] = True
        threading.Thread(target=_gera_simulacao, daemon=True).start()

    @app.get("/simulador")
    def simulador():
        if (bloqueio := precisa("gestao")):
            return bloqueio
        if simulacao["html"]:
            return simulacao["html"]
        _dispara()
        msg = simulacao["erro"] or "Rodando as noites sorteadas (uns 20 segundos). A página atualiza sozinha."
        return _pagina("Simulador", f'<meta http-equiv="refresh" content="5"><h1>Simulador de rotas</h1>'
                       f'<p class="sub">{html.escape(msg)}</p>')

    @app.post("/simulador/refazer")
    def simulador_refazer():
        if (bloqueio := precisa("gestao")):
            return bloqueio
        simulacao["html"] = None
        _dispara()
        return redirect("/simulador")

    @app.get("/api/simular")
    def api_simular():
        """Uma noite, para testar uma regra sem gerar a página inteira: dia, motoboys, jeito, semente."""
        if papel() != "gestao" and not robo():
            return erro(403, "permission_denied")
        dia = request.args.get("dia", "sexta")
        jeito = request.args.get("jeito", "dois")
        try:
            motos = int(request.args.get("motoboys", 4))
            semente = int(request.args.get("semente", 1))
        except ValueError:
            return erro(400, "numero")
        if dia not in S.itajuba.PEDIDOS_HORA or jeito not in S.POLITICAS or not 1 <= motos <= 15:
            return erro(400, "parametro")
        noite = S.simular(S.gerar_pedidos(dia, 18, 25, semente), motos, jeito, semente)
        return jsonify({"dia": dia, "motoboys": motos, "jeito": S.POLITICAS[jeito][0], "semente": semente,
                        "resumo": S.resumo(noite)})

    # ---------- painéis ----------
    def _lista_paineis():
        if not cfg.paineis.is_dir():
            return []
        return sorted((p for p in cfg.paineis.iterdir() if p.is_file() and NOME_PAINEL.match(p.name)),
                      key=lambda p: (not p.name.startswith("painel-"), p.name))

    @app.get("/paineis/")
    def paineis():
        if (bloqueio := precisa("gestao")):
            return bloqueio
        itens = "".join(
            f'<li><a href="/paineis/{html.escape(p.name)}">{html.escape(p.stem.replace("-", " "))}</a>'
            f'<small>{time.strftime("%d/%m %H:%M", time.localtime(p.stat().st_mtime))}</small></li>'
            for p in _lista_paineis()) or "<li>Nenhum painel publicado ainda.</li>"
        return _pagina("Painéis", f'<div class="topo"><h1>Painéis</h1><a href="/">Início</a></div>'
                       f'<p class="sub">O que o pipeline gerou por último. Contém folha com nome: só a gestão vê.</p>'
                       f'<ul class="lista">{itens}</ul>')

    @app.get("/paineis/<nome>")
    def painel_arquivo(nome):
        if (bloqueio := precisa("gestao")):
            return bloqueio
        alvo = next((p for p in _lista_paineis() if p.name == nome), None)   # só o que está na lista: sem ../
        if alvo is None:
            abort(404)
        return send_file(alvo, as_attachment=alvo.suffix == ".xlsx")

    # ---------- despacho em tempo real (gerencial/despacho_rotas.py) ----------
    from gerencial.despacho_rotas import registrar
    registrar(app, banco, papel, precisa, erro, json_corpo)

    return app


def main():
    app = criar()
    porta = int(os.environ.get("GERENCIAL_PORTA") or 8080)
    try:
        from waitress import serve
        print(f"Servidor gerencial em http://127.0.0.1:{porta} (waitress)", flush=True)
        serve(app, host="127.0.0.1", port=porta, threads=32)
    except ImportError:
        print(f"Servidor gerencial em http://127.0.0.1:{porta} (servidor de teste do Flask)", flush=True)
        app.run(host="127.0.0.1", port=porta, threaded=True)


if __name__ == "__main__":
    main()
