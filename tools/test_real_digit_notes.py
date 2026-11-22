import json
import math
import unittest
from pathlib import Path

import build_viewer_index as viewer
import generate_numbers as gen
from real_digit_notes import build_real_digit_notes


def constant(decimal, name="検算用の値"):
    return {
        "name": name,
        "symbol": "x",
        "decimal": decimal,
        "description": "桁を検算する。",
        "sources": {"検算用": "https://example.org/"},
    }


class RealDigitNoteTests(unittest.TestCase):
    def test_catalog_values_and_page_numbers_for_pi_e_and_ln3(self):
        catalog = Path(__file__).with_name("real_constants_v1.json")
        entries = json.loads(catalog.read_text(encoding="utf-8"))["constants"]
        constants = {entry["symbol"]: entry for entry in entries}
        cases = [
            ("π", math.pi, {"314"}),
            ("e", math.e, {"271", "272"}),
            ("ln 3", math.log(3), {"109", "110", "1098", "1099"}),
        ]
        for symbol, value, pages in cases:
            with self.subTest(symbol=symbol):
                entry = constants[symbol]
                self.assertAlmostEqual(float(entry["decimal"]), value, places=13)
                self.assertEqual(set(build_real_digit_notes([entry], 1188)), pages)

    def test_pi_is_in_both_the_number_page_and_viewer_search(self):
        page = gen.render_number_page(gen.build_info(314), None, None, None, None, None, None)
        search = viewer._build_record(314, {})["searchText"]
        for term in ["実数の数字列", "円周率", "π", "3141", "3.142"]:
            with self.subTest(term=term):
                self.assertIn(term, page)
                self.assertIn(term, search)

    def test_leading_zeroes_trailing_zeroes_and_half_up_tie(self):
        notes = build_real_digit_notes([constant("0.00100450000000")], 1188)
        self.assertEqual(set(notes), {"100", "1004", "1005"})
        self.assertRegex(notes["100"][0]["text"], r"0\.00100(?!\d)")
        self.assertRegex(notes["1005"][0]["text"], r"0\.001005(?!\d)")

    def test_rounding_carries_across_a_power_of_ten(self):
        notes = build_real_digit_notes([constant("9.99969000000000")], 9999)
        self.assertEqual(set(notes), {"999", "9999", "100", "1000"})
        self.assertRegex(notes["100"][0]["text"], r"10\.0(?!\d)")
        self.assertRegex(notes["1000"][0]["text"], r"10\.00(?!\d)")

    def test_negative_value_keeps_its_sign_in_display_only(self):
        notes = build_real_digit_notes([constant("-0.6180339887498948")], 9999)
        self.assertEqual(set(notes), {"618", "6180"})
        text = notes["618"][0]["text"]
        self.assertIn("-0.618033", text)
        self.assertRegex(text, r"-0\.618(?!\d)")
        self.assertRegex(text, r"-0\.6180(?!\d)")

    def test_invalid_catalog_expansions(self):
        for invalid in ["0", "3.14", "0.0001234", "1.23456e2"]:
            with self.subTest(decimal=invalid), self.assertRaises(ValueError):
                build_real_digit_notes([constant(invalid)], 1188)

    def test_include_the_last_page_and_keep_distinct_constants_on_it(self):
        first = constant("1.18864000000000", "一つ目")
        second = constant("1.18830000000000", "二つ目")
        notes = build_real_digit_notes([first, second], 1188)
        self.assertEqual(set(notes), {"118", "119", "1188"})
        self.assertEqual(len(notes["1188"]), 2)
        for entry in [first, second]:
            matched = [note for note in notes["1188"] if entry["name"] in note["title"]]
            self.assertEqual(len(matched), 1)
            self.assertEqual(matched[0]["sources"], entry["sources"])


if __name__ == "__main__":
    unittest.main()
