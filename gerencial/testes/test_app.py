"""Servidor gerencial: duas senhas, quem vê o quê, a tela de rotas com a mesma API e os painéis sem fuga de pasta."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from gerencial import app as G

LOJA, GESTAO, SEGREDO, ROBO = "senha-da-loja", "senha-da-gestao", "s" * 32, "r" * 32


class Gerencial(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        pasta = Path(cls.tmp.name) / "paineis"
        pasta.mkdir()
        (pasta / "painel-rentabilidade.html").write_text("<h1>painel</h1>", encoding="utf-8")
        (pasta / "segredo.txt").write_text("não lista", encoding="utf-8")
        cls.app = G.criar({"GERENCIAL_SENHA_LOJA": LOJA, "GERENCIAL_SENHA_GESTAO": GESTAO, "GERENCIAL_SEGREDO": SEGREDO,
                           "ROBO_TOKEN": ROBO, "GERENCIAL_BANCO": str(Path(cls.tmp.name) / "t.db"),
                           "GERENCIAL_PAINEIS": str(pasta)})

    @classmethod
    def tearDownClass(cls):
        cls.app.extensions["banco_rotas"].con.close()
        cls.tmp.cleanup()

    def cliente(self, senha=None):
        c = self.app.test_client()
        if senha:
            r = c.post("/entrar", data={"senha": senha})
            self.assertEqual(r.status_code, 302)
        return c

    def test_sem_login_vai_para_a_senha(self):
        c = self.cliente()
        self.assertEqual(c.get("/").headers["Location"], "/entrar")
        self.assertEqual(c.get("/rotas/").headers["Location"], "/entrar")
        self.assertEqual(c.get("/paineis/").status_code, 302)
        self.assertEqual(c.get("/api/estado").status_code, 401)

    def test_senha_errada(self):
        r = self.cliente().post("/entrar", data={"senha": "nada-disso"})
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("Set-Cookie", r.headers)

    def test_loja_so_ve_a_tela_de_rotas(self):
        c = self.cliente(LOJA)
        self.assertEqual(c.get("/").headers["Location"], "/despacho")
        r = c.get("/rotas/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b'<script src="/ponte.js"></script>', r.data)
        self.assertEqual(c.get("/ponte.js").status_code, 200)
        self.assertEqual(c.get("/rotas/itajuba_z14.png").status_code, 200)
        self.assertEqual(c.get("/paineis/").status_code, 403)
        self.assertEqual(c.get("/paineis/painel-rentabilidade.html").status_code, 403)
        self.assertEqual(c.get("/simulador").status_code, 403)
        self.assertEqual(c.get("/api/simular").status_code, 403)

    def test_gestao_ve_os_paineis_e_nada_fora_da_lista(self):
        c = self.cliente(GESTAO)
        r = c.get("/paineis/")
        self.assertIn(b"painel rentabilidade", r.data)
        self.assertNotIn(b"segredo", r.data)
        self.assertEqual(c.get("/paineis/painel-rentabilidade.html").data, b"<h1>painel</h1>")
        self.assertEqual(c.get("/paineis/segredo.txt").status_code, 404)
        self.assertEqual(c.get("/paineis/..%2Fsegredo.txt").status_code, 404)

    def test_robo_grava_o_painel_e_le_os_toques(self):
        c = self.cliente(LOJA)
        h = {"Authorization": "Bearer " + ROBO}
        self.assertEqual(c.put("/api/painel/atual", json={"agora": "20:00"}).status_code, 403)
        self.assertEqual(c.put("/api/painel/atual", json={"agora": "20:01"}, headers=h).status_code, 200)
        self.assertEqual(c.get("/api/estado").get_json()["colecoes"]["painel"][0]["dados"]["agora"], "20:01")
        criado = time.time() * 1000
        self.assertEqual(c.post("/api/eventos", json={"tipo": "voltou", "moto": "Alan", "criado": criado}).status_code, 200)
        self.assertEqual(c.post("/api/eventos", json={"tipo": "apagar", "criado": criado}).status_code, 400)
        self.assertEqual(c.post("/api/eventos", data="tipo=voltou").status_code, 400)
        evs = c.get(f"/api/eventos?desde={criado - 1}", headers=h).get_json()["eventos"]
        self.assertEqual([e["moto"] for e in evs], ["Alan"])

    def test_motoboy_so_primeiro_nome(self):
        c = self.cliente(LOJA)
        self.assertEqual(c.put("/api/motoboys/beto", json={"nome": "Beto"}).status_code, 200)
        self.assertEqual(c.put("/api/motoboys/x", json={"nome": "Beto da Silva"}).status_code, 400)
        self.assertEqual(c.put("/api/motoboys/../x", json={"nome": "Beto"}).status_code, 404)
        self.assertEqual(c.delete("/api/motoboys/beto").status_code, 200)

    def test_leitura_espera_a_mudanca(self):
        c = self.cliente(LOJA)
        v = c.get("/api/estado").get_json()["v"]
        threading.Timer(0.4, lambda: self.app.test_client().put(
            "/api/painel/atual", json={"agora": "21:00"}, headers={"Authorization": "Bearer " + ROBO})).start()
        t0 = time.time()
        novo = c.get(f"/api/estado?v={v}").get_json()
        self.assertLess(time.time() - t0, 5)
        self.assertNotEqual(novo["v"], v)

    def test_simular_uma_noite(self):
        r = self.cliente(GESTAO).get("/api/simular?dia=terça&motoboys=3&jeito=dois")
        self.assertEqual(r.status_code, 200)
        self.assertIn("tempo_medio", r.get_json()["resumo"])
        self.assertEqual(self.cliente(GESTAO).get("/api/simular?motoboys=99").status_code, 400)

    def test_despacho_pedido_chega_e_ganha_motoboy(self):
        c = self.cliente(LOJA)
        A = "/api/despacho/real"
        self.assertEqual(c.get("/despacho").status_code, 200)
        self.assertEqual(c.get("/despacho/treino").status_code, 200)
        self.assertEqual(c.post(A + "/moto", json={"nome": "Alan"}).status_code, 200)
        self.assertEqual(c.post(A + "/moto", json={"nome": "Alan da Silva"}).status_code, 400)
        r = c.post(A + "/pedido", json={"canal": "iFood Burguer", "num": "4821", "bairro": "Boa Vista", "tipo": "lanche"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["pedido"]["moto"], "alan")
        self.assertEqual(c.post(A + "/pedido", json={"canal": "iFood", "bairro": "Lua", "tipo": "x"}).status_code, 400)
        ref = r.get_json()["pedido"]["ref"]
        self.assertEqual(c.post(f"{A}/pronto/{ref}").status_code, 200)
        self.assertEqual(c.post(A + "/moto/alan/saiu").status_code, 200)
        self.assertEqual(c.get(A + "/estado").get_json()["motos"][0]["status"], "rua")
        self.assertEqual(c.post(A + "/moto/alan/voltou").status_code, 200)
        self.assertEqual(c.post(A + "/relogio/avancar", json={"min": 5}).status_code, 404)   # relógio só no treino
        self.assertEqual(c.get(A + "/exportar.xlsx").status_code, 200)
        self.assertEqual(self.cliente().get(A + "/estado").status_code, 401)

    def test_treino_cenario_planilha_e_busca_de_rua(self):
        import io
        c = self.cliente(GESTAO)
        T = "/api/despacho/treino"
        nomes = [x["nome"] for x in c.get("/api/despacho/cenarios").get_json()["cenarios"]]
        self.assertIn("teste-rapido", nomes)
        e = c.post(T + "/cenario", json={"nome": "teste-rapido"}).get_json()
        self.assertEqual(len(e["motos"]), 3)
        self.assertEqual(c.post(T + "/relogio/avancar", json={"min": 60}).status_code, 200)
        self.assertEqual(c.get(T + "/estado").get_json()["resumo"]["entregues"], 4)
        modelo = c.get("/api/despacho/modelo.xlsx")
        self.assertEqual(modelo.status_code, 200)
        r = c.post(T + "/importar", data={"arquivo": (io.BytesIO(modelo.data), "modelo.xlsx")},
                   content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.get_json()["importados"], 4)
        ruas = c.get("/api/mapa/buscar?q=coronel%20renn").get_json()["ruas"]
        self.assertTrue(any("Renno" in x["rua"] for x in ruas))

    def test_cookie_da_loja_nao_vira_gestao(self):
        seg = SEGREDO.encode()
        bom = G.assina(seg, "loja", int(time.time()) + 60)
        self.assertEqual(G.papel_da_sessao(seg, bom), "loja")
        self.assertIsNone(G.papel_da_sessao(seg, bom.replace("loja", "gestao", 1)))
        self.assertIsNone(G.papel_da_sessao(seg, G.assina(seg, "loja", int(time.time()) - 1)))

    def test_senhas_iguais_nao_sobe(self):
        with self.assertRaises(SystemExit):
            G.Config({"GERENCIAL_SENHA_LOJA": LOJA, "GERENCIAL_SENHA_GESTAO": LOJA, "GERENCIAL_SEGREDO": SEGREDO,
                      "ROBO_TOKEN": ROBO})


if __name__ == "__main__":
    unittest.main()
