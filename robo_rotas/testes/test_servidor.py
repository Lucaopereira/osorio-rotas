"""O servidor da tela: login, quem grava o quê e a leitura que espera mudança."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from robo_rotas import servidor, tela_api

SENHA, SEGREDO, ROBO = "senha-de-teste", "s" * 32, "r" * 32


class SemRedirecionar(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Servidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        env = {"TELA_SENHA": SENHA, "TELA_SEGREDO": SEGREDO, "ROBO_TOKEN": ROBO,
               "TELA_BANCO": str(Path(cls.tmp.name) / "t.db"), "TELA_PORTA": "0"}
        servidor.os.environ["TELA_SILENCIO"] = "1"
        cls.banco = servidor.Banco(env["TELA_BANCO"])
        cls.srv = servidor.criar_servidor(servidor.Config(env), cls.banco)
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.abre = urllib.request.build_opener(SemRedirecionar)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.banco.con.close()
        cls.tmp.cleanup()

    def pede(self, metodo, caminho, corpo=None, cookie=None, token=None, tipo="application/json", bruto=None):
        h = {"Content-Type": tipo}
        if cookie:
            h["Cookie"] = cookie
        if token:
            h["Authorization"] = "Bearer " + token
        dados = bruto if bruto is not None else (None if corpo is None else json.dumps(corpo).encode())
        req = urllib.request.Request(self.url + caminho, data=dados, method=metodo, headers=h)
        try:
            with self.abre.open(req, timeout=40) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def entra(self):
        st, _, h = self.pede("POST", "/entrar", bruto=f"senha={SENHA}".encode(), tipo="application/x-www-form-urlencoded")
        self.assertEqual(st, 303)
        return h["Set-Cookie"].split(";")[0]

    def test_sem_login_so_ve_a_pagina_de_senha(self):
        st, corpo, _ = self.pede("GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(b'name="senha"', corpo)
        self.assertNotIn(b"ponte.js", corpo)
        self.assertEqual(self.pede("GET", "/api/estado")[0], 401)
        self.assertEqual(self.pede("GET", "/itajuba_z14.png")[0], 303)

    def test_senha_errada_nao_entra(self):
        st, _, h = self.pede("POST", "/entrar", bruto=b"senha=errada", tipo="application/x-www-form-urlencoded")
        self.assertEqual(st, 401)
        self.assertNotIn("Set-Cookie", h)

    def test_logado_recebe_a_tela_do_ricardo_com_a_ponte(self):
        st, corpo, h = self.pede("GET", "/", cookie=self.entra())
        self.assertEqual(st, 200)
        self.assertIn(b'<script src="/ponte.js"></script><script>', corpo)
        self.assertIn(b"<title>Waisorio</title>", corpo)
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])

    def test_painel_so_o_robo_grava(self):
        c = self.entra()
        self.assertEqual(self.pede("PUT", "/api/painel/atual", {"agora": "20:00"}, cookie=c)[0], 403)
        self.assertEqual(self.pede("PUT", "/api/painel/atual", {"agora": "20:00"}, token="errado" * 6)[0], 403)
        self.assertEqual(self.pede("PUT", "/api/painel/atual", {"agora": "20:01"}, token=ROBO)[0], 200)
        estado = json.loads(self.pede("GET", "/api/estado", cookie=c)[1])
        self.assertEqual(estado["colecoes"]["painel"][0]["dados"]["agora"], "20:01")

    def test_toque_da_loja_chega_ao_robo(self):
        c = self.entra()
        criado = time.time() * 1000
        self.assertEqual(self.pede("POST", "/api/eventos", {"tipo": "voltou", "moto": "Alan", "criado": criado}, cookie=c)[0], 200)
        self.assertEqual(self.pede("POST", "/api/eventos", {"tipo": "apagar_tudo", "criado": criado}, cookie=c)[0], 400)
        self.assertEqual(self.pede("POST", "/api/eventos", bruto=b"tipo=voltou", cookie=c, tipo="application/x-www-form-urlencoded")[0], 400)
        evs = tela_api.ler_eventos(criado - 1, url=self.url, token=ROBO)
        self.assertEqual([e["moto"] for e in evs], ["Alan"])

    def test_cadastro_so_primeiro_nome(self):
        c = self.entra()
        self.assertEqual(self.pede("PUT", "/api/motoboys/beto", {"nome": "Beto", "criado": 1}, cookie=c)[0], 200)
        self.assertEqual(self.pede("PUT", "/api/motoboys/x", {"nome": "Beto da Silva 1199"}, cookie=c)[0], 400)
        self.assertIn("Beto", [m["nome"] for m in tela_api.ler_motoboys(url=self.url, token=ROBO)])
        self.assertEqual(self.pede("DELETE", "/api/motoboys/beto", cookie=c)[0], 200)

    def test_leitura_espera_a_mudanca(self):
        c = self.entra()
        v = json.loads(self.pede("GET", "/api/estado", cookie=c)[1])["v"]
        threading.Timer(0.5, lambda: tela_api.enviar_painel({"agora": "21:00"}, url=self.url, token=ROBO)).start()
        t0 = time.time()
        novo = json.loads(self.pede("GET", f"/api/estado?v={v}", cookie=c)[1])
        self.assertLess(time.time() - t0, 5)
        self.assertNotEqual(novo["v"], v)

    def test_painel_de_exemplo_tem_o_que_a_tela_le(self):
        p = tela_api.painel_exemplo()
        for campo in ("saidas", "rua", "quadro", "motoboys", "mapa", "agora", "gerado_ms", "dia"):
            self.assertIn(campo, p)
        self.assertTrue(p["replay"])


class Sessao(unittest.TestCase):
    def test_cookie_vencido_ou_alterado_nao_vale(self):
        seg = b"x" * 32
        bom = servidor._assina(seg, int(time.time()) + 60)
        self.assertTrue(servidor.sessao_valida(seg, bom))
        self.assertFalse(servidor.sessao_valida(seg, bom[:-1] + ("0" if bom[-1] != "0" else "1")))
        self.assertFalse(servidor.sessao_valida(seg, servidor._assina(seg, int(time.time()) - 1)))
        self.assertFalse(servidor.sessao_valida(b"y" * 32, bom))


if __name__ == "__main__":
    unittest.main()
