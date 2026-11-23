import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generate_numbers as gen
import wikipedia_ja as wiki


class WikipediaIssueWeightTests(unittest.TestCase):
    def test_failed_refresh_keeps_both_cached_selections(self):
        cases = [
            ("properties", wiki.load_or_build_wikipedia_property_sentence_sets_for_numbers,
             "extract_property_candidate_sentences_from_title"),
            ("others", wiki.load_or_build_wikipedia_other_item_sets_for_numbers,
             "extract_other_candidate_items_from_title"),
        ]
        for key, load, extract in cases:
            with self.subTest(key=key), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "section.json"
                cached = {key: {"555": ["current"]}, key + "_legacy": {"555": ["legacy"]}}
                path.write_text(json.dumps(cached), encoding="utf-8")
                with patch.object(wiki, extract, side_effect=RuntimeError("fetch failed")):
                    current, legacy = load(path, refresh=True, numbers=[555, 556])
                self.assertEqual(current, {555: ["current"]})
                self.assertEqual(legacy, {555: ["legacy"]})
                self.assertEqual(load(path, refresh=False, numbers=[555, 556], offline=True), (current, legacy))

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
