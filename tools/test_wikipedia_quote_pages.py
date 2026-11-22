import re
import unittest

import generate_numbers as gen


class WikipediaQuotePageTests(unittest.TestCase):
    def test_only_the_damaged_cache_entry_uses_the_verified_revision(self):
        damaged = "( ) 625 = 2^−4 × 10^4 625 × 10^−4 = = = 0.0625 = 0.0016 逆数が有限小数になる25番目の数である。"
        fresh = r"$\frac{1}{625}=0.0016$。"
        lines = gen._wikipedia_quote_lines([damaged, fresh], 625, "性質")
        self.assertTrue(any("0.0625" in line and "oldid=" in line for line in lines))
        self.assertTrue(any("0.0016" in line and "oldid=" in line for line in lines))
        self.assertFalse(any("0.0625" in line and "0.0016" in line for line in lines))
        self.assertIn("短い引用・整形", lines[-1])
        self.assertNotIn("oldid=", lines[-1])

    def test_all_verified_excerpts_have_usable_text_and_unique_cache_keys(self):
        for n, source in gen._verified_wikipedia_quotes().items():
            self.assertGreater(source["revision"], 0)
            keys = set()
            for repair in source["repairs"]:
                with self.subTest(n=n, match=repair["match"]):
                    self.assertRegex(repair["sha256"], r"^[0-9a-f]{64}$")
                    self.assertNotIn(repair["sha256"], keys)
                    keys.add(repair["sha256"])
                    self.assertTrue(repair["quotes"])
                    limit = 160 if repair.get("section") == "その他" else 140
                    for text in repair["quotes"]:
                        rendered = gen.format_quote(text, limit)
                        self.assertIsNotNone(rendered)
                        for formula in re.findall(r"\$[^$]+\$", text):
                            self.assertIn(formula, rendered[0])


if __name__ == "__main__":
    unittest.main()
