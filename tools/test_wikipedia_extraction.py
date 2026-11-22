import unittest
from unittest.mock import patch

import wikipedia_ja as wiki


class WikipediaMathExtractionTests(unittest.TestCase):
    def test_nested_fraction_templates_stay_on_their_own_list_items(self):
        source = (
            "* 625 × 10{{sup|&minus;4}} = {{sfrac|1|2{{sup|4}}}} = 0.0625\n"
            "* {{sfrac|1|625}} = 0.0016"
        )
        expected = {
            r"625 × 10^{−4} = \frac{1}{2^{4}} = 0.0625。",
            r"\frac{1}{625} = 0.0016。",
        }
        with patch.object(wiki, "fetch_sections", return_value=[wiki.WikipediaSection("1", "性質")]), \
             patch.object(wiki, "fetch_section_wikitext", return_value=source):
            self.assertEqual(set(wiki.extract_property_candidate_sentences_from_title("625")), expected)
            self.assertEqual(set(wiki.extract_property_sentences_from_title("625")), expected)

    def test_mathematical_markup_survives_wiki_cleanup(self):
        tex = r"1-\frac{{}_{365}\mathrm{P}_{23}}{365^{23}}"
        source = f"確率は <math>{tex}\n&amp;gt; 0</math> であり [[1/2|{{{{sfrac|1|2}}}}]] を超える。"
        expected = f"確率は ${tex} > 0$ であり " + r"\frac{1}{2} を超える。"
        self.assertEqual(wiki.wikitext_to_plain_text(source), expected)

    def test_tex_punctuation_does_not_split_sentences(self):
        source = r"* <math>\text{文中。の点} = 2</math> を含む長い文。独立した文化の説明の例をここに記す。"
        text = wiki.wikitext_to_plain_text_keep_newlines(source)
        expected = {r"$\text{文中。の点} = 2$ を含む長い文。", "独立した文化の説明の例をここに記す。"}
        self.assertEqual(set(wiki.extract_other_candidate_items_from_plain_text(text)), expected)
        self.assertEqual(set(wiki.extract_other_items_from_plain_text(text)), expected)

    def test_html_exponents_subscripts_and_double_escaped_entities(self):
        source = "* (−2)<sup>3</sup> &amp;times; F<sub>12</sub> &amp;minus; 1"
        self.assertEqual(wiki.wikitext_to_plain_text(source), "(−2)^{3} × F_{12} − 1")

    def test_fraction_variants_and_repeating_decimals(self):
        source = "{{frac|5}}、{{分数|3|4}}、{{sfrac|2|1|3}}、0.{{overline|45}}"
        expected = r"\frac{1}{5}、\frac{3}{4}、2\frac{1}{3}、0.\overline{45}"
        self.assertEqual(wiki.wikitext_to_plain_text(source), expected)

    def test_underlined_repeating_digits_in_wiki_and_html(self):
        for digits in (
            "{{underline|714285}}",
            "<u>714285</u>",
            '<span style="text-decoration:underline">714285</span>',
            "<SPAN style='color:blue; text-decoration-line: underline'><u>71</u>4285</SPAN>",
        ):
            with self.subTest(digits=digits):
                expected = (r"0.\underline{\underline{71}4285}" if "color:" in digits else r"0.\underline{714285}")
                self.assertEqual(wiki.wikitext_to_plain_text("0." + digits), expected)
        self.assertEqual(wiki.wikitext_to_plain_text('<span style="color: green">green</span>'), "green")

    def test_fraction_containing_linked_powers(self):
        source = "{{sfrac|[[平方数|2{{sup|3}}]]|[[9|3<sup>2</sup>]]}}"
        self.assertEqual(wiki.wikitext_to_plain_text(source), r"\frac{2^{3}}{3^{2}}")

    def test_tex_text_inequalities_and_array_rows_are_preserved(self):
        source = r"<math>\begin{matrix} x &lt; y \\ \text{左 {{template}}} \end{matrix}</math>"
        expected = r"$\begin{matrix} x < y \\ \text{左 {{template}}} \end{matrix}$"
        self.assertEqual(wiki.wikitext_to_plain_text(source), expected)

    def test_damaged_math_does_not_leak_into_adjacent_prose(self):
        source = (
            "* 10 = {{未対応のテンプレート|1|2}} + 9\n"
            "* 99 = 2<sup></sup>\n"
            "* <math>5 + 2\n途中の式を含めない\n"
            "* 続く完結した <math>2+2</math> は別の項目。\n"
            "* [[''作品''|音楽作品]]の刊行年。<ref name=\"a\" />\n"
            "* 4 = 2 + 2 （{{OEIS|A000290}}）"
        )
        text = wiki.wikitext_to_plain_text_keep_newlines(source)
        self.assertEqual(text.splitlines(), ["続く完結した $2+2$ は別の項目。", "音楽作品の刊行年。", "4 = 2 + 2 （ ）"])


if __name__ == "__main__":
    unittest.main()
