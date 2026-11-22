"""生成器と同じ入口で、旧キャッシュの整形と既に区切られた TeX を検証する。"""
import unittest

from wikipedia_quote_math import format_quote


class WikipediaQuoteMathTest(unittest.TestCase):
    def test_text_and_numbered_formula(self):
        self.assertEqual(format_quote("約数は 1, 2, 3 である。", 140),
                         ("約数は 1, 2, 3 である。", False, False))
        self.assertEqual(format_quote("715 = 714と715はルース＝アーロン・ペア。", 140),
                         ("714と715はルース＝アーロン・ペア。", False, False))
        self.assertEqual(format_quote("400 = 100_(20) (ただし基数は20)。", 140)[0],
                         "$400 = 100_{20}$ (ただし基数は20)。")

    def test_equation_boundaries(self):
        self.assertEqual(format_quote("例は 12 = 2^2 × (2^1 + 1) n = 1 のとき。", 140)[0],
                         r"例は $12 = 2^{2} \times (2^{1} + 1)$ $n = 1$ のとき。")
        self.assertEqual(format_quote("18^3 = 5832 , 18^4 = 104976 である。", 140)[0],
                         "$18^{3} = 5832$ , $18^{4} = 104976$ である。")
        self.assertEqual(format_quote("これは 3^2 + 4^2 = 5^2 5^2 + 12^2 = 13^2。", 140)[0],
                         "これは $3^{2} + 4^{2} = 5^{2}$ $5^{2} + 12^{2} = 13^{2}$。")

    def test_entities_and_prime_factorial(self):
        self.assertEqual(format_quote("11# &amp;minus; 1 = 2309、n# を使う。", 140)[0],
                         r"$11\# - 1 = 2309$、$n\#$ を使う。")
        self.assertEqual(format_quote("√e は平方根。", 140)[0], r"$\sqrt{e}$ は平方根。")

    def test_flattened_exponents_need_arithmetic_evidence(self):
        self.assertEqual(format_quote("715 = 3 2 + 9 2 + 25 2 3つの平方数。", 140)[0],
                         "$715 = 3^{2} + 9^{2} + 25^{2}$ 3つの平方数。")
        self.assertEqual(format_quote("625 2 = 390625 と下4桁が一致する。", 140)[0],
                         "$625^{2} = 390625$ と下4桁が一致する。")
        a = "42 = (-80538738812075974) 3 + 80435758145817515 3 + 12602123297335631 3"
        self.assertEqual(format_quote(a, 140)[0],
                         "$42 = (-80538738812075974)^{3} + 80435758145817515^{3} + 12602123297335631^{3}$")

    def test_damaged_fraction_keeps_independent_equation(self):
        rendered, changed, shortened = format_quote("38 = ( )^2 + ( )^2 38 = 1^2 + 1^2 + 6^2。", 140)
        self.assertEqual(rendered, "… $38 = 1^{2} + 1^{2} + 6^{2}$。")
        self.assertTrue(changed and shortened)
        self.assertEqual(format_quote("14! − 1 = 87178291199 = 0.0 … (下線部は循環節)", 140)[0],
                         "$14! - 1 = 87178291199$…")
        self.assertIsNone(format_quote("259 = n = 5 のときの の値とみたとき1つ前は31。", 140))
        self.assertIsNone(format_quote("715 = 714。", 140))

    def test_preserve_explicit_source_tex(self):
        for source in (r"$[0,1)$", r"$f()=1$", r"$x=-2^{-(n+1)}$", r"$a=b=0.00\underline{9}\ldots$",
                       r"$\begin{pmatrix} 2 & 9 \\ 1 & 8 \end{pmatrix}$", r"$2^{2n}=4^n$"):
            with self.subTest(source=source):
                self.assertEqual(format_quote(source, len(source)-2), (source, True, False))
        self.assertEqual(format_quote(r"高さ $x$ = $\sqrt{9}$。", 140)[0], r"高さ $x = \sqrt{9}$。")

    def test_budget_never_cuts_a_formula(self):
        quote = "参考。$\\frac{1234}{5678}$ という例。"
        self.assertNotIn("\\frac", format_quote(quote, 7)[0])
        self.assertEqual(format_quote("$x$。", 2), ("$x$。", True, False))
        self.assertEqual(format_quote("1 = 1 = 1 = 1", 5), ("$1 = 1$…", True, True))

    def test_delimiters_and_decimal_chain(self):
        self.assertEqual(format_quote("価格は$5です。", 140), ("価格は$5です。", False, False))
        self.assertEqual(format_quote("前文。$x^2 + 1。後文。", 140), ("前文。…。後文。", False, True))
        self.assertIsNone(format_quote(r"$\frac{1}{2", 140))
        self.assertEqual(format_quote("1/2 = 2/4 = 0.5", 140)[0], "$1/2 = 2/4 = 0.5$")

    def test_table_markup(self):
        self.assertIsNone(format_quote('{| class="wikitable" | 1 |}', 140))
        self.assertEqual(format_quote('{| class="wikitable" |7^2 |} 7の累乗は循環する。', 140),
                         ("… 7の累乗は循環する。", False, True))

    def test_titles_units_and_annotations(self):
        for text in ("キャッチ=22（1961年）から由来。", "281_Anti nukeは活動家。",
                     "フェラーリ・400#412 - 乗用車の車種。", "第501＝第503戦車連隊。",
                     "(730 = 365日 × 2年)。", "1ハロン=220ヤード。", "720° = 2周。"):
            with self.subTest(text=text):
                self.assertEqual(format_quote(text, 160), (text, False, False))
        self.assertEqual(format_quote("画面は320×240 (QVGA)。", 160)[0],
                         r"画面は$320\times 240$ (QVGA)。")
        self.assertEqual(format_quote("敷地面積は880Km^2である。", 160)[0],
                         "敷地面積は$880Km^{2}$である。")
        self.assertEqual(format_quote("上限は255（=2 8 -1）である。", 160)[0],
                         "上限は255（$=2^{8} -1$）である。")


if __name__ == "__main__":
    unittest.main()
