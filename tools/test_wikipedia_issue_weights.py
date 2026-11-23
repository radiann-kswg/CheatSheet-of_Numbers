import unittest

import generate_numbers as gen
import wikipedia_ja as wiki


class WikipediaIssueWeightTests(unittest.TestCase):
    def test_specific_topics_need_the_right_number_and_section(self):
        cases = [
            (717, "property", "717は二進法でも回文となる。", True),
            (717, "property", "717の素因数には239がある。", False),
            (109, "property", "逆数をフィボナッチ数の交代和で表す。", True),
            (109, "property", "フィボナッチ多項式の値。", False),
            (62, "other", "62系の非同期sram。", True),
            (62, "other", "テレビ局の62チャネル。", False),
            (555, "other", "仮面ライダー555。", False),
            (555, "property", "NE555", False),
            (554, "other", "NE555", False),
        ]
        for number, kind, text, matches in cases:
            with self.subTest(number=number, text=text):
                self.assertEqual(wiki.issue_quote_bonus(number, kind, text) > 0, matches)

    def test_new_candidates_cross_the_cutoff_and_manual_pins_keep_priority(self):
        show = "555を題名に含むテレビ番組・映画・漫画で長く親しまれている。"
        timer = "NE555は時間を計るための集積回路。"
        source = show + "\n" + timer
        extract = wiki.extract_other_candidate_items_from_plain_text
        self.assertEqual(extract(source, max_candidates=1), [show])
        self.assertEqual(extract(source, max_candidates=1, n=555), [timer])
        scoring = dict(term_freq={}, searchhits_cache={}, offline=True, limit=1, threshold=30, kind="other")
        self.assertEqual(wiki._select_by_importance([show, timer], n=555, **scoring), [timer])
        self.assertEqual(wiki._select_by_importance([show, timer], n=555, pinned_substrings=["テレビ番組"], **scoring), [show])

    def test_cached_quotes_keep_their_source_and_stable_order(self):
        first, second = "映画の555。", "鉄道の555。"
        timer, other_timer = "NE555の説明。", "555タイマーの名称。"
        original = [first, second, timer, other_timer]
        self.assertEqual(gen._prioritize_cached_quotes(original, 555, "other", []), [timer, other_timer, first, second])
        self.assertEqual(gen._prioritize_cached_quotes(original, 555, "other", ["鉄道"]), [second, timer, other_timer, first])
        self.assertEqual(gen._prioritize_cached_quotes(original, 554, "other", ["鉄道"]), original)


if __name__ == "__main__":
    unittest.main()
