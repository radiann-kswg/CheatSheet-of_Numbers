import json
import unittest

import build_viewer_index as viewer
import generate_numbers as gen


class IssueLoreTests(unittest.TestCase):
    def test_published_issue_and_ic_filters_select_the_relevant_pages(self):
        index = json.loads(viewer.OUTPUT_PATH.read_text(encoding="utf-8"))
        records = index["numbers"]
        expected = {
            "6": {717},
            "7": {8, 89, 109, 112, 144, 377, 1094, 1123, 1124, 1154, 1176, 1187, 1188},
            "8": {24, 25, 27, 28, 62, 74, 78, 79, 93, 555, 556, 831, 832, 834, 838},
            "9": {17, 19, 59, 61, 179, 181, 821, 823, 1019, 1021},
            "10": {23, 27, 37, 851},
            "11": {159, 282, 392, 496, 497},
        }
        for issue, numbers in expected.items():
            with self.subTest(issue=issue):
                matches = {r["n"] for r in records if r.get("issueSnippets", {}).get(issue)}
                self.assertEqual(matches, numbers)
        ic_pages = {r["n"] for r in records if "ic_part_numbers" in r["propertyFilters"]}
        self.assertEqual(ic_pages, expected["8"])

    def test_issue_notes_appear_in_generated_pages_and_search_text(self):
        lore = gen._load_number_lore()
        cases = [
            (717, "6", ("1011001101", "3+239=242")),
            (112, "7", ("89の逆数", "桁上がり")),
            (1123, "7", ("フィボナッチの日", "11月23日")),
            (62, "8", ("CY62128EV30", "AS6C6264", "128 KiB")),
            (181, "9", ("180桁", "ミディの定理", "18回ずつ")),
            (851, "10", ("$12P=(333,537)$", "lcm", "Aitken")),
            (392, "11", ("対数帯域", "**392**", "4(1-e^{-x})")),
        ]
        for number, issue, terms in cases:
            with self.subTest(number=number):
                record = viewer._build_record(number, lore)
                self.assertTrue(record["issueSnippets"][issue])
                page = gen.render_number_page(gen.build_info(number), None, None, None, None, None, None)
                for term in terms:
                    self.assertIn(term, page)
                    self.assertIn(term.lower(), record["searchText"])


if __name__ == "__main__":
    unittest.main()
