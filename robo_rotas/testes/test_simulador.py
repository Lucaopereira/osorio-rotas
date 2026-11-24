"""O simulador respeita as regras em toda saída, e a mesma semente dá a mesma noite."""
import unittest

from robo_rotas import regras, simulador as S
from robo_rotas.regras import Motoboy, Pedido, sugerir

LOJA = (-22.4187, -45.4540)


class Simulador(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pedidos = S.gerar_pedidos("sexta", 18, 25, 3)
        cls.noites = {(n, p): S.simular(cls.pedidos, n, p, 3) for n in (2, 4) for p in ("um", "dois", "tres", "hoje")}

    def test_toda_saida_respeita_as_regras(self):
        for (n, pol), noite in self.noites.items():
            if pol == "hoje":
                continue
            por_ref = {p.ref: p for p in noite.pedidos}
            limite = S.POLITICAS[pol][1]
            for s in noite.saidas:
                grupo = [por_ref[r] for r in s["refs"]]
                self.assertLessEqual(len(grupo), limite, (n, pol, s))
                self.assertLessEqual(sum(p.peso for p in grupo), regras.PESO_MAX + 1e-9)
                comida = any(p.comida for p in grupo)
                grande = any(not p.comida and not p.pequeno for p in grupo)
                self.assertFalse(comida and grande, f"misturou lanche com bebida grande: {n} {pol} {s}")

    def test_ninguem_sai_antes_de_ficar_pronto_e_todos_chegam(self):
        for noite in self.noites.values():
            for p in noite.pedidos:
                self.assertIsNotNone(p.chegou)
                self.assertGreaterEqual(p.saiu + 1e-9, p.pronto)
                self.assertGreater(p.chegou, p.saiu)

    def test_mesma_semente_mesma_noite(self):
        a = S.resumo(S.simular(self.pedidos, 4, "dois", 3))
        b = S.resumo(S.simular(S.gerar_pedidos("sexta", 18, 25, 3), 4, "dois", 3))
        self.assertEqual(a, b)

    def test_avisado_na_chegada_fica_com_o_pedido(self):
        r = S.resumo(self.noites[(4, "dois")])
        self.assertGreater(r["pct_manteve_sugestao"], 90)


class Fixos(unittest.TestCase):
    def test_pedido_fixado_fica_com_o_motoboy_dele(self):
        perto = (-22.4230, -45.4600)
        ps = [Pedido("a", *perto, 0, 40), Pedido("b", -22.4232, -45.4602, 0, 40)]
        s, _ = sugerir(ps, [Motoboy("Alan"), Motoboy("Beto", livre_em=15)], LOJA, fixos={"a": "Beto"})
        self.assertEqual([p.ref for p in s["Beto"].paradas], ["a"])
        self.assertEqual([p.ref for p in s["Alan"].paradas], ["b"])

    def test_fixado_em_quem_nao_esta_no_turno_volta_para_a_fila(self):
        s, _ = sugerir([Pedido("a", -22.4230, -45.4600, 0, 40)], [Motoboy("Alan")], LOJA, fixos={"a": "Ze"})
        self.assertEqual([p.ref for p in s["Alan"].paradas], ["a"])


if __name__ == "__main__":
    unittest.main()
