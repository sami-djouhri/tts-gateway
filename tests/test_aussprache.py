import unittest

from app.aussprache import aussprechbar


class AusspracheTest(unittest.TestCase):
    def test_bekannte_woerter_werden_umgeschrieben(self):
        self.assertEqual(aussprechbar("Trump trifft die IT-Branche"), "Trampp trifft die Ei Tie-Branche")
        self.assertEqual(aussprechbar("Neues Update in New York."), "Neues Apdäit in Nju York.")

    def test_nur_ganze_woerter_und_genaue_schreibweise(self):
        # „it" klein, „Teamarbeit" als Wortteil und „Trumpf" bleiben unberuehrt.
        self.assertEqual(aussprechbar("let it be, Teamarbeit, Trumpf"), "let it be, Teamarbeit, Trumpf")

    def test_bindestrich_zaehlt_als_wortteil(self):
        # „Cloud-Dienst" ja (Wortgrenze vor dem Bindestrich), „E-Cloud" nicht.
        self.assertEqual(aussprechbar("Cloud-Dienst"), "Klaud-Dienst")
        self.assertEqual(aussprechbar("E-Cloud"), "E-Cloud")

    def test_nur_fuer_deutsch(self):
        self.assertEqual(aussprechbar("Trump", "en"), "Trump")
        self.assertEqual(aussprechbar("Trump", "de-DE"), "Trampp")
        self.assertEqual(aussprechbar("Trump", None), "Trampp")
        self.assertEqual(aussprechbar("", "de"), "")


if __name__ == "__main__":
    unittest.main()
