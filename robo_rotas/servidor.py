"""A tela Waisorio do Ricardo servida pela VPS, com login e o banco no próprio servidor.

A tela é o HTML dele sem mudança nenhuma (`tela/index.html`, copiado do artefato). O que muda é de onde ela lê:
no claude.ai ela chama `claude.use("db")`; aqui o servidor põe antes um `ponte.js` que responde a essa chamada
com as mesmas funções (`doc().onSnapshot`, `collection().orderBy().limit()`, `add`, `set`, `delete`) e fala com
este servidor. Os nomes dos documentos são os mesmos: `painel/atual`, `eventos`, `motoboys`.

Quem grava o quê (a mesma regra do banco do artefato):
  painel/atual   só o robô (chave ROBO_TOKEN)                      no artefato: só o dono
  eventos        a loja logada (os toques) e o robô lê              no artefato: quem pode usar
  motoboys       a loja logada                                     no artefato: quem pode usar

Só biblioteca padrão do Python. Configuração por variável de ambiente, nunca no repositório:
  TELA_SENHA     senha da loja (a tela pede uma vez por aparelho)
  TELA_SEGREDO   assina o cookie da sessão
  ROBO_TOKEN     chave do robô para gravar o painel e ler os eventos
  TELA_BANCO     arquivo SQLite (padrão: robo_rotas/tela.db)
  TELA_PORTA     padrão 8080, só em 127.0.0.1 (o Caddy põe o HTTPS na frente)
  TELA_HTTPS     1 quando estiver atrás do HTTPS (cookie Secure)

    python -m robo_rotas.servidor
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PASTA = Path(__file__).parent / "tela"
SESSAO_DIAS = 30
ESPERA_S = 25                 # a leitura da tela espera até 25 s por uma mudança antes de responder
EVENTOS_NA_TELA = 200         # a tela mostra os 30 últimos; mandamos folga para o recorte dela
EVENTOS_DIAS = 7              # evento mais velho que isso sai do banco
TAM_EVENTO = 4_000
TAM_PAINEL = 1_000_000
TIPOS_EVENTO = {"saiu", "voltou", "fora", "entrou", "saiu_turno", "pequeno", "entregador",
                "fixar", "soltar", "pronto", "producao"}
ESTATICOS = {"itajuba_z14.png": "image/png", "itajuba_z15.png": "image/png", "logo_osorio.png": "image/png",
             "ponte.js": "text/javascript; charset=utf-8"}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
       "form-action 'self'")
ID_OK = re.compile(r"^[a-z0-9]{1,30}$")
TENTATIVAS_MAX = 8            # senha errada 8 vezes no mesmo endereço: trava 15 min
TRAVA_S = 15 * 60


class Banco:
    """Documentos por coleção, num SQLite. Toda gravação sobe a versão e acorda quem está esperando."""

    def __init__(self, caminho: str | Path):
        self.con = sqlite3.connect(str(caminho), check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("CREATE TABLE IF NOT EXISTS docs (colecao TEXT, id TEXT, dados TEXT, gravado REAL, "
                         "PRIMARY KEY (colecao, id))")
        self.trava = threading.Lock()
        self.mudou = threading.Condition(self.trava)
        self.versao = int(time.time() * 1000)   # muda a cada reinício: a tela relê tudo

    def _grava(self, sql, args):
        with self.mudou:
            self.con.execute(sql, args)
            self.con.commit()
            self.versao += 1
            self.mudou.notify_all()
            return self.versao

    def set(self, colecao: str, id_: str, dados: dict):
        return self._grava("INSERT OR REPLACE INTO docs VALUES (?, ?, ?, ?)",
                           (colecao, id_, json.dumps(dados, ensure_ascii=False), time.time()))

    def delete(self, colecao: str, id_: str):
        return self._grava("DELETE FROM docs WHERE colecao = ? AND id = ?", (colecao, id_))

    def get(self, colecao: str, id_: str):
        with self.trava:
            r = self.con.execute("SELECT dados FROM docs WHERE colecao = ? AND id = ?", (colecao, id_)).fetchone()
        return json.loads(r[0]) if r else None

    def lista(self, colecao: str):
        with self.trava:
            rs = self.con.execute("SELECT id, dados FROM docs WHERE colecao = ?", (colecao,)).fetchall()
        return [{"id": i, "dados": json.loads(d)} for i, d in rs]

    def eventos(self, desde: float | None = None, ultimos: int | None = None):
        evs = [e for e in self.lista("eventos") if desde is None or float(e["dados"].get("criado") or 0) > desde]
        evs.sort(key=lambda e: float(e["dados"].get("criado") or 0))
        return evs[-ultimos:] if ultimos else evs

    def limpa_eventos(self):
        corte = (time.time() - EVENTOS_DIAS * 86400) * 1000
        velhos = [e["id"] for e in self.lista("eventos") if float(e["dados"].get("criado") or 0) < corte]
        for i in velhos:
            self.delete("eventos", i)
        return len(velhos)

    def estado(self):
        with self.trava:
            v = self.versao
        painel = self.get("painel", "atual")
        evs = self.eventos(ultimos=EVENTOS_NA_TELA)
        return {"v": v, "colecoes": {"painel": [{"id": "atual", "dados": painel}] if painel is not None else [],
                                     "eventos": list(reversed(evs)), "motoboys": self.lista("motoboys")}}

    def espera(self, versao: int, segundos: float):
        with self.mudou:
            self.mudou.wait_for(lambda: self.versao != versao, timeout=segundos)


class Config:
    def __init__(self, env=os.environ):
        faltam = [k for k in ("TELA_SENHA", "TELA_SEGREDO", "ROBO_TOKEN") if not env.get(k)]
        if faltam:
            raise SystemExit("Faltam variáveis de ambiente: " + ", ".join(faltam) + ". Ver robo_rotas/README.md.")
        if len(env["TELA_SENHA"]) < 8 or len(env["ROBO_TOKEN"]) < 24 or len(env["TELA_SEGREDO"]) < 24:
            raise SystemExit("Senha com menos de 8 caracteres, ou segredo e chave do robô com menos de 24.")
        self.senha = env["TELA_SENHA"].encode()
        self.segredo = env["TELA_SEGREDO"].encode()
        self.robo = env["ROBO_TOKEN"].encode()
        self.https = env.get("TELA_HTTPS") == "1"
        self.banco = env.get("TELA_BANCO") or str(Path(__file__).parent / "tela.db")
        self.porta = int(env.get("TELA_PORTA") or 8080)


def _assina(segredo: bytes, ate: int) -> str:
    return f"{ate}.{hmac.new(segredo, str(ate).encode(), hashlib.sha256).hexdigest()}"


def sessao_valida(segredo: bytes, valor: str | None) -> bool:
    if not valor or "." not in valor:
        return False
    ate = valor.split(".", 1)[0]
    if not ate.isdigit() or int(ate) < time.time():
        return False
    return hmac.compare_digest(_assina(segredo, int(ate)), valor)


def tela_html() -> bytes:
    """O HTML do Ricardo, com a ponte carregada antes do script dele. Nada mais muda."""
    html = (PASTA / "index.html").read_text(encoding="utf-8")
    if "<script>" not in html:
        raise SystemExit("tela/index.html sem <script>: não é a tela esperada.")
    return html.replace("<script>", '<script src="/ponte.js"></script><script>', 1).encode("utf-8")


PAGINA_ENTRAR = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Waisorio</title><style>
:root{--bg:#f6f4ef;--fg:#1d1b16;--muted:#6b665c;--line:#d9d4c8;--acc:#b4441c}
@media (prefers-color-scheme:dark){:root{--bg:#17150f;--fg:#efebe2;--muted:#a39e92;--line:#3a362d;--acc:#e0713f}}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.4 system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}
form{width:100%;max-width:340px}h1{font-size:26px;margin:0 0 4px}p{color:var(--muted);margin:0 0 18px}
input{width:100%;box-sizing:border-box;font-size:18px;padding:12px;border:1px solid var(--line);border-radius:10px;background:transparent;color:var(--fg)}
button{margin-top:12px;width:100%;font-size:18px;font-weight:600;padding:12px;border:0;border-radius:10px;background:var(--acc);color:#fff}
.erro{color:var(--acc);margin-top:12px;min-height:1.4em}</style></head><body>
<form method="post" action="/entrar"><h1>Waisorio</h1><p>Senha da loja. Cada aparelho pede uma vez.</p>
<input type="password" name="senha" autocomplete="current-password" autofocus required aria-label="Senha">
<button>Entrar</button><div class="erro">{erro}</div></form></body></html>"""


def criar_servidor(cfg: Config, banco: Banco, host="127.0.0.1", porta: int | None = None) -> ThreadingHTTPServer:
    falhas: dict[str, list] = {}
    pagina = {"html": tela_html()}

    class Tela(BaseHTTPRequestHandler):
        server_version = "Waisorio"
        sys_version = ""

        def log_message(self, fmt, *args):   # sem corpo, sem cookie: só método, caminho e código
            if not os.environ.get("TELA_SILENCIO"):
                super().log_message(fmt, *args)

        # ---------- respostas ----------
        def _manda(self, codigo, corpo: bytes = b"", tipo="application/json; charset=utf-8", extra=None):
            self.send_response(codigo)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corpo)

        def _json(self, codigo, obj):
            self._manda(codigo, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

        def _erro(self, codigo, code):
            self._json(codigo, {"code": code})

        # ---------- quem é ----------
        def _cookie(self):
            for parte in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = parte.strip().partition("=")
                if k == "sessao":
                    return v
            return None

        def _logado(self):
            return sessao_valida(cfg.segredo, self._cookie())

        def _robo(self):
            a = self.headers.get("Authorization") or ""
            return a.startswith("Bearer ") and hmac.compare_digest(a[7:].encode(), cfg.robo)

        def _ip(self):
            # atrás do Caddy o endereço real vem no cabeçalho; só vale se a conexão veio da própria máquina
            if self.client_address[0] == "127.0.0.1" and self.headers.get("X-Forwarded-For"):
                return self.headers["X-Forwarded-For"].split(",")[0].strip()
            return self.client_address[0]

        def _corpo(self, limite):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limite:
                return None, "grande_demais"
            bruto = self.rfile.read(n) if n else b""
            return bruto, None

        def _json_corpo(self, limite):
            # só aceita JSON: formulário de outro site não consegue mandar isso sem o navegador perguntar antes
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return None, "tipo"
            bruto, erro = self._corpo(limite)
            if erro:
                return None, erro
            try:
                obj = json.loads(bruto or b"null")
            except ValueError:
                return None, "json"
            return (obj, None) if isinstance(obj, dict) else (None, "json")

        # ---------- rotas ----------
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            url = urlparse(self.path)
            caminho = url.path
            if caminho == "/saude":
                return self._manda(200, b"ok", "text/plain; charset=utf-8")
            if caminho == "/api/eventos" and self._robo():
                desde = float((parse_qs(url.query).get("desde") or ["0"])[0] or 0)
                return self._json(200, {"eventos": [dict(e["dados"], id=e["id"]) for e in banco.eventos(desde)]})
            if caminho == "/api/motoboys" and self._robo():
                return self._json(200, {"motoboys": [dict(m["dados"], id=m["id"]) for m in banco.lista("motoboys")]})
            if caminho == "/favicon.ico":
                return self._manda(404, b"", "text/plain; charset=utf-8")
            if caminho == "/sair":
                return self._manda(303, b"", extra={"Location": "/", "Set-Cookie": "sessao=; Max-Age=0; Path=/; HttpOnly; SameSite=Strict"})
            if not self._logado():
                if caminho.startswith("/api/"):
                    return self._erro(401, "not_granted")
                if caminho != "/":
                    return self._manda(303, b"", extra={"Location": "/"})
                return self._manda(200, PAGINA_ENTRAR.replace("{erro}", "").encode(), "text/html; charset=utf-8")
            if caminho == "/":
                return self._manda(200, pagina["html"], "text/html; charset=utf-8")
            if caminho.lstrip("/") in ESTATICOS:
                nome = caminho.lstrip("/")
                return self._manda(200, (PASTA / nome).read_bytes(), ESTATICOS[nome],
                                   extra={"Cache-Control": "private, max-age=3600"} if nome.endswith(".png") else None)
            if caminho == "/api/estado":
                v = int((parse_qs(url.query).get("v") or ["0"])[0] or 0)
                if v and v == banco.versao:
                    banco.espera(v, ESPERA_S)
                return self._json(200, banco.estado())
            return self._erro(404, "not_found")

        def do_POST(self):
            caminho = urlparse(self.path).path
            if caminho == "/entrar":
                return self._entrar()
            if not self._logado():
                return self._erro(401, "not_granted")
            if caminho == "/api/eventos":
                ev, erro = self._json_corpo(TAM_EVENTO)
                if erro:
                    return self._erro(400, erro)
                if ev.get("tipo") not in TIPOS_EVENTO or not isinstance(ev.get("criado"), (int, float)):
                    return self._erro(400, "evento_invalido")
                id_ = secrets.token_hex(10)
                banco.set("eventos", id_, ev)
                return self._json(200, {"id": id_})
            return self._erro(404, "not_found")

        def do_PUT(self):
            caminho = urlparse(self.path).path
            if caminho == "/api/painel/atual":
                if not self._robo():
                    return self._erro(403, "permission_denied")   # no artefato: só o dono grava o painel
                painel, erro = self._json_corpo(TAM_PAINEL)
                if erro:
                    return self._erro(400, erro)
                banco.set("painel", "atual", painel)
                banco.limpa_eventos()
                return self._json(200, {"ok": True})
            m = re.fullmatch(r"/api/motoboys/([^/]+)", caminho)
            if m and self._logado():
                if not ID_OK.match(m.group(1)):
                    return self._erro(400, "id")
                dados, erro = self._json_corpo(TAM_EVENTO)
                if erro:
                    return self._erro(400, erro)
                nome = str(dados.get("nome") or "")
                if not re.fullmatch(r"[A-Za-zÀ-ÿ']{2,30}", nome):     # só o primeiro nome, como a tela pede
                    return self._erro(400, "nome")
                banco.set("motoboys", m.group(1), {"nome": nome, "criado": dados.get("criado") or int(time.time() * 1000)})
                return self._json(200, {"ok": True})
            return self._erro(401 if not self._logado() else 403, "permission_denied")

        def do_DELETE(self):
            if urlparse(self.path).path == "/api/painel/atual" and self._robo():
                banco.delete("painel", "atual")
                return self._json(200, {"ok": True})
            m = re.fullmatch(r"/api/motoboys/([^/]+)", urlparse(self.path).path)
            if not self._logado():
                return self._erro(401, "not_granted")
            if not m or not ID_OK.match(m.group(1)):
                return self._erro(403, "permission_denied")
            banco.delete("motoboys", m.group(1))
            return self._json(200, {"ok": True})

        def _entrar(self):
            ip, agora = self._ip(), time.time()
            n, ate = falhas.get(ip, [0, 0])
            if ate > agora:
                return self._manda(429, PAGINA_ENTRAR.replace("{erro}", "Muitas tentativas. Espere 15 minutos.").encode(),
                                   "text/html; charset=utf-8")
            bruto, _ = self._corpo(2_000)
            senha = (parse_qs((bruto or b"").decode("utf-8", "replace")).get("senha") or [""])[0].encode()
            if not hmac.compare_digest(hashlib.sha256(senha).digest(), hashlib.sha256(cfg.senha).digest()):
                n += 1
                falhas[ip] = [0, agora + TRAVA_S] if n >= TENTATIVAS_MAX else [n, 0]
                time.sleep(1)
                return self._manda(401, PAGINA_ENTRAR.replace("{erro}", "Senha errada.").encode(), "text/html; charset=utf-8")
            falhas.pop(ip, None)
            ate_s = int(agora + SESSAO_DIAS * 86400)
            cookie = f"sessao={_assina(cfg.segredo, ate_s)}; Max-Age={SESSAO_DIAS * 86400}; Path=/; HttpOnly; SameSite=Strict"
            if cfg.https:
                cookie += "; Secure"
            return self._manda(303, b"", extra={"Location": "/", "Set-Cookie": cookie})

    srv = ThreadingHTTPServer((host, cfg.porta if porta is None else porta), Tela)
    srv.daemon_threads = True
    return srv


def main():
    cfg = Config()
    banco = Banco(cfg.banco)
    srv = criar_servidor(cfg, banco)
    print(f"Waisorio em http://127.0.0.1:{srv.server_address[1]} (banco {cfg.banco})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
