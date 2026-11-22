"""Wikipedia の短い引用を、式を途中で切らずに Markdown 用に整える。"""

from __future__ import annotations

import ast
from fractions import Fraction
import html
import re


# 新しい取得結果の $...$ を最優先し、旧キャッシュでは数式に使う文字列だけを拾う。
# 語の一部（例: HOKKAIDO）を変数として拾わない。
_PROTECTED = re.compile("\ue070([0-9]+)\ue071")
_RUN = re.compile(
    r"\\begin\{([a-zA-Z]+)\}.*?\\end\{\1\}|(?:\ue070\d+\ue071|\\(?!begin\{)[A-Za-z]+|\\[!;, #%{}_|]|"
    r"(?:[A-Za-z]+)|[0-9 \t{}()[\]^_#πσφωαβθΣ∞√×÷−–≠≒≤≥≡→⇒±＝＋－=+*/!|.,…･~<>:-])+"
)
_SIGNAL = re.compile(r"[\ue070\\^_=＝√×÷≒≡≤≥≠πσφω]|[A-Za-z0-9]#(?!\d)|[0-9)]\s+[+−]\s+[0-9(]")
_WORD = re.compile(r"(?<![\\A-Za-z])([A-Za-z]{2,})(?![A-Za-z])")
_OPERATORS = re.compile(r"(?:[=＝≒≡≤≥<>+*/×÷^_−–-]|\\(?:times|div|pm|cdot))$")
_MISSING = re.compile(r"(?:^|[=≒+×÷*/−-])\s*(?:\^(?!\d+√)|_)|[=≒]\s*=|[−-]\s*\+\s*[−-]")
# 旧キャッシュで添字か指数か、指数の終端がどこかを判定できない形。
_FLATTENED_SYMBOL = re.compile(r"(?<![A-Za-z\\])[nmkxyzwabe] (?:[0-9]|[nke])\b")
_AMBIGUOUS_POWER = re.compile(r"\^[0-9]+[nm]|(?:\^|_)[nm][+−-]\d+(?=[A-Za-z(×÷])|"
                              r"log_10[0-9]|\) [nm]\s*$")
_SYMBOLS = {
    "×": r"\times ", "÷": r"\div ", "π": r"\pi ", "−": "-", "–": "-",
    "…": r"\ldots ", "≒": r"\approx ", "≠": r"\ne ", "≤": r"\le ",
    "≥": r"\ge ", "≡": r"\equiv ", "∞": r"\infty ", "±": r"\pm ",
    "→": r"\to ", "⇒": r"\Rightarrow ", "＝": "=", "＋": "+", "－": "-",
}
_PAIRS = {"(": ")", "[": "]", "{": "}"}


def _arith(expr: str) -> Fraction:
    """小さい有理数式のみ。巨大な冪・階乗・暗黙の乗算は値から判定しない。"""
    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return Fraction(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            x = value(node.operand)
            return -x if isinstance(node.op, ast.USub) else x
        if not isinstance(node, ast.BinOp):
            raise ValueError
        a, b = value(node.left), value(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            return a / b
        if isinstance(node.op, ast.Pow) and b.denominator == 1 and abs(b) <= 64 and max(
            a.numerator.bit_length(), a.denominator.bit_length()
        ) * max(1, abs(int(b))) < 4096:
            return a ** int(b)
        raise ValueError

    expr = expr.translate(str.maketrans({"−": "-", "–": "-", "×": "*", "÷": "/", "^": "**"}))
    if not re.fullmatch(r"[0-9() +*/.-]{1,300}", expr):
        raise ValueError
    # Decimal literals are exact; retain the original spelling.
    expr = re.sub(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])",
                  lambda m: f"({int(m[1] + m[2])}/{10 ** len(m[2])})", expr)
    return value(ast.parse(expr.strip(), mode="eval").body)


def _equation_status(expr: str, *, require_all=False) -> bool | None:
    parts = expr.split("=")
    if len(parts) < 2:
        return None
    known = []
    for part in parts:
        try:
            known.append(_arith(part))
        except (ValueError, SyntaxError, ArithmeticError, RecursionError):
            if require_all:
                return None
            continue
    if len(known) < 2:
        return None
    return all(x == known[0] for x in known)


def _balanced(expr: str) -> bool:
    stack = []
    for i, char in enumerate(expr):
        if i and expr[i - 1] == "\\":
            continue
        if char in _PAIRS:
            stack.append(_PAIRS[char])
        elif char in ")]}" and (not stack or stack.pop() != char):
            return False
    return not stack and len(re.findall(r"\\left\b", expr)) == len(re.findall(r"\\right\b", expr))


def _latex(expr: str) -> str:
    expr = re.sub(r"(?<!\\)\\{2,}(?=[A-Za-z])", r"\\", expr)
    expr = re.sub(r"\^(\d+)√\s*(\d+)", r"\\sqrt[\1]{\2}", expr)
    expr = re.sub(r"√\s*\\overline\s*\{([^{}]+)\}", r"\\sqrt{\1}", expr)
    expr = re.sub(r"√\s*(\d+|[A-Za-zπ])", r"\\sqrt{\1}", expr)
    expr = expr.replace("･･･", "…").replace("...", "…").translate(str.maketrans(_SYMBOLS))
    expr = re.sub(r"(?<!\\)#", r"\\#", expr)
    expr = re.sub(r"_\((\d+)\)", r"_{\1}", expr)
    expr = re.sub(r"([_^]) *(-?\d+)", r"\1{\2}", expr)
    return re.sub(r" +", " ", expr).strip().replace("{{", "{ {")


def _clip_equation(expr: str, budget: int) -> str:
    """長い連鎖等式は、右辺が完結した等号まで引用する。"""
    for sep in reversed(list(re.finditer(r"(?<![<>])=", expr))):
        prefix = expr[:sep.start()].rstrip()
        if "=" in prefix and len(prefix) <= budget and _balanced(prefix):
            return prefix
    # 無限積を列記した原文は、完結した因子と継続記号までを示す。
    if r"\ldots" in expr or r"\cdots" in expr:
        for m in reversed(list(re.finditer(r"\\right\)\s*(?=\\left\()", expr))):
            prefix = expr[:m.end()].strip()
            if "=" in prefix and len(prefix) + 1 <= budget and _balanced(prefix):
                return prefix + "…"
    return ""


def _split_runs(run: str):
    """日本語説明の括弧・リスト境界を式の外に残す。"""
    # 説明の開き括弧は次の日本語、閉じ括弧は直前の日本語と組になる。
    # 対応する相手がこの区間にある算術用の括弧は保持する。
    start = 0
    opens = []
    cuts = set()
    braces = 0
    for i, c in enumerate(run):
        if c == "(":
            opens.append(i)
        elif c == ")":
            if opens:
                opens.pop()
            else:
                cuts.add(i)
        elif c in "{[":
            braces += 1
        elif c in "}]":
            braces -= 1
        elif c == "," and not opens and not braces:
            if not (i and run[i-1].isdigit() and re.match(r"\d{3}(?!\d)", run[i+1:])):
                cuts.add(i)
    cuts.update(opens)
    # 通常の英単語・文化項目の表題は数式に入れない。
    for m in _WORD.finditer(run):
        if "=" in run and re.fullmatch(r"[IVXLCDM]+", m[1]):
            continue
        if re.match(r"\^\{?-?[0-9]", run[m.end():]) and m[1].lower() in {"km", "cm", "mm", "kg", "ms", "hz"}:
            continue
        if m[1] not in {"lim", "sin", "cos", "tan", "log", "mod", "gcd", "lcm", "frac", "cases"}:
            # \mathrm{P} などの TeX の引数には手を加えない。
            if not (m.start() and run[m.start()-1] == "{"):
                cuts.update(range(m.start(), m.end()))
                if m.start() and run[m.start()-1] == "_":
                    cuts.add(m.start()-1)
                # 寸法に付随する「(QVGA)」等、通常の注記の括弧も本文に残す。
                if run[:m.start()].rstrip().endswith("(") and run[m.end():].lstrip().startswith(")"):
                    cuts.update((run.rfind("(", 0, m.start()), run.index(")", m.end())))
    for i in sorted(cuts):
        if i > start:
            yield run[start:i], True
        yield run[i], False
        start = i + 1
    if start < len(run):
        yield run[start:], True


_FLAT_DIGIT = re.compile(r"((?<![\d_^])\d+|\)) ([0-9]{1,2})(?=\s*(?:[+−–×÷=)-]|$)|\s+[\da-z])")
_NEXT_EXPR = re.compile(
    r"(?<=[\d)}!πσωφ…\ue071])(?= (?:\d|\ue070|[a-zA-Z]\s*(?:[=<>#]| \d\b| [a-z]\b)|\\(?:sigma|sum|frac)\b))"
)


def _formula_parts(run: str):
    """隣り合う式を分け、平坦化した数字の指数は等式を検算できたときに復元する。"""
    # 空白を仮の ^ に替えても文字位置は同じ。検算できない部分には元の文字列を使う。
    trial = _FLAT_DIGIT.sub(r"\1^\2", run)
    start = 0
    for stop in [m.start() for m in _NEXT_EXPR.finditer(trial)] + [len(trial)]:
        fragment = trial[start:stop]
        original = run[start:stop]
        if fragment != original and _equation_status(fragment, require_all=True) is True:
            yield fragment
        else:
            yield original
        start = stop


def format_quote(text: str, limit: int) -> tuple[str, bool, bool] | None:
    """返り値は（本文、表記を整形したか、一部省略したか）。"""
    text = html.unescape(html.unescape(text)).strip()
    protected = []

    def save_formula(expression):
        protected.append(expression)
        return f"\ue070{len(protected)-1}\ue071"

    text = re.sub(r"(\${1,2})([^$\n]+?)\1", lambda m: save_formula(m[2]),
                  text.replace("\ue070", "").replace("\ue071", ""))
    # 閉じ忘れた数式を次の文まで連結しない。通貨記号と金額は通常の本文として扱う。
    text, unclosed = re.subn(r"\$(?!\d[\d,.]*(?=\s*[ぁ-鿿。！？]|$))[^。！？]*", "…", text)
    # 表組の断片は引用として読めない。閉じた表の後に独立した記述があれば残す。
    text, tables = re.subn(r"\{\|.*?(?:\|\}|$)", "…", text, flags=re.S)
    text = re.sub(r"^(?:[（(]\s*[\d一二三四五六七八九十]*\s*[)）]\s*)+", "", text)
    # 失われたテンプレートは空の括弧として残ることがある。底が消えた冪は残して検出する。
    text = re.sub(r"[（(]\s*[)）](?!\s*[\^_])", " ", text)
    text = re.sub(r"^\d+\s*=\s*(?=\d+と)", "", text)
    text = re.sub(r"^\d+\s*=\s*(?=[a-z]\s*=\s*\d+ のときの\s*[a-zA-Z0-9\\(])", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 「255（=2 8 -1）」の省略された左辺は直前にある。値を確認してから補う。
    def parenthetic_value(m):
        expr = _FLAT_DIGIT.sub(r"\1^\2", m[3])
        if _equation_status(f"{m[1]}={expr}", require_all=True) is True:
            return m[1] + m[2] + save_formula("=" + _latex(expr)) + m[4]
        return m[0]

    text = re.sub(r"(\d+)([（(])\s*[=＝]\s*([\d ^+×÷−-]+)([)）])", parenthetic_value, text)
    pieces = []

    def add(raw, math=False):
        if not raw:
            return
        if not math and pieces and pieces[-1][1] is False:
            pieces[-1] = (pieces[-1][0] + raw, False)
        else:
            pieces.append((raw, math))

    def legacy(raw, preceding, following):
        expr = raw.strip()
        # 「キャッチ=22」「満89歳 = 90年目」「= 2カ月半」などの名前・言い換え。
        # 日本語や単位の文脈には、引用中で欠けた左辺を探す判定を適用しない。
        if (re.search(r"[ァ-ヶー°歳分秒（(]\s*$", preceding) and re.fullmatch(r"[=＝]\s*\d+", expr)
                or preceding.endswith("第") and re.fullmatch(r"\d+\s*[=＝]", expr) and following.startswith("第")
                or re.fullmatch(r"\(?\s*\d+\s*[=＝]\s*\d+", expr)
                   and re.match(r"(?:日|時間|個|年)\s*[×÷]", following)
                or preceding and re.fullmatch(r"[×÷]\s*\d+", expr) and re.match(r"[ぁ-鿿]", following)):
            add(raw)
            return
        # 「… 3つの」「… 20番目」の先頭の数字は説明の一部。
        trailer = None
        if re.match(r"(?:つ|連続|番目|桁|個|通り|から|を|は|人)", following):
            trailer = re.search(r"(?<=[\d)}!]) (\d+)$", raw)
        if trailer:
            raw = raw[:trailer.start()]
        for piece, candidate in _split_runs(raw):
            if not candidate:
                add(piece)
                continue
            for part in _formula_parts(piece):
                # 資料の句読点は式の外に置く。
                trimmed = part.strip(" \t,:")
                if trimmed.endswith(".") and not trimmed.endswith("..."):
                    trimmed = trimmed[:-1].rstrip()
                if not trimmed:
                    add(part)
                    continue
                if (not _SIGNAL.search(trimmed) and not _FLATTENED_SYMBOL.search(trimmed)
                        or not re.search(r"[a-zA-Z0-9\\πσφω]", trimmed)):
                    add(part)
                    continue
                start = part.index(trimmed)
                add(part[:start])
                add(trimmed, True)
                add(part[start + len(trimmed):])
        if trailer:
            add(trailer[0])

    at = 0
    for m in _RUN.finditer(text):
        add(text[at:m.start()])
        if m[0].startswith(r"\begin{"):
            add(m[0], True)
        else:
            legacy(m[0], text[:m.start()], text[m.end():])
        at = m.end()
    add(text[at:])

    output = []
    omitted = bool(tables or unclosed)
    damaged = False
    formatted = False
    available = limit

    def omission():
        nonlocal omitted
        omitted = True
        if not output or not output[-1].endswith("…"):
            output.append("…")

    def restore(raw):
        return _PROTECTED.sub(lambda m: protected[int(m[1])], raw)

    for index, (raw, math) in enumerate(pieces):
        if math:
            # 別の箇条書きから結合した整数=循環小数。確実な先行等式だけを残す。
            merged = re.search(r"[=＝]\s*0\.\s*[\d ]*(?:…|\.{3}|$)", raw)
            status = _equation_status(raw)
            partial = bool(merged and re.search("[=＝]", raw[:merged.start()]) and status is not True)
            if partial:
                raw = raw[:merged.start()].strip()
                status = _equation_status(raw)
            # 古い引用に「60×4 = 240+33 = 273」のような誤った連鎖がある場合、
            # 値が確認できる右側の等式は独立した形で残せる。
            if status is False:
                _, _, tail = raw.partition("=")
                if _equation_status(tail, require_all=True) is True:
                    omission()
                    raw = tail.strip()
                    status = True
            # 特定不能になった項を挟む等式は掲載しない。
            if (_MISSING.search(raw) or raw.startswith(("=", "≒")) or _OPERATORS.search(raw)
                    or _FLATTENED_SYMBOL.search(raw) or _AMBIGUOUS_POWER.search(raw)
                    or _FLAT_DIGIT.search(raw)
                    or re.search(r"\(\s*\)\s*[\^_]", raw) or not _balanced(raw)
                    or status is False):
                omission()
                damaged = True
                continue
            # 取得元で区切られた TeX は、旧キャッシュの正規化をすべて終えてから戻す。
            # これにより、行列の改行や半開区間 [0,1) も原文のまま表示できる。
            formula = restore(_latex(raw))
            cost = len(restore(raw))
            if cost > available:
                formula = _clip_equation(formula, available)
                if not formula:
                    omission()
                    continue
                cost = len(formula)
                partial = True
            output.append("$" + formula + "$")
            formatted = True
            available -= cost
            if partial:
                if formula.endswith((r"\ldots", "…")):
                    omitted = True
                else:
                    omission()
        else:
            output.append(raw[:max(0, available)])
            available -= len(raw)
            if available < 0:
                omission()
                break
        if available <= 0:
            if index + 1 < len(pieces):
                omission()
            break
    result = "".join(output).strip()
    if omitted:
        # 欠けた式を指す修飾節だけでは元の主張を復元できない。先行する独立した
        # 式があるときはそこまでを引用し、式の値や主語が失われた後続文を省く。
        result = re.sub(r"…\s*(?:のときの\s*の値|はいずれも|は[^\s。]*数|であるが、これ|"
                        r"\(?下線部は循環節|で表せる|の形で|の値とみた|（ただし).*", "…", result)
    if damaged and "$" not in result and (result.count("…") > 1 or re.search(
        r"…\s*[,、]|…\s+\d*…|…\s*のとき|この性質|下線部", result
    )):
        return None
    if not re.search(r"[\wぁ-鿿]", result):
        return None
    return result, formatted, omitted
