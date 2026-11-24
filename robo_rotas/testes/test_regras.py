"""As regras da reunião 13, uma por teste. `python -m unittest discover robo_rotas/testes`."""
import unittest
from datetime import datetime

from robo_rotas.regras import Motoboy, Pedido, para_tela, sugerir

LOJA = (-22.4256, -45.4528)
PERTO = (-22.4300, -45.4600)      # ~1 km da loja
PERTO_2 = (-22.4305, -45.4605)    # vizinho do PERTO (~80 m)
PERTO_3 = (-22.4298, -45.4590)
LONGE = (-22.4000, -45.4200)      # ~4,5 km, outro lado da cidade
OPOSTO = (-22.4212, -45.4456)     # ~1 km da loja, no sentido contrário do PERTO


def ped(ref, onde, pronto=0, prazo=40, **kw):
    return Pedido(ref, onde[0], onde[1], pronto, prazo, **kw)


def grupos(saidas):
    return sorted(sorted(p.ref for p in r.paradas) for r in saidas.values())


class Regras(unittest.TestCase):
    def test_um_pedido_por_motoboy_parado(self):
        s, sem = sugerir([ped("a", PERTO), ped("b", PERTO_2)], [Motoboy("Alan"), Motoboy("Beto")], LOJA)
        self.assertEqual(grupos(s), [["a"], ["b"]])
        self.assertEqual(sem, [])

    def test_dois_quando_ninguem_esta_parado(self):
        s, _ = sugerir([ped("a", PERTO), ped("b", PERTO_2)], [Motoboy("Alan"), Motoboy("Beto", livre_em=30)], LOJA)
        self.assertEqual(grupos(s), [["a", "b"]])

    def test_nao_junta_se_o_proximo_volta_logo(self):
        s, _ = sugerir([ped("a", PERTO), ped("b", PERTO_2)], [Motoboy("Alan"), Motoboy("Beto", livre_em=4)], LOJA)
        self.assertEqual(grupos(s), [["a"], ["b"]])

    def test_lanche_nao_vai_com_bebida_grande(self):
        p = [ped("lanche", PERTO, comida=True), ped("litrao", PERTO_2, gelado=True, peso=0.5)]
        s, sem = sugerir(p, [Motoboy("Alan")], LOJA)
        self.assertEqual(grupos(s), [["lanche"]] if s["Alan"].paradas[0].ref == "lanche" else [["litrao"]])
        self.assertEqual(len(sem), 1)

    def test_lanche_vai_com_bebida_pequena_em_cima(self):
        p = [ped("lanche", PERTO, comida=True), ped("long", PERTO_2, gelado=True, pequeno=True)]
        s, _ = sugerir(p, [Motoboy("Alan")], LOJA)
        self.assertEqual(grupos(s), [["lanche", "long"]])
        self.assertTrue(para_tela(s, [Motoboy("Alan")], datetime(2026, 11, 14, 20, 0))[0]["gelado_em_cima"])

    def test_duas_caixas_de_litrao_vao_sozinhas(self):
        p = [ped("caixas", PERTO, peso=2.0), ped("lata", PERTO_2, pequeno=True, peso=0.1)]
        s, sem = sugerir(p, [Motoboy("Alan")], LOJA)
        self.assertEqual(sum(len(r.paradas) for r in s.values()), 1)
        self.assertEqual(len(sem), 1)

    def test_tres_so_com_as_paradas_juntas(self):
        motos = [Motoboy("Alan")]
        s, sem = sugerir([ped("a", PERTO), ped("b", PERTO_2), ped("c", PERTO_3)], motos, LOJA)
        self.assertEqual(grupos(s), [["a", "b", "c"]])
        s, sem = sugerir([ped("a", PERTO), ped("b", PERTO_2), ped("c", LONGE, prazo=90)], motos, LOJA)
        self.assertEqual(max(len(r.paradas) for r in s.values()), 2)
        self.assertEqual([p.ref for p in sem], ["c"])

    def test_juntar_nao_atrasa_quem_ja_estava_na_saida(self):
        # "a" chega em ~6 min com prazo de 7; "b" fica do outro lado da loja e também está apertado
        p = [ped("a", PERTO, prazo=7), ped("b", OPOSTO, prazo=7.5)]
        s, _ = sugerir(p, [Motoboy("Alan"), Motoboy("Beto", livre_em=25)], LOJA)
        for r in s.values():
            for q, atraso in zip(r.paradas, r.atrasos):
                if q.ref == "a":
                    self.assertEqual(atraso, 0)

    def test_motoboy_fora_da_loja_nao_entra(self):
        s, sem = sugerir([ped("a", PERTO)], [Motoboy("Alan", fora=True)], LOJA)
        self.assertEqual(s, {})
        self.assertEqual([p.ref for p in sem], ["a"])

    def test_formato_da_tela(self):
        motos = [Motoboy("Alan", cor=2), Motoboy("Beto", livre_em=8)]
        s, _ = sugerir([ped("a", PERTO, pronto=5), ped("b", LONGE, prazo=90)], motos, LOJA)
        tela = para_tela(s, motos, datetime(2026, 11, 14, 20, 0))
        self.assertEqual([x["quando"] for x in tela], ["espera", "depois"])
        self.assertEqual(tela[0]["sai"], "20:05")
        self.assertEqual(set(tela[0]), {"moto", "cor", "quando", "sai", "livre", "volta", "min", "gelado_em_cima", "paradas"})


if __name__ == "__main__":
    unittest.main()
