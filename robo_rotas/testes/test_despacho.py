"""Despacho em tempo real: pedido chega e ganha motoboy, endereço, modos, cenário, piloto, troca manual e planilha."""
import os
import tempfile
import unittest

from robo_rotas import cenarios, despacho as D, mapa, servidor


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.banco = servidor.Banco(os.path.join(self.tmp.name, "t.db"))
        self.d = D.Despacho(self.banco, "treino")

    def tearDown(self):
        self.banco.con.close()
        self.tmp.cleanup()


class Regras(Base):
    def test_um_pedido_por_motoboy_parado(self):
        for n in ("Alan", "Beto"):
            self.d.novo_motoboy(n)
        a = self.d.novo_pedido("iFood Burguer", "1", "lanche", bairro="Centro")["pedido"]
        b = self.d.novo_pedido("iFood Burguer", "2", "lanche", bairro="Centro")["pedido"]
        self.assertNotEqual(a["moto"], b["moto"])
        self.assertTrue(a["moto"] and b["moto"])

    def test_lanche_nao_vai_com_bebida_grande(self):
        self.d.novo_motoboy("Alan")
        self.d.novo_pedido("iFood Burguer", "1", "lanche", bairro="Centro")
        caixa = self.d.novo_pedido("Zé", "2", "uma caixa de litrão", bairro="Centro")["pedido"]
        self.assertIsNone(caixa["moto"])
        self.assertTrue(caixa["sem_motoboy"])

    def test_no_maximo_dois_por_saida(self):
        self.d.novo_motoboy("Alan")
        for i in range(3):
            self.d.novo_pedido("Zé", str(i), "poucas latas", bairro="Centro")
        self.assertLessEqual(len(self.d.estado()["saidas"]["alan"]["paradas"]), 2)

    def test_loja_troca_o_motoboy_na_mao_e_o_robo_respeita(self):
        for n in ("Alan", "Beto"):
            self.d.novo_motoboy(n)
        p = self.d.novo_pedido("iFood Burguer", "1", "lanche", bairro="Centro")["pedido"]
        outro = "beto" if p["moto"] == "alan" else "alan"
        self.d.fixar(p["ref"], outro)
        e = self.d.estado()
        q = next(x for x in e["pedidos"] if x["ref"] == p["ref"])
        self.assertEqual((q["moto"], q["manual"]), (outro, True))
        self.d.fixar(p["ref"], None)
        self.assertFalse(next(x for x in self.d.estado()["pedidos"] if x["ref"] == p["ref"])["manual"])

    def test_saiu_e_volta_sozinho_na_hora_prevista(self):
        self.d.novo_motoboy("Alan")
        p = self.d.novo_pedido("Zé", "1", "fardo ou garrafas", bairro="Pinheirinho")["pedido"]
        with self.assertRaises(D.ErroDespacho):
            self.d.saiu("alan")                     # ainda não está pronto
        self.d.marcar_pronto(p["ref"])
        self.d.saiu("alan")
        self.assertEqual(self.d.estado()["motos"][0]["status"], "rua")
        self.d.avancar(30)
        e = self.d.estado()
        self.assertEqual(e["motos"][0]["status"], "loja")
        self.assertEqual(e["pedidos"][0]["status"], "entregue")
        self.assertEqual(e["resumo"]["entregues"], 1)


@unittest.skipUnless(mapa.carregar(), "sem o arquivo das ruas")
class Endereco(Base):
    def test_rua_com_numero_vira_ponto_na_rua(self):
        self.d.novo_motoboy("Alan")
        r = self.d.novo_pedido("WhatsApp", "1", "lanche", endereco="R. Cel. Rennó, 210")
        p = r["pedido"]
        self.assertEqual((p["rua"], p["numero"], p["precisao"], p["bairro"]), ("Rua Coronel Renno", "210", "rua", "Pinheirinho"))
        self.assertIsNone(r["aviso"])

    def test_localizacao_colada_do_whatsapp(self):
        p = self.d.novo_pedido("WhatsApp", "1", "lanche", endereco="https://maps.google.com/?q=-22.4290,-45.4620")["pedido"]
        self.assertEqual(p["precisao"], "ponto")
        self.assertAlmostEqual(p["lat"], -22.429)

    def test_rua_desconhecida_cai_no_bairro_com_aviso(self):
        r = self.d.novo_pedido("Zé", "1", "poucas latas", endereco="Rua que não existe", bairro="Medicina")
        self.assertEqual(r["pedido"]["precisao"], "bairro")
        self.assertTrue(r["aviso"])

    def test_sem_rua_e_sem_bairro_recusa(self):
        with self.assertRaises(D.ErroDespacho):
            self.d.novo_pedido("Zé", "1", "poucas latas", endereco="Rua que não existe")

    def test_rota_pelas_ruas_e_maior_que_a_reta(self):
        M = mapa.carregar()
        a, b = (-22.4187, -45.4540), (-22.4413, -45.4373)
        self.assertGreater(M.km(a, b), mapa._metros(a, b) / 1000)
        self.assertGreater(len(M.caminho(a, b)), 5)


class Modos(Base):
    def test_real_e_treino_nao_se_misturam(self):
        real = D.Despacho(self.banco, "real")
        real.novo_motoboy("Alan")
        self.d.novo_motoboy("Beto")
        self.assertEqual([m["nome"] for m in real.estado()["motos"]], ["Alan"])
        self.assertEqual([m["nome"] for m in self.d.estado()["motos"]], ["Beto"])
        with self.assertRaises(D.ErroDespacho):
            real.avancar(5)

    def test_cenario_chega_no_horario_e_piloto_entrega_tudo(self):
        self.d.carregar_cenario(cenarios.TESTE_RAPIDO)
        e = self.d.estado()
        self.assertEqual(len(e["motos"]), 3)
        self.assertEqual(e["cenario"]["chegaram"], 2)          # dois pedidos no minuto zero
        self.d.avancar(90)
        e = self.d.estado()
        self.assertEqual(e["cenario"]["chegaram"], 4)
        self.assertTrue(e["cenario"]["fim"])
        self.assertEqual(e["resumo"]["entregues"], 4)
        self.assertLess(e["resumo"]["espera_media"], 5)       # anda minuto a minuto: ninguém espera o pulo do relógio

    def test_exportar_tem_uma_linha_por_pedido(self):
        self.d.novo_motoboy("Alan")
        self.d.novo_pedido("Zé", "9", "poucas latas", bairro="Centro")
        linhas = self.d.exportar()
        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["Canal"], "Zé")


class Planilha(unittest.TestCase):
    def test_le_planilha_com_apelidos_e_aponta_linha_ruim(self):
        linhas = [{"Hora": "19:02", "Canal": "ifood", "Número": "4821", "Endereço": "", "Bairro": "Centro", "Tipo": "Lanche"},
                  {"Hora": "19:10", "Canal": "zé", "Número": "7710", "Endereço": "", "Bairro": "Bps", "Tipo": "1 caixa"},
                  {"Hora": "x", "Canal": "zé", "Número": "1", "Endereço": "", "Bairro": "Centro", "Tipo": "latas"},
                  {"Hora": "19:20", "Canal": "Site", "Número": "2", "Endereço": "", "Bairro": "Lua", "Tipo": "lanche"}]
        cen, problemas = D.ler_planilha(linhas)
        self.assertEqual([(q["canal"], q["tipo"], q["t"]) for q in cen["pedidos"]],
                         [("iFood Burguer", "lanche", 0), ("Zé", "uma caixa de litrão", 8)])
        self.assertEqual(cen["inicio"], "19:02")
        self.assertEqual(len(problemas), 2)


if __name__ == "__main__":
    unittest.main()
