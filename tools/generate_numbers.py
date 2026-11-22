from __future__ import annotations

import argparse
from collections.abc import Sequence
import math
from fractions import Fraction
from dataclasses import dataclass
from itertools import groupby
import html
import json
import os
from pathlib import Path
import re

from number_range import MAX_NUMBER, number_folder
from progress import ProgressBar, ProgressSpinner
from wikidata_cc0 import WikidataEnrichment, load_or_build_enrichment
from wikipedia_ja import (
    extract_wikipedia_facts,
    load_or_build_wikipedia_intros_for_numbers,
    load_or_build_wikipedia_other_item_sets_for_numbers,
    load_or_build_wikipedia_property_sentence_sets_for_numbers,
    to_japanese_kanji,
)


ROOT = Path(__file__).resolve().parents[1]
NUMBERS_DIR = ROOT / "numbers"


_RE_WIKIPEDIA_OTHER_RELATED_STUB = re.compile(
    r"^その他\s*(?:\d+|[零〇一二三四五六七八九十百千]+)\s*に関連すること。?$"
)


_RE_WIKIPEDIA_OTHER_LOW_VALUE = re.compile(
    r"(?:JIS\s*X\s*0401|ISO\s*3166-2:JP|都道府県コード|アメリカ合衆国第\s*\d+\s*代大統領)"
)


def _number_relevance_tokens(n: int) -> set[str]:
    kanji = to_japanese_kanji(n)
    tokens: set[str] = {str(n), f"{n:03d}", kanji, f"第{n}", f"第{kanji}"}
    if n < 100:
        tokens.add(f"{n:02d}")
    return {t for t in tokens if t}


def _strip_leading_ordinal_marker(s: str) -> str:
    s2 = s.strip()
    s2 = re.sub(r"^\(\s*\)\s*", "", s2)
    s2 = re.sub(r"^[（(]\s*[0-9一二三四五六七八九十]*\s*[)）]\s*", "", s2)
    return s2.strip()

def _load_wikipedia_pins_config(pins_path: Path) -> dict[int, dict[str, list[str]]]:
    if not pins_path.exists():
        return {}
    try:
        raw = json.loads(pins_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    pins = raw.get("pins", {})
    if not isinstance(pins, dict):
        return {}

    out: dict[int, dict[str, list[str]]] = {}
    for k, v in pins.items():
        try:
            n = int(k)
        except ValueError:
            continue
        if not isinstance(v, dict):
            continue
        entry: dict[str, list[str]] = {}
        for kind, arr in v.items():
            if not isinstance(arr, list):
                continue
            entry[str(kind)] = [str(s) for s in arr if isinstance(s, str) and s.strip()]
        if entry:
            out[n] = entry
    return out


def _filter_wikipedia_other_excerpts_for_number(
    excerpts: list[str],
    n: int,
    *,
    pinned_substrings: list[str] | None = None,
) -> list[str]:
    if not excerpts:
        return []

    tokens = _number_relevance_tokens(n)
    pins = [p.strip() for p in (pinned_substrings or []) if isinstance(p, str) and p.strip()]
    kept: list[str] = []
    low_value: list[str] = []
    stubs: list[str] = []

    for raw in excerpts:
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue

        if pins and any(p in s for p in pins):
            kept.append(s)
            continue

        if _RE_WIKIPEDIA_OTHER_RELATED_STUB.search(s):
            stubs.append(s)
            continue

        s_match = _strip_leading_ordinal_marker(s)

        if _RE_WIKIPEDIA_OTHER_LOW_VALUE.search(s_match):
            low_value.append(s)
            continue

        if any(tok in s_match for tok in tokens):
            kept.append(s)
            continue

        if "この数" in s_match or "この数字" in s_match:
            has_other_large_number = bool(re.search(r"\d{3,}", s_match)) or bool(re.search(r"[一二三四五六七八九]百", s_match))
            if not has_other_large_number:
                kept.append(s)
            continue

    if kept:
        return kept
    if low_value:
        return low_value
    return stubs


def _dedupe_preserve_order(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    return out


def _looks_like_number_wikipedia_intro(intro_extract: str) -> bool:
    # 一部の数字は同名の固有名詞等へリダイレクト/曖昧さ回避されうる。
    # 数の記事の冒頭には「自然数」「整数」等が含まれることが多いので、最低限の安全策として使う。
    return ("自然数" in intro_extract) or ("整数" in intro_extract)


def _sanitize_excerpt(s: str) -> str:
    """Clean cached Wikipedia excerpts before quoting.

    - Decode HTML entities (&minus; / &times; ...) that may remain in older caches.
    - Remove stub "( )" fragments left by stripped templates.
    - Repair known template-stripping artifacts that create false equations,
      e.g. "715 = 714と715は…" -> "714と715は…" / "57 = = 素数 p = 7 …" -> "素数 p = 7 …".
    """

    t = html.unescape(html.unescape(s))
    t = re.sub(r"[（(]\s*[)）]", " ", t)
    t = re.sub(r"^\s*\d+\s*=\s*(?=\d+\s*と)", "", t)
    t = re.sub(r"^\s*\d+\s*=\s*=\s*", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _math_prefix_is_false(prefix: str) -> bool:
    """Return True only when the prefix is a *pure-arithmetic* equation that is false.

    Used as a publication gate: excerpts whose leading equation is provably wrong
    (source typos or extraction damage) must not be published. Expressions with
    variables (n, p, σ ...) cannot be judged and return False.
    """

    s = prefix.replace("×", "*").replace("÷", "/").replace("−", "-")
    s = s.replace("^", "**").replace(" ", "")
    if not re.fullmatch(r"[0-9+\-*/().=]+", s):
        return False
    parts = [q for q in s.split("=") if q]
    if len(parts) < 2:
        return False
    try:
        values = [_bounded_arith_eval(q) for q in parts]
    except Exception:
        return False
    return any(abs(v - values[0]) > 1e-9 for v in values[1:])


def _bounded_arith_eval(expr: str):
    """Evaluate a small arithmetic expression with hard bounds.

    eval() だと巨大な冪（例: 破損テキスト由来の 3**50**5）で停止するため、
    AST を辿って値域を制限しながら評価する。
    """

    import ast

    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            v = _ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else v
        if isinstance(node, ast.BinOp):
            left = _ev(node.left)
            right = _ev(node.right)
            if isinstance(node.op, ast.Add):
                out = left + right
            elif isinstance(node.op, ast.Sub):
                out = left - right
            elif isinstance(node.op, ast.Mult):
                out = left * right
            elif isinstance(node.op, ast.Div):
                out = left / right
            elif isinstance(node.op, ast.Pow):
                if abs(right) > 64 or abs(left) > 10**9:
                    raise ValueError("exponent out of bounds")
                out = left ** right
            else:
                raise ValueError("unsupported operator")
            if abs(out) > 10**18:
                raise ValueError("value out of bounds")
            return out
        raise ValueError("unsupported expression")

    return _ev(ast.parse(expr, mode="eval"))


def _split_math_prefix(text: str) -> tuple[str, str] | None:
    """Split a Wikipedia excerpt into (math_like_prefix, remainder).

    We do NOT modify the quote itself. Instead, we optionally add a separate
    line that re-states the excerpt with KaTeX formatting.

    Prefix stops at:
    - Japanese characters
    - Japanese punctuation (。 、)
    - Parentheses ( ( / （ ) to keep the math part clean
    """

    s = text.strip()
    if not s:
        return None

    # 上付き指数の平坦化（"2 2 + 4 2" ← 2²+4²）を修復する。
    # 単一桁の指数が直後に演算子/等号/文末を伴う場合のみ対象。
    s = re.sub(r"(\d+) (\d)(?=\s*[+\-−×÷=)]|$|\s+\d+[^\d\s])", r"\1^\2", s)

    def _is_japanese_char(ch: str) -> bool:
        code = ord(ch)
        return (
            (0x3040 <= code <= 0x30FF)  # Hiragana/Katakana
            or (0x4E00 <= code <= 0x9FFF)  # CJK Unified Ideographs
        )

    end = 0
    for i, ch in enumerate(s):
        # Stop at delimiters (keep '.'/',' because decimals are common).
        if ch in "。、(（":
            end = i
            break
        if _is_japanese_char(ch):
            end = i
            break
        if ch.isdigit() and i + 1 < len(s) and _is_japanese_char(s[i + 1]):
            if i > 0 and s[i - 1] == " ":
                end = i
                break
        end = i + 1

    # Trim trailing spaces from the prefix but keep remainder intact.
    prefix_end = end
    while prefix_end > 0 and s[prefix_end - 1] == " ":
        prefix_end -= 1
    prefix = s[:prefix_end]
    remainder = s[prefix_end:]

    if not prefix:
        return None

    # Avoid cases like "= 0." that are missing the left-hand side.
    if prefix.startswith("=") or prefix.startswith("＝"):
        return None

    # Must contain at least one digit and a math signal.
    if not re.search(r"\d", prefix):
        return None
    if not re.search(r"[=^×÷√π]", prefix):
        return None

    # 演算子を挟まずに数値項が連続する場合、後続は説明文の断片
    # （例: "276 = 0^5 + 1^5 + 2^5 + 3^5 0^5を含めて…" の 2 つ目の 0^5）。
    m_gap = re.search(r"(?<=[\d)]) +(?=\d)", prefix)
    if m_gap:
        remainder = prefix[m_gap.start():] + remainder
        prefix = prefix[: m_gap.start()].rstrip()

    # A completed equation followed by a fresh "<var> = ..." belongs to the
    # explanation, not the formula (e.g. "57 = 2^6 − 2^3 + 1 n = 2 のときの…").
    first_eq = prefix.find("=")
    if first_eq != -1:
        m2 = re.search(r"\s(?=[A-Za-z]\s*=)", prefix[first_eq + 1:])
        if m2:
            cut = first_eq + 1 + m2.start()
            remainder = prefix[cut:] + remainder
            prefix = prefix[:cut].rstrip()

    # Reject fragments that would produce broken KaTeX.
    if prefix.count("{") != prefix.count("}") or prefix.count("(") != prefix.count(")"):
        return None
    if prefix.endswith("=") or prefix.endswith("＝"):
        return None
    if len(prefix) < 6:
        return None
    if not re.search(r"\d", prefix) or not re.search(r"[=^×÷√π]", prefix):
        return None
    return prefix, remainder


def _katex_balanced(s: str) -> bool:
    """KaTeX 式として明らかに破綻していないか（\\left/\\right・波括弧の均衡）を確認する。"""
    return (
        s.count("\\left") == s.count("\\right")
        and s.count("{") == s.count("}")
    )


def _to_katex_math(expr: str) -> str:
    s = expr

    # Defensive normalization:
    # Some pipelines/tools may double-escape backslashes, resulting in strings like
    # "\\times" in the final Markdown. For KaTeX macros, a single backslash is enough.
    # We only collapse when the backslashes are immediately followed by a macro name
    # (alphabetic), so we don't touch LaTeX line breaks ("\\\\") if they ever appear.
    s = re.sub(r"\\{2,}(?=[A-Za-z])", r"\\", s)

    # Normalize characters.
    s = s.replace("×", r"\times")
    s = s.replace("÷", r"\div")
    s = s.replace("π", r"\pi")
    s = s.replace("…", r"\dots")
    s = s.replace("−", "-")  # U+2212

    # Root notations seen in Japanese Wikipedia excerpts.
    # Example: ^3√31 -> \sqrt[3]{31}
    # IMPORTANT: replacement strings in re.sub treat backslashes specially.
    # Use double backslash to emit a literal backslash for KaTeX macros.
    s = re.sub(r"\^(\d+)√\s*(\d+)", r"\\sqrt[\1]{\2}", s)
    # Example: √10 -> \sqrt{10}
    s = re.sub(r"√\s*(\d+)", r"\\sqrt{\1}", s)

    # Use braces for exponents, including negative ones.
    s = re.sub(r"\^(-?\d+)", r"^{\1}", s)

    # Keep ASCII spaces (KaTeX ignores extra spaces reasonably).
    return s.strip()


ELEMENTS_JA: list[str | None] = [
    None,
    "水素",
    "ヘリウム",
    "リチウム",
    "ベリリウム",
    "ホウ素",
    "炭素",
    "窒素",
    "酸素",
    "フッ素",
    "ネオン",
    "ナトリウム",
    "マグネシウム",
    "アルミニウム",
    "ケイ素",
    "リン",
    "硫黄",
    "塩素",
    "アルゴン",
    "カリウム",
    "カルシウム",
    "スカンジウム",
    "チタン",
    "バナジウム",
    "クロム",
    "マンガン",
    "鉄",
    "コバルト",
    "ニッケル",
    "銅",
    "亜鉛",
    "ガリウム",
    "ゲルマニウム",
    "ヒ素",
    "セレン",
    "臭素",
    "クリプトン",
    "ルビジウム",
    "ストロンチウム",
    "イットリウム",
    "ジルコニウム",
    "ニオブ",
    "モリブデン",
    "テクネチウム",
    "ルテニウム",
    "ロジウム",
    "パラジウム",
    "銀",
    "カドミウム",
    "インジウム",
    "スズ",
    "アンチモン",
    "テルル",
    "ヨウ素",
    "キセノン",
    "セシウム",
    "バリウム",
    "ランタン",
    "セリウム",
    "プラセオジム",
    "ネオジム",
    "プロメチウム",
    "サマリウム",
    "ユウロピウム",
    "ガドリニウム",
    "テルビウム",
    "ジスプロシウム",
    "ホルミウム",
    "エルビウム",
    "ツリウム",
    "イッテルビウム",
    "ルテチウム",
    "ハフニウム",
    "タンタル",
    "タングステン",
    "レニウム",
    "オスミウム",
    "イリジウム",
    "白金",
    "金",
    "水銀",
    "タリウム",
    "鉛",
    "ビスマス",
    "ポロニウム",
    "アスタチン",
    "ラドン",
    "フランシウム",
    "ラジウム",
    "アクチニウム",
    "トリウム",
    "プロトアクチニウム",
    "ウラン",
    "ネプツニウム",
    "プルトニウム",
    "アメリシウム",
    "キュリウム",
    "バークリウム",
    "カリホルニウム",
    "アインスタイニウム",
    "フェルミウム",
    "メンデレビウム",
    "ノーベリウム",
    "ローレンシウム",
    "ラザホージウム",
    "ドブニウム",
    "シーボーギウム",
    "ボーリウム",
    "ハッシウム",
    "マイトネリウム",
    "ダームスタチウム",
    "レントゲニウム",
    "コペルニシウム",
    "ニホニウム",
    "フレロビウム",
    "モスコビウム",
    "リバモリウム",
    "テネシン",
    "オガネソン",
]


HTTP_STATUS_CODES_REPO_INDEX = (
    "https://github.com/radiann-kswg/CheatSheet-of_HttpResponceDataCode/blob/main/index.md"
)
LIST_7400_WIKIPEDIA_EN = "https://en.wikipedia.org/wiki/List_of_7400-series_integrated_circuits"

HTTP_STATUS_CODES_REPO_BASE = (
    "https://github.com/radiann-kswg/CheatSheet-of_HttpResponceDataCode/blob/main/status-codes/"
)

# 実在する HTTP ステータスコードのみを対象にする（IANA 登録コード＋主要実装の非標準コード）。
# 値: (参照リポジトリ内の相対パス, MDN に個別ページがあるか)
HTTP_STATUS_PAGES: dict[int, tuple[str, bool]] = {
    100: ("1xx-information/100-continue.md", True),
    101: ("1xx-information/101-switching-protocols.md", True),
    102: ("1xx-information/102-processing.md", True),
    103: ("1xx-information/103-early-hints.md", True),
    104: ("1xx-information/104-upload-resumption-supported.md", False),
    200: ("2xx-success/200-ok.md", True),
    201: ("2xx-success/201-created.md", True),
    202: ("2xx-success/202-accepted.md", True),
    203: ("2xx-success/203-non-authoritative-information.md", True),
    204: ("2xx-success/204-no-content.md", True),
    205: ("2xx-success/205-reset-content.md", True),
    206: ("2xx-success/206-partial-content.md", True),
    207: ("2xx-success/207-multi-status.md", True),
    208: ("2xx-success/208-already-reported.md", True),
    226: ("2xx-success/226-im-used.md", True),
    300: ("3xx-redirection/300-multiple-choices.md", True),
    301: ("3xx-redirection/301-moved-permanently.md", True),
    302: ("3xx-redirection/302-found.md", True),
    303: ("3xx-redirection/303-see-other.md", True),
    304: ("3xx-redirection/304-not-modified.md", True),
    307: ("3xx-redirection/307-temporary-redirect.md", True),
    308: ("3xx-redirection/308-permanent-redirect.md", True),
    400: ("4xx-client-error/400-bad-request.md", True),
    401: ("4xx-client-error/401-unauthorized.md", True),
    402: ("4xx-client-error/402-payment-required.md", True),
    403: ("4xx-client-error/403-forbidden.md", True),
    404: ("4xx-client-error/404-not-found.md", True),
    405: ("4xx-client-error/405-method-not-allowed.md", True),
    406: ("4xx-client-error/406-not-acceptable.md", True),
    407: ("4xx-client-error/407-proxy-authentication-required.md", True),
    408: ("4xx-client-error/408-request-timeout.md", True),
    409: ("4xx-client-error/409-conflict.md", True),
    410: ("4xx-client-error/410-gone.md", True),
    411: ("4xx-client-error/411-length-required.md", True),
    412: ("4xx-client-error/412-precondition-failed.md", True),
    413: ("4xx-client-error/413-content-too-large.md", True),
    414: ("4xx-client-error/414-uri-too-long.md", True),
    415: ("4xx-client-error/415-unsupported-media-type.md", True),
    416: ("4xx-client-error/416-range-not-satisfiable.md", True),
    417: ("4xx-client-error/417-expectation-failed.md", True),
    418: ("4xx-client-error/418-im-a-teapot.md", True),
    421: ("4xx-client-error/421-misdirected-request.md", True),
    422: ("4xx-client-error/422-unprocessable-content.md", True),
    423: ("4xx-client-error/423-locked.md", True),
    424: ("4xx-client-error/424-failed-dependency.md", True),
    425: ("4xx-client-error/425-too-early.md", True),
    426: ("4xx-client-error/426-upgrade-required.md", True),
    428: ("4xx-client-error/428-precondition-required.md", True),
    429: ("4xx-client-error/429-too-many-requests.md", True),
    431: ("4xx-client-error/431-request-header-fields-too-large.md", True),
    451: ("4xx-client-error/451-unavailable-for-legal-reasons.md", True),
    500: ("5xx-server-error/500-internal-server-error.md", True),
    501: ("5xx-server-error/501-not-implemented.md", True),
    502: ("5xx-server-error/502-bad-gateway.md", True),
    503: ("5xx-server-error/503-service-unavailable.md", True),
    504: ("5xx-server-error/504-gateway-timeout.md", True),
    505: ("5xx-server-error/505-http-version-not-supported.md", True),
    506: ("5xx-server-error/506-variant-also-negotiates.md", True),
    507: ("5xx-server-error/507-insufficient-storage.md", True),
    508: ("5xx-server-error/508-loop-detected.md", True),
    510: ("5xx-server-error/510-not-extended.md", True),
    511: ("5xx-server-error/511-network-authentication-required.md", True),
    444: ("implementation-dependent/nginx-proprietary/444-connection-closed-without-response.md", False),
    495: ("implementation-dependent/nginx-proprietary/495-client-certificate-verification-error.md", False),
    496: ("implementation-dependent/nginx-proprietary/496-client-certificate-required.md", False),
    497: ("implementation-dependent/nginx-proprietary/497-http-request-sent-to-https-port.md", False),
    520: ("implementation-dependent/cloudflare-proprietary/520-web-server-returns-an-unknown-error.md", False),
    521: ("implementation-dependent/cloudflare-proprietary/521-web-server-is-down.md", False),
    522: ("implementation-dependent/cloudflare-proprietary/522-connection-timed-out.md", False),
    523: ("implementation-dependent/cloudflare-proprietary/523-origin-is-unreachable.md", False),
    524: ("implementation-dependent/cloudflare-proprietary/524-a-timeout-occurred.md", False),
    525: ("implementation-dependent/cloudflare-proprietary/525-ssl-handshake-failed.md", False),
    526: ("implementation-dependent/cloudflare-proprietary/526-invalid-ssl-certificate.md", False),
    530: ("implementation-dependent/cloudflare-proprietary/530-origin-dns-error.md", False),
    598: ("implementation-dependent/proxy-conventions/598-er-throttled-or-blocked.md", False),
    599: ("implementation-dependent/proxy-conventions/599-er-context-unknown-error.md", False),
}

IANA_HTTP_STATUS_REGISTRY = (
    "https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml"
)


# 代表的な 74xx の機能（シリーズ/メーカーで差異があるため、断定を避けて入口として提示）
LOGIC_74XX_HINTS: dict[int, str] = {
    0: "4回路 2入力 NAND（例: 74xx00）",
    2: "4回路 2入力 NOR（例: 74xx02）",
    4: "6回路 インバータ（NOT）（例: 74xx04）",
    8: "4回路 2入力 AND（例: 74xx08）",
    32: "4回路 2入力 OR（例: 74xx32）",
    74: "2回路 Dフリップフロップ（例: 74xx74）",
    86: "4回路 2入力 XOR（例: 74xx86）",
    125: "4回路 3ステート・バッファ（例: 74xx125）",
    138: "3→8 デコーダ/デマルチプレクサ（例: 74xx138）",
    139: "2回路 2→4 デコーダ/デマルチプレクサ（例: 74xx139）",
    151: "8→1 マルチプレクサ（例: 74xx151）",
    157: "4回路 2→1 マルチプレクサ（例: 74xx157）",
    161: "4ビット 同期バイナリ・カウンタ（例: 74xx161）",
    163: "4ビット 同期バイナリ・カウンタ（例: 74xx163）",
    165: "8ビット PISO シフトレジスタ（例: 74xx165）",
    173: "4ビット レジスタ（3ステート出力）（例: 74xx173）",
    174: "6ビット Dフリップフロップ（例: 74xx174）",
    191: "4ビット UP/DOWN カウンタ（例: 74xx191）",
    240: "8ビット バッファ/ラインドライバ（反転, 3ステート）（例: 74xx240）",
    244: "8ビット バッファ/ラインドライバ（3ステート）（例: 74xx244）",
    245: "8ビット 双方向トランシーバ（3ステート）（例: 74xx245）",
    273: "8ビット レジスタ（例: 74xx273）",
    374: "8ビット Dフリップフロップ（3ステート）（例: 74xx374）",
    393: "デュアル 4ビット リップルカウンタ（例: 74xx393）",
}


DAIJI_DIGITS = {
    0: "零",
    1: "壹",
    2: "貳",
    3: "參",
    4: "肆",
    5: "伍",
    6: "陸",
    7: "柒",
    8: "捌",
    9: "玖",
}


EN_UNDER_20 = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
}

EN_TENS = {
    20: "twenty",
    30: "thirty",
    40: "forty",
    50: "fifty",
    60: "sixty",
    70: "seventy",
    80: "eighty",
    90: "ninety",
}


JP_DIGIT_READING = {
    0: "れい",
    1: "いち",
    2: "に",
    3: "さん",
    4: "よん",
    5: "ご",
    6: "ろく",
    7: "なな",
    8: "はち",
    9: "きゅう",
}


@dataclass(frozen=True)
class NumberInfo:
    n: int
    factorization: str
    is_prime: bool
    is_even: bool
    digit_sum: int
    num_divisors: int | None
    sum_divisors: int | None
    proper_divisor_sum: int | None
    abundance: str | None
    totient: int | None
    is_square: bool
    is_cube: bool
    is_triangular: bool
    is_fibonacci: bool
    is_mersenne: bool
    representations: dict[str, str]
    jp_kanji: str
    jp_daiji: str
    jp_reading: str
    en_words: str
    atomic_element: str | None


def is_prime(n: int) -> bool:
    if n <= 1:
        return False
    if n <= 3:
        return True
    if n % 2 == 0:
        return False
    limit = int(math.isqrt(n))
    for d in range(3, limit + 1, 2):
        if n % d == 0:
            return False
    return True


def prime_factorization(n: int) -> list[tuple[int, int]]:
    factors: list[tuple[int, int]] = []
    if n <= 1:
        return factors

    remaining = n
    count = 0
    while remaining % 2 == 0:
        remaining //= 2
        count += 1
    if count:
        factors.append((2, count))

    p = 3
    while p * p <= remaining:
        count = 0
        while remaining % p == 0:
            remaining //= p
            count += 1
        if count:
            factors.append((p, count))
        p += 2

    if remaining > 1:
        factors.append((remaining, 1))

    return factors


def format_factorization(n: int, factors: list[tuple[int, int]]) -> str:
    if n == 0:
        return "0"
    if n == 1:
        return "1"
    if not factors:
        return str(n)
    parts: list[str] = []
    for p, exp in factors:
        if exp == 1:
            parts.append(str(p))
        else:
            parts.append(f"{p}^{exp}")
    return " × ".join(parts)


def divisor_count_and_sum(factors: list[tuple[int, int]]) -> tuple[int, int]:
    # For n >= 2
    count = 1
    sigma = 1
    for p, exp in factors:
        count *= exp + 1
        sigma *= (p ** (exp + 1) - 1) // (p - 1)
    return count, sigma


def euler_totient(n: int, factors: list[tuple[int, int]]) -> int:
    if n == 0:
        return 0
    if n == 1:
        return 1
    result = n
    for p, _ in factors:
        result = result // p * (p - 1)
    return result


def is_perfect_square(n: int) -> bool:
    if n < 0:
        return False
    r = math.isqrt(n)
    return r * r == n


def is_perfect_cube(n: int) -> bool:
    if n < 0:
        return False
    r = round(n ** (1 / 3))
    return r * r * r == n


def is_triangular(n: int) -> bool:
    if n < 0:
        return False
    # 8n+1 is a square
    return is_perfect_square(8 * n + 1)


def is_fibonacci(n: int) -> bool:
    if n < 0:
        return False
    return is_perfect_square(5 * n * n + 4) or is_perfect_square(5 * n * n - 4)


def is_mersenne(n: int) -> bool:
    # n = 2^p - 1
    if n <= 0:
        return False
    x = n + 1
    return x & (x - 1) == 0


def to_roman(n: int) -> str | None:
    if not (1 <= n <= 3999):
        return None
    numerals = [
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    ]
    remaining = n
    out: list[str] = []
    for value, symbol in numerals:
        while remaining >= value:
            out.append(symbol)
            remaining -= value
    return "".join(out)


def japanese_reading(n: int) -> str:
    if n == 0:
        return JP_DIGIT_READING[0]

    thousands, rest = divmod(n, 1000)
    h = rest // 100
    t = (n // 10) % 10
    u = n % 10

    out: list[str] = []
    if thousands:
        if thousands == 1:
            out.append("せん")
        elif thousands == 3:
            out.append("さんぜん")
        elif thousands == 8:
            out.append("はっせん")
        else:
            out.append(JP_DIGIT_READING[thousands] + "せん")

    if h:
        if h == 1:
            out.append("ひゃく")
        elif h == 3:
            out.append("さんびゃく")
        elif h == 6:
            out.append("ろっぴゃく")
        elif h == 8:
            out.append("はっぴゃく")
        else:
            out.append(JP_DIGIT_READING[h] + "ひゃく")

    if t:
        if t == 1:
            out.append("じゅう")
        else:
            out.append(JP_DIGIT_READING[t] + "じゅう")

    if u:
        out.append(JP_DIGIT_READING[u])

    return "".join(out)


def english_words(n: int) -> str:
    if not (0 <= n <= MAX_NUMBER):
        raise ValueError(f"Supported range is 0..{MAX_NUMBER}")
    if n < 20:
        return EN_UNDER_20[n]
    if n < 100:
        tens = (n // 10) * 10
        unit = n % 10
        if unit == 0:
            return EN_TENS[tens]
        return f"{EN_TENS[tens]}-{EN_UNDER_20[unit]}"

    if n >= 1000:
        thousands, rest = divmod(n, 1000)
        prefix = f"{EN_UNDER_20[thousands]} thousand"
    else:
        hundreds, rest = divmod(n, 100)
        prefix = f"{EN_UNDER_20[hundreds]} hundred"
    if rest == 0:
        return prefix
    return f"{prefix} {english_words(rest)}"


# --- 追加の数学的性質（機械導出・Wolfram で集合を検算済み） ---

_HIGHLY_COMPOSITE = {1, 2, 4, 6, 12, 24, 36, 48, 60, 120, 180, 240, 360, 720, 840}
_FACTORIALS = {1, 2, 6, 24, 120, 720}
_LUCAS = {2, 1, 3, 4, 7, 11, 18, 29, 47, 76, 123, 199, 322, 521, 843}
_PELL = {1, 2, 5, 12, 29, 70, 169, 408, 985}
_CATALAN = {1, 2, 5, 14, 42, 132, 429}


def _is_palindrome_number(n: int) -> bool:
    s = str(n)
    return s == s[::-1]


def _is_happy(n: int) -> bool:
    seen: set[int] = set()
    while n != 1 and n not in seen:
        seen.add(n)
        n = sum(int(c) ** 2 for c in str(n))
    return n == 1


def _prime_factor_shape(n: int) -> tuple[int, int]:
    """Return (総素因数個数（重複含む）, 相異なる素因数の個数)."""
    total = 0
    distinct = 0
    m = n
    q = 2
    while q * q <= m:
        if m % q == 0:
            distinct += 1
            while m % q == 0:
                total += 1
                m //= q
        q += 1
    if m > 1:
        total += 1
        distinct += 1
    return total, distinct


def _happy_chain(n: int) -> list[int]:
    chain = [n]
    seen: set[int] = set()
    while n != 1 and n not in seen:
        seen.add(n)
        n = sum(int(c) ** 2 for c in str(n))
        chain.append(n)
    return chain


def _flat_prime_factors_katex(n: int) -> str:
    """素因数を重複込みで平坦に並べた KaTeX 式（例: 57 → '3 \\times 19'）。"""
    parts: list[str] = []
    for p, e in prime_factorization(n):
        parts.extend([str(p)] * e)
    return " \\times ".join(parts)


def extra_math_flag_details(n: int) -> list[tuple[str, str]]:
    """機械導出できる数の性質を（フラグ名, 定義＋この数での根拠）のペアで列挙する。"""

    details: list[tuple[str, str]] = []
    if n < 1:
        return details

    prime = is_prime(n)
    rev = int(str(n)[::-1])

    if n >= 10 and _is_palindrome_number(n):
        if prime:
            details.append(("回文素数", "逆から読んでも同じ数になる素数。"))
        else:
            details.append(("回文数", "逆から読んでも同じ数になる数。"))
    if prime and rev != n and is_prime(rev):
        details.append(
            ("エマープ", f"逆順に読むと異なる素数になる素数。{n} の逆順 {rev} も素数。"))
    if prime:
        partners = [p for p in (n - 2, n + 2) if p >= 2 and is_prime(p)]
        if partners:
            ptxt = " と ".join(str(p) for p in partners)
            details.append(("双子素数", f"差が 2 の素数の組を成す素数。{n} は {ptxt} と組になる。"))
        if is_prime(2 * n + 1):
            details.append(
                ("ソフィー・ジェルマン素数",
                 f"$2p+1$ も素数となる素数 $p$。$2 \\times {n} + 1 = {2 * n + 1}$ も素数。"))
        if n >= 5 and (n - 1) % 2 == 0 and is_prime((n - 1) // 2):
            details.append(
                ("安全素数", f"$(p-1)/2$ も素数となる素数 $p$。$({n}-1)/2 = {(n - 1) // 2}$ も素数。"))
    else:
        total, distinct = _prime_factor_shape(n)
        if total == 2:
            details.append(
                ("半素数", f"ちょうど 2 つの素数の積で表される合成数。${n} = {_flat_prime_factors_katex(n)}$。"))
        if total == 3 and distinct == 3:
            details.append(
                ("楔数", f"相異なる 3 つの素数の積で表される合成数。${n} = {_flat_prime_factors_katex(n)}$。"))
    ds = sum(int(c) for c in str(n))
    if ds > 0 and n % ds == 0:
        details.append(
            ("ハーシャッド数", f"各位の和で割り切れる数。${n} \\div {ds} = {n // ds}$。"))
    if _is_happy(n):
        chain = _happy_chain(n)
        det = "各位の 2 乗の和を繰り返し取ると 1 に到達する数。"
        if 1 < len(chain) <= 8:
            det += "（" + " → ".join(str(x) for x in chain) + "）"
        details.append(("ハッピー数", det))
    if n in _HIGHLY_COMPOSITE:
        details.append(("高度合成数", "それ未満のどの自然数よりも約数の個数が多い数。"))
    if n in _FACTORIALS:
        k = {1: 1, 2: 2, 6: 3, 24: 4, 120: 5, 720: 6}[n]
        details.append(("階乗数", f"階乗で表される数。${n} = {k}!$。"))
    if n in _LUCAS:
        details.append(("リュカ数", "リュカ数列（2, 1, 3, 4, 7, 11, …。隣接 2 項の和で定まる）の項。"))
    if n in _PELL:
        details.append(
            ("ペル数", "ペル数列（1, 2, 5, 12, 29, …。$P_k = 2P_{k-1} + P_{k-2}$ で定まる）の項。"))
    if n in _CATALAN:
        details.append(("カタラン数", "カタラン数列（1, 2, 5, 14, 42, …。組合せ論に頻出）の項。"))
    return details


def extra_math_properties(n: int) -> list[str]:
    """（後方互換）フラグ名のみのリストを返す。"""
    return [name for name, _ in extra_math_flag_details(n)]


# --- 数列への所属（機械導出） ---------------------------------------------
#
# 判定はすべて本スクリプト内で計算する（外部サイトからの取得・転載はしない）。
# 対象とする数列の目録は https://number-pedia.com/ を参考にしたが、
# 同サイトは利用規約でスクレイピング・複製を禁じているため取得は行わず、
# 各数列の定義（公知の数学的事実）から自前で計算し、OEIS 等の一次情報へ導線を張る。
# 0..999 の全域について OEIS の公表値と突き合わせて検算済み。

_SEQ_LIMIT = MAX_NUMBER + 1


def _seq_from_gen(gen) -> dict[int, int]:
    """(添字, 値) の列から 値 < _SEQ_LIMIT のものを {値: 添字} で返す。"""
    out: dict[int, int] = {}
    for i, v in gen:
        if v >= _SEQ_LIMIT:
            break
        if v >= 0 and v not in out:
            out[v] = i
    return out


def _seq_sigma(n: int) -> int:
    s = 1
    for p, e in prime_factorization(n):
        s *= (p ** (e + 1) - 1) // (p - 1)
    return s


def _seq_tau(n: int) -> int:
    t = 1
    for _p, e in prime_factorization(n):
        t *= e + 1
    return t


def _seq_totient(n: int) -> int:
    return euler_totient(n, prime_factorization(n))


def _seq_digits(n: int) -> list[int]:
    return [int(c) for c in str(n)]


def _seq_is_perfect_power(n: int) -> bool:
    if n < 4:
        return False
    for k in range(2, n.bit_length() + 1):
        r = round(n ** (1.0 / k))
        for c in (r - 1, r, r + 1):
            if c >= 2 and c ** k == n:
                return True
    return False


def _polygonal(k: int, i: int) -> int:
    """k 角数の第 i 項。"""
    return i * ((k - 2) * i - (k - 4)) // 2


def _centered_polygonal(k: int, i: int) -> int:
    """中心つき k 角数の第 i 項。"""
    return k * i * (i - 1) // 2 + 1


def _polygonal_index(k: int, n: int) -> int | None:
    """n が k 角数なら第何項かを返す（第 1 項は常に 1 なので第 2 項以降のみ）。"""
    i = 2
    while True:
        v = _polygonal(k, i)
        if v > n:
            return None
        if v == n:
            return i
        i += 1


def _centered_polygonal_index(k: int, n: int) -> int | None:
    i = 2
    while True:
        v = _centered_polygonal(k, i)
        if v > n:
            return None
        if v == n:
            return i
        i += 1


_POLYGON_NAME_JA = {
    5: "五角数", 6: "六角数", 7: "七角数", 8: "八角数", 9: "九角数", 10: "十角数",
    11: "十一角数", 12: "十二角数", 13: "十三角数", 14: "十四角数", 15: "十五角数",
    16: "十六角数", 17: "十七角数", 18: "十八角数", 19: "十九角数", 20: "二十角数",
}

_CENTERED_NAME_JA = {
    3: "中心つき三角数", 4: "中心つき四角数", 5: "中心つき五角数", 6: "中心つき六角数",
    7: "中心つき七角数", 8: "中心つき八角数", 9: "中心つき九角数", 10: "中心つき十角数",
    11: "中心つき十一角数", 12: "中心つき十二角数（＝六芒星数）", 13: "中心つき十三角数",
    14: "中心つき十四角数", 15: "中心つき十五角数", 16: "中心つき十六角数",
    17: "中心つき十七角数", 18: "中心つき十八角数", 19: "中心つき十九角数",
    20: "中心つき二十角数",
}


def _seq_lucky() -> set[int]:
    """幸運数（ラッキーナンバー、A000959）。ふるいで生成する。"""
    nums = list(range(1, 20001, 2))
    i = 1
    while i < len(nums):
        step = nums[i]
        if step > len(nums):
            break
        del nums[step - 1:: step]
        i += 1
    return {v for v in nums if v < _SEQ_LIMIT}


def _seq_ulam() -> set[int]:
    """ウラム数（A002858）: それ以前の相異なる 2 項の和として一意に表せる数。"""
    seq = [1, 2]
    seen = {1, 2}
    cand = 3
    while seq[-1] < _SEQ_LIMIT:
        ways = 0
        for x in seq:
            y = cand - x
            if y <= x:
                break
            if y in seen:
                ways += 1
                if ways > 1:
                    break
        if ways == 1:
            seq.append(cand)
            seen.add(cand)
        cand += 1
    return {v for v in seq if v < _SEQ_LIMIT}


def _seq_smith() -> set[int]:
    """スミス数（A006753）: 各位の和が素因数（重複込み）の各位の和に等しい合成数。"""
    out: set[int] = set()
    for n in range(4, _SEQ_LIMIT):
        if is_prime(n):
            continue
        if sum(_seq_digits(n)) == sum(sum(_seq_digits(p)) * e
                                      for p, e in prime_factorization(n)):
            out.add(n)
    return out


def _seq_semiperfect() -> set[int]:
    """疑似完全数（A005835）: 真の約数の一部の和で自身を表せる数。"""
    out: set[int] = set()
    for n in range(1, _SEQ_LIMIT):
        divs = [d for d in range(1, n) if n % d == 0]
        if sum(divs) < n:
            continue
        reach = 1
        for d in divs:
            reach |= reach << d
        if (reach >> n) & 1:
            out.add(n)
    return out


def _seq_perfect_totient() -> set[int]:
    """完全トーシェント数（A082897）: 反復トーシェントの総和が自身に等しい数。"""
    out: set[int] = set()
    for n in range(1, _SEQ_LIMIT):
        s, m = 0, n
        while m > 1:
            m = _seq_totient(m)
            s += m
        if s == n:
            out.add(n)
    return out


def _seq_hamming() -> set[int]:
    """ハミング数（A051037）: 2, 3, 5 のみを素因数に持つ数。"""
    out: set[int] = set()
    a = 1
    while a < _SEQ_LIMIT:
        b = a
        while b < _SEQ_LIMIT:
            c = b
            while c < _SEQ_LIMIT:
                out.add(c)
                c *= 5
            b *= 3
        a *= 2
    return out


def _seq_kaprekar() -> set[int]:
    """カプレカ数（A006886）: 平方を 2 分割して足すと自身に戻る数。"""
    out: set[int] = {1}
    for n in range(2, _SEQ_LIMIT):
        sq = str(n * n)
        for cut in range(1, len(sq)):
            left, right = sq[:cut], sq[cut:]
            if int(right) and int(left) + int(right) == n:
                out.add(n)
                break
    return out


def _seq_proth() -> set[int]:
    """プロス数（A080075）: $k \\cdot 2^m + 1$（$k$ は奇数、$k < 2^m$）。"""
    out: set[int] = set()
    m = 1
    while 2 ** m < _SEQ_LIMIT * 2:
        k = 1
        while k < 2 ** m:
            v = k * 2 ** m + 1
            if v < _SEQ_LIMIT:
                out.add(v)
            k += 2
        m += 1
    return out


def _seq_leyland() -> set[int]:
    """レイランド数（A076980）: $x^y + y^x$（$x \\ge y \\ge 2$）。"""
    out: set[int] = set()
    for x in range(2, 40):
        for y in range(2, x + 1):
            v = x ** y + y ** x
            if v < _SEQ_LIMIT:
                out.add(v)
    return out


def _seq_totient_values() -> set[int]:
    """トーシェント数（A002202）: ある $m$ について $\\varphi(m)$ となりうる値。"""
    return {_seq_totient(m) for m in range(1, _SEQ_LIMIT * 6)
            if _seq_totient(m) < _SEQ_LIMIT}


def _seq_running_record(key) -> set[int]:
    """1 から順に key(n) の最大記録を更新した数（高度合成数・超過剰数用）。"""
    out: set[int] = set()
    best = None
    for n in range(1, _SEQ_LIMIT):
        v = key(n)
        if best is None or v > best:
            best = v
            out.add(n)
    return out


def _seq_linear_recurrence(order: int) -> set[int]:
    """n-ナッチ数（トリボナッチ・テトラナッチ）。初期値 0,...,0,1。"""
    seq = [0] * (order - 1) + [1]
    while seq[-1] < _SEQ_LIMIT:
        seq.append(sum(seq[-order:]))
    return {v for v in seq if v < _SEQ_LIMIT}


def _seq_primorial(offset: int) -> set[int]:
    """素数階乗 p# に offset を足した数（ユークリッド数 / クンマー数）。"""
    out: set[int] = set()
    prod = 1
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31):
        prod *= p
        v = prod + offset
        if 0 <= v < _SEQ_LIMIT:
            out.add(v)
        if prod > _SEQ_LIMIT:
            break
    return out


def _seq_bell() -> set[int]:
    row = [1]
    vals = [1]
    for _ in range(12):
        new = [row[-1]]
        for x in row:
            new.append(new[-1] + x)
        row = new
        vals.append(row[0])
    return {v for v in vals if v < _SEQ_LIMIT}


def _seq_motzkin() -> set[int]:
    m = [1, 1]
    for n in range(2, 15):
        m.append(((2 * n + 1) * m[n - 1] + (3 * n - 3) * m[n - 2]) // (n + 2))
    return {v for v in m if v < _SEQ_LIMIT}


def _seq_derangement() -> set[int]:
    d = [1, 0]
    for n in range(2, 12):
        d.append((n - 1) * (d[n - 1] + d[n - 2]))
    return {v for v in d if 0 < v < _SEQ_LIMIT}


def _seq_euler_numbers() -> set[int]:
    """オイラー数（A000364、正割数）。"""
    n_max = 10
    E = [0] * (2 * n_max + 1)
    E[0] = 1
    for n in range(1, n_max + 1):
        E[2 * n] = -sum(math.comb(2 * n, 2 * k) * E[2 * k] for k in range(0, n))
    return {abs(E[2 * n]) for n in range(0, n_max + 1) if abs(E[2 * n]) < _SEQ_LIMIT}


def _seq_prime_indexed_primes() -> set[int]:
    """スーパー素数（A006450）: 素数列の素数番目の項。"""
    ps = [p for p in range(2, _SEQ_LIMIT) if is_prime(p)]
    return {ps[i - 1] for i in range(1, len(ps) + 1) if is_prime(i)}


def _seq_balanced_prime() -> set[int]:
    ps = [p for p in range(2, 2000) if is_prime(p)]
    return {ps[i] for i in range(1, len(ps) - 1)
            if 2 * ps[i] == ps[i - 1] + ps[i + 1] and ps[i] < _SEQ_LIMIT}


def _seq_euler_polynomial_prime() -> set[int]:
    """オイラーの素数（A005846）: $n^2 + n + 41$ が与える素数。"""
    out: set[int] = set()
    n = 0
    while True:
        v = n * n + n + 41
        if v >= _SEQ_LIMIT:
            break
        if is_prime(v):
            out.add(v)
        n += 1
    return out


def _seq_cuban_prime() -> set[int]:
    """キュバン素数（A002407）: $(x^3-y^3)/(x-y)$（$x = y+1$）が素数となるもの。"""
    out: set[int] = set()
    y = 0
    while True:
        x = y + 1
        v = (x ** 3 - y ** 3) // (x - y)
        if v >= _SEQ_LIMIT:
            break
        if is_prime(v):
            out.add(v)
        y += 1
    return out


def _seq_chen_prime() -> set[int]:
    """陳素数（A109611）: $p+2$ が素数または半素数となる素数 $p$。"""
    out: set[int] = set()
    for p in range(2, _SEQ_LIMIT):
        if not is_prime(p):
            continue
        q = p + 2
        if is_prime(q) or sum(e for _x, e in prime_factorization(q)) == 2:
            out.add(p)
    return out


def _seq_permutable_prime() -> set[int]:
    from itertools import permutations
    out: set[int] = set()
    for p in range(2, _SEQ_LIMIT):
        if not is_prime(p):
            continue
        if all(is_prime(int("".join(t))) for t in set(permutations(str(p)))):
            out.add(p)
    return out


def _seq_truncatable_prime(left: bool) -> set[int]:
    out: set[int] = set()
    for p in range(2, _SEQ_LIMIT):
        if not is_prime(p):
            continue
        s = str(p)
        if left:
            if "0" in s:
                continue
            ok = all(is_prime(int(s[i:])) for i in range(len(s)))
        else:
            ok = all(is_prime(int(s[: i + 1])) for i in range(len(s)))
        if ok:
            out.add(p)
    return out


def _seq_nsw_prime() -> set[int]:
    """NSW 素数（A088165）: 半companion ペル数の奇数番項のうち素数。"""
    h = [1, 1]
    while h[-1] < _SEQ_LIMIT * 100:
        h.append(2 * h[-1] + h[-2])
    return {h[i] for i in range(1, len(h), 2) if h[i] < _SEQ_LIMIT and is_prime(h[i])}


def _seq_wagstaff_prime() -> set[int]:
    out: set[int] = set()
    for p in range(2, 30):
        if not is_prime(p):
            continue
        v = (2 ** p + 1) // 3
        if v < _SEQ_LIMIT and is_prime(v):
            out.add(v)
    return out


# 数列名 → (集合を作る関数, 定義の説明文)
_SEQUENCE_SPECS: list[tuple[str, "typing.Callable[[], set[int]]", str]] = [
    ("矩形数", lambda: {i * (i + 1) for i in range(1, 40)},
     "連続する 2 整数の積 $k(k+1)$ で表される数（長方形数）。（OEIS [A002378](https://oeis.org/A002378)）"),
    ("三角錐数", lambda: {i * (i + 1) * (i + 2) // 6 for i in range(1, 40)},
     "三角数を積み上げた四面体状の個数 $k(k+1)(k+2)/6$ で表される数。（OEIS [A000292](https://oeis.org/A000292)）"),
    ("四角錐数", lambda: {i * (i + 1) * (2 * i + 1) // 6 for i in range(1, 40)},
     "平方数を積み上げた四角錐状の個数 $k(k+1)(2k+1)/6$ で表される数。（OEIS [A000330](https://oeis.org/A000330)）"),
    ("五角錐数", lambda: {i * i * (i + 1) // 2 for i in range(1, 40)},
     "五角数を積み上げた個数 $k^2(k+1)/2$ で表される数。（OEIS [A002411](https://oeis.org/A002411)）"),
    ("五胞体数", lambda: {i * (i + 1) * (i + 2) * (i + 3) // 24 for i in range(1, 40)},
     "4 次元の三角錐（五胞体）状に並ぶ個数 $k(k+1)(k+2)(k+3)/24$ で表される数。（OEIS [A000332](https://oeis.org/A000332)）"),
    ("星型八面体数", lambda: {i * (2 * i * i - 1) for i in range(1, 40)},
     "星型八面体（ステラ・オクタンギュラ）状に並ぶ個数 $k(2k^2-1)$ で表される数。（OEIS [A007588](https://oeis.org/A007588)）"),
    ("ケーキ数", lambda: {(i ** 3 + 5 * i + 6) // 6 for i in range(1, 40)},
     "立方体を $k$ 回の平面切断で分けられる最大領域数 $(k^3+5k+6)/6$。（OEIS [A000125](https://oeis.org/A000125)）"),
    ("幸運数", _seq_lucky,
     "自然数から一定の規則でふるい落として残る数（素数のふるいに似た構成）。（OEIS [A000959](https://oeis.org/A000959)）"),
    ("ウラム数", _seq_ulam,
     "それ以前の相異なる 2 項の和として「ただ 1 通りに」表せる数。（OEIS [A002858](https://oeis.org/A002858)）"),
    ("スミス数", _seq_smith,
     "各位の和が、素因数（重複込み）の各位の和に等しい合成数。（OEIS [A006753](https://oeis.org/A006753)）"),
    ("ナルシシスト数", lambda: {n for n in range(0, _SEQ_LIMIT)
                                if n == sum(d ** len(str(n)) for d in _seq_digits(n))},
     "各位を桁数乗して足すと自身に戻る数（アームストロング数）。（OEIS [A005188](https://oeis.org/A005188)）"),
    ("ズッカーマン数", lambda: {n for n in range(1, _SEQ_LIMIT)
                                if math.prod(_seq_digits(n))
                                and n % math.prod(_seq_digits(n)) == 0},
     "各位の積で割り切れる数。（OEIS [A007602](https://oeis.org/A007602)）"),
    ("多冪数", lambda: {n for n in range(1, _SEQ_LIMIT)
                        if all(e >= 2 for _p, e in prime_factorization(n))},
     "すべての素因数が 2 乗以上で現れる数（パワフル数）。（OEIS [A001694](https://oeis.org/A001694)）"),
    ("アキレス数", lambda: {n for n in range(2, _SEQ_LIMIT)
                            if all(e >= 2 for _p, e in prime_factorization(n))
                            and not _seq_is_perfect_power(n)},
     "多冪数でありながら完全冪ではない数。（OEIS [A052486](https://oeis.org/A052486)）"),
    ("プロス数", _seq_proth,
     "$k \\cdot 2^m + 1$（$k$ は奇数、$k < 2^m$）の形の数。（OEIS [A080075](https://oeis.org/A080075)）"),
    ("レイランド数", _seq_leyland,
     "$x^y + y^x$（$x \\ge y \\ge 2$）の形で表せる数。（OEIS [A076980](https://oeis.org/A076980)）"),
    ("ハミング数", _seq_hamming,
     "素因数が 2, 3, 5 のみからなる数（5-なめらかな数）。（OEIS [A051037](https://oeis.org/A051037)）"),
    ("カプレカ数", _seq_kaprekar,
     "平方を 2 つに分割して足すと元の数に戻る数。（OEIS [A006886](https://oeis.org/A006886)）"),
    ("疑似完全数", _seq_semiperfect,
     "真の約数のうちいくつかの和で自身をちょうど表せる数（半完全数）。（OEIS [A005835](https://oeis.org/A005835)）"),
    ("完全トーシェント数", _seq_perfect_totient,
     "トーシェント関数を 1 になるまで反復適用した値の総和が自身に等しい数。（OEIS [A082897](https://oeis.org/A082897)）"),
    ("調和数（オア数）", lambda: {n for n in range(1, _SEQ_LIMIT)
                        if (n * _seq_tau(n)) % _seq_sigma(n) == 0},
     "約数の調和平均が整数になる数。日本語で $H_n = 1 + 1/2 + \\cdots + 1/n$ を指す『調和数』とは別物。（OEIS [A001599](https://oeis.org/A001599)）"),
    ("超過剰数", lambda: _seq_running_record(lambda n: Fraction(_seq_sigma(n), n)),
     "$\\sigma(n)/n$ がそれ未満のどの数よりも大きい数。（OEIS [A004394](https://oeis.org/A004394)）"),
    ("トーシェント数", _seq_totient_values,
     "ある $m$ について $\\varphi(m)$ の値として現れうる数。（OEIS [A002202](https://oeis.org/A002202)）"),
    ("ファクトリオン", lambda: {n for n in range(1, _SEQ_LIMIT)
                                if n == sum(math.factorial(d) for d in _seq_digits(n))},
     "各位の階乗の和が自身に等しい数。（OEIS [A014080](https://oeis.org/A014080)）"),
    ("交互階乗", lambda: {abs(sum((-1) ** (i - k) * math.factorial(k)
                                  for k in range(1, i + 1))) for i in range(1, 10)},
     "$k! - (k-1)! + \\cdots \\pm 1!$ の形で表される数。（OEIS [A005165](https://oeis.org/A005165)）"),
    ("ベル数", _seq_bell, "集合の分割の総数を与える数列の項。（OEIS [A000110](https://oeis.org/A000110)）"),
    ("モツキン数", _seq_motzkin, "円周上の点を交差せずに結ぶ方法の数を与える数列の項。（OEIS [A001006](https://oeis.org/A001006)）"),
    ("モンモール数", _seq_derangement, "完全順列（どの要素も元の位置に来ない並べ方）の総数。（OEIS [A000166](https://oeis.org/A000166)）"),
    ("オイラー数", _seq_euler_numbers, "正割関数の展開係数として現れる数（A000364）。（OEIS [A000364](https://oeis.org/A000364)）"),
    ("タンジェント数", lambda: {1, 2, 16, 272}, "正接関数の展開係数として現れる数（A000182）。（OEIS [A000182](https://oeis.org/A000182)）"),
    ("フェルマー数", lambda: {2 ** (2 ** i) + 1 for i in range(0, 5)},
     "$2^{2^k} + 1$ の形の数。（OEIS [A000215](https://oeis.org/A000215)）"),
    ("ユークリッド数", lambda: _seq_primorial(+1), "素数階乗に 1 を足した数 $p\\# + 1$。（OEIS [A006862](https://oeis.org/A006862)）"),
    ("クンマー数", lambda: _seq_primorial(-1), "素数階乗から 1 を引いた数 $p\\# - 1$。（OEIS [A057588](https://oeis.org/A057588)）"),
    ("カレン数", lambda: {i * 2 ** i + 1 for i in range(1, 12)}, "$k \\cdot 2^k + 1$ の形の数。（OEIS [A002064](https://oeis.org/A002064)）"),
    ("ウッダル数", lambda: {i * 2 ** i - 1 for i in range(1, 12)}, "$k \\cdot 2^k - 1$ の形の数。（OEIS [A003261](https://oeis.org/A003261)）"),
    ("キャロル数", lambda: {(2 ** i - 1) ** 2 - 2 for i in range(2, 12)},
     "$(2^k - 1)^2 - 2$ の形の数。（OEIS [A093112](https://oeis.org/A093112)）"),
    ("キネア数", lambda: {(2 ** i + 1) ** 2 - 2 for i in range(1, 12)},
     "$(2^k + 1)^2 - 2$ の形の数。（OEIS [A093069](https://oeis.org/A093069)）"),
    ("サービット数", lambda: {3 * 2 ** i - 1 for i in range(0, 12)},
     "$3 \\cdot 2^k - 1$ の形の数（サービト・イブン・クッラ数）。（OEIS [A055010](https://oeis.org/A055010)）"),
    ("トリボナッチ数", lambda: _seq_linear_recurrence(3),
     "直前 3 項の和で定まる数列（0, 0, 1, 1, 2, 4, 7, 13, …）の項。（OEIS [A000073](https://oeis.org/A000073)）"),
    ("テトラナッチ数", lambda: _seq_linear_recurrence(4),
     "直前 4 項の和で定まる数列（0, 0, 0, 1, 1, 2, 4, 8, …）の項。（OEIS [A000078](https://oeis.org/A000078)）"),
    ("ヤーコプスタール数", lambda: _seq_jacobsthal_set(),
     "$J_k = J_{k-1} + 2J_{k-2}$ で定まる数列（0, 1, 1, 3, 5, 11, …）の項。（OEIS [A001045](https://oeis.org/A001045)）"),
    ("ペラン数", lambda: _seq_perrin_set(),
     "$P_k = P_{k-2} + P_{k-3}$ で定まる数列（3, 0, 2, 3, 2, 5, …）の項。（OEIS [A001608](https://oeis.org/A001608)）"),
    ("ピタゴラス素数", lambda: {p for p in range(2, _SEQ_LIMIT)
                                if is_prime(p) and p % 4 == 1},
     "4 で割って 1 余る素数。2 つの平方数の和で一意に表せる。（OEIS [A002144](https://oeis.org/A002144)）"),
    ("平衡素数", _seq_balanced_prime,
     "前後の素数の相加平均にちょうど等しい素数。（OEIS [A006562](https://oeis.org/A006562)）"),
    ("スーパー素数", _seq_prime_indexed_primes,
     "素数列の「素数番目」の項として現れる素数。（OEIS [A006450](https://oeis.org/A006450)）"),
    ("オイラー素数", _seq_euler_polynomial_prime,
     "オイラーの多項式 $n^2 + n + 41$ が与える素数。（OEIS [A005846](https://oeis.org/A005846)）"),
    ("キュバン素数", _seq_cuban_prime,
     "連続する 2 立方数の差 $(x^3-y^3)/(x-y)$（$x = y+1$）として表せる素数。（OEIS [A002407](https://oeis.org/A002407)）"),
    ("陳素数", _seq_chen_prime,
     "$p + 2$ が素数または半素数となる素数 $p$。（OEIS [A109611](https://oeis.org/A109611)）"),
    ("置換可能素数", _seq_permutable_prime,
     "各位をどのように並べ替えても素数になる素数。（OEIS [A003459](https://oeis.org/A003459)）"),
    ("左切り捨て可能素数", lambda: _seq_truncatable_prime(True),
     "上位の桁を 1 桁ずつ落としても常に素数であり続ける素数。（OEIS [A024785](https://oeis.org/A024785)）"),
    ("右切り捨て可能素数", lambda: _seq_truncatable_prime(False),
     "下位の桁を 1 桁ずつ落としても常に素数であり続ける素数。（OEIS [A024770](https://oeis.org/A024770)）"),
    ("メルセンヌ素数", lambda: {2 ** p - 1 for p in (2, 3, 5, 7)},
     "$2^p - 1$（$p$ は素数）の形の素数。（OEIS [A000668](https://oeis.org/A000668)）"),
    ("ワグスタッフ素数", _seq_wagstaff_prime,
     "$(2^p + 1)/3$（$p$ は素数）の形の素数。（OEIS [A000979](https://oeis.org/A000979)）"),
    ("NSW素数", _seq_nsw_prime,
     "ニューマン–シャンクス–ウィリアムズ素数。$S_k = 2S_{k-1} + S_{k-2}$ の奇数番項のうち素数。（OEIS [A088165](https://oeis.org/A088165)）"),
]


def _seq_jacobsthal_set() -> set[int]:
    j = [0, 1]
    while j[-1] < _SEQ_LIMIT:
        j.append(j[-1] + 2 * j[-2])
    return {v for v in j if v < _SEQ_LIMIT}


def _seq_perrin_set() -> set[int]:
    p = [3, 0, 2]
    while p[-1] < _SEQ_LIMIT:
        p.append(p[-2] + p[-3])
    return {v for v in p if v < _SEQ_LIMIT}


_SEQUENCE_TABLE: dict[str, tuple[set[int], str]] | None = None


def _sequence_table() -> dict[str, tuple[set[int], str]]:
    global _SEQUENCE_TABLE
    if _SEQUENCE_TABLE is None:
        _SEQUENCE_TABLE = {
            name: (builder(), desc) for name, builder, desc in _SEQUENCE_SPECS
        }
    return _SEQUENCE_TABLE


def sequence_flag_details(n: int, already: set[str]) -> list[tuple[str, str]]:
    """n が属する数列を（フラグ名, 定義＋この数での根拠）で列挙する。

    `already` に含まれる名前（既存のフラグで説明済みのもの）は重複を避けて除外する。
    """
    details: list[tuple[str, str]] = []
    if not (0 <= n < _SEQ_LIMIT):
        return details

    # 多角数（五角数〜二十角数）はまとめて 1 フラグにする（概要が長くなりすぎるため）
    poly_hits = [(k, i) for k in sorted(_POLYGON_NAME_JA)
                 if (i := _polygonal_index(k, n)) is not None]
    if poly_hits and "多角数" not in already:
        bits = [
            f"{_POLYGON_NAME_JA[k]}（第 {i} 項。$P_{{{k}}}({i}) = {i}\\{{({k}-2)\\cdot{i} - ({k}-4)\\}}/2 = {n}$）"
            for k, i in poly_hits
        ]
        details.append(
            ("多角数",
             "$k$ 角形に点を並べたときの個数 $P_k(i) = i\\{(k-2)i-(k-4)\\}/2$ で表される数"
             "（五角数 OEIS [A000326](https://oeis.org/A000326)、六角数 [A000384](https://oeis.org/A000384) ほか）。"
             + "該当: " + " / ".join(bits)))

    cpoly_hits = [(k, i) for k in sorted(_CENTERED_NAME_JA)
                  if (i := _centered_polygonal_index(k, n)) is not None]
    if cpoly_hits and "中心つき多角数" not in already:
        bits = [f"{_CENTERED_NAME_JA[k]}（第 {i} 項）" for k, i in cpoly_hits]
        details.append(
            ("中心つき多角数",
             "中心の 1 点の周りに $k$ 角形状の層を重ねた個数 $C_k(i) = ki(i-1)/2 + 1$ で表される数"
             "（中心つき三角数 OEIS [A005448](https://oeis.org/A005448)、中心つき四角数 [A001844](https://oeis.org/A001844) ほか）。"
             + "該当: " + " / ".join(bits)))

    oeis_comments = (_load_oeis_comments().get("comments") or {})
    for name, (members, desc) in _sequence_table().items():
        if name in already:
            continue
        if n in members:
            c = oeis_comments.get(name)
            if isinstance(c, dict) and c.get("ja"):
                desc = (desc + " \u30b3\u30e1\u30f3\u30c8\uff08OEIS \u306e\u5f53\u8a72\u6570\u5217\u3088\u308a\u548c\u8a33\u30fb\u8981\u7d04\u3001CC BY-SA 4.0\uff09: " + c["ja"])
            details.append((name, desc))
    return details


def math_flag_details(n: int, info: "NumberInfo") -> list[tuple[str, str]]:
    """概要の数学フラグ全種と、定義＋この数での根拠のペアを返す。"""
    details: list[tuple[str, str]] = []
    if info.is_square:
        k = math.isqrt(n)
        details.append(("平方数", f"整数の 2 乗で表される数。${n} = {k}^2$。"))
    if info.is_cube:
        k = round(n ** (1 / 3))
        details.append(("立方数", f"整数の 3 乗で表される数。${n} = {k}^3$。"))
    if info.is_triangular:
        k = (math.isqrt(8 * n + 1) - 1) // 2
        if k >= 1:
            details.append(
                ("三角数", f"1 から連続する自然数の和で表される数。${n} = 1 + 2 + \\cdots + {k}$（第 {k} 三角数）。"))
        else:
            details.append(("三角数", "三角数列の初項（$T_0 = 0$）とされる。"))
    if info.is_fibonacci:
        details.append(
            ("フィボナッチ数", "フィボナッチ数列（0, 1, 1, 2, 3, 5, 8, …。隣接 2 項の和で定まる）の項。"))
    if info.is_mersenne:
        k = n.bit_length()
        details.append(
            ("メルセンヌ数", f"$2^k - 1$ の形の数。${n} = 2^{{{k}}} - 1$（広義: 指数 {k} が素数とは限らない）。"))
    if info.abundance and info.sum_divisors is not None:
        s = info.sum_divisors
        if info.abundance == "完全数":
            details.append(
                ("完全数", f"約数の総和が自身の 2 倍に等しい数。$\\sigma({n}) = {s} = 2 \\times {n}$。"))
        elif info.abundance == "過剰数":
            details.append(
                ("過剰数", f"約数の総和が自身の 2 倍を上回る数。$\\sigma({n}) = {s} \\gt {2 * n} = 2 \\times {n}$。"))
        else:
            details.append(
                ("不足数", f"約数の総和が自身の 2 倍に満たない数。$\\sigma({n}) = {s} \\lt {2 * n} = 2 \\times {n}$。"))
    details.extend(extra_math_flag_details(n))
    details.extend(sequence_flag_details(n, {name for name, _ in details}))
    return details


# --- Wolfram Knowledgebase 由来の科学データ（tools/wolfram_enrichment_v1.json） ---

WOLFRAM_ENRICHMENT_PATH = Path(__file__).resolve().parent / "wolfram_enrichment_v1.json"
_WOLFRAM_ENRICHMENT_CACHE: dict | None = None

NGC_TYPE_JA = {
    "Galaxy": "銀河",
    "StarCluster": "星団",
    "Nebula": "星雲",
    "Star": "恒星（または星の重なり）",
}

NGC_LIST_URL = "https://en.wikipedia.org/wiki/List_of_NGC_objects_(1%E2%80%931000)"


def _load_wolfram_enrichment() -> dict:
    global _WOLFRAM_ENRICHMENT_CACHE
    if _WOLFRAM_ENRICHMENT_CACHE is None:
        try:
            _WOLFRAM_ENRICHMENT_CACHE = json.loads(
                WOLFRAM_ENRICHMENT_PATH.read_text(encoding="utf-8"))
        except Exception:
            _WOLFRAM_ENRICHMENT_CACHE = {}
    return _WOLFRAM_ENRICHMENT_CACHE


# ---------------------------------------------------------------------------
# 数秘・占術・文化のいわれ（number_lore_v1.json + 機械導出）
# ---------------------------------------------------------------------------

OEIS_COMMENTS_PATH = Path(__file__).resolve().parent / "oeis_comments_ja_v1.json"
_OEIS_COMMENTS_CACHE: dict | None = None


def _load_oeis_comments() -> dict:
    """OEIS の %C コメント和訳（CC BY-SA 4.0、GitHub ミラー oeis/oeisdata 由来）。"""
    global _OEIS_COMMENTS_CACHE
    if _OEIS_COMMENTS_CACHE is None:
        try:
            _OEIS_COMMENTS_CACHE = json.loads(
                OEIS_COMMENTS_PATH.read_text(encoding="utf-8"))
        except Exception:
            _OEIS_COMMENTS_CACHE = {}
    return _OEIS_COMMENTS_CACHE


NUMBER_LORE_PATH = Path(__file__).resolve().parent / "number_lore_v1.json"
_NUMBER_LORE_CACHE: dict | None = None


def _load_number_lore() -> dict:
    global _NUMBER_LORE_CACHE
    if _NUMBER_LORE_CACHE is None:
        try:
            _NUMBER_LORE_CACHE = json.loads(
                NUMBER_LORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            _NUMBER_LORE_CACHE = {}
    return _NUMBER_LORE_CACHE


# 元素の系列（Wolfram ElementData "Series"）の日本語訳
ELEMENT_SERIES_JA = {
    "Nonmetal": "非金属",
    "NobleGas": "貴ガス",
    "AlkaliMetal": "アルカリ金属",
    "AlkalineEarthMetal": "アルカリ土類金属",
    "Metalloid": "半金属",
    "Chalcogen": "カルコゲン（酸素族）",
    "Halogen": "ハロゲン",
    "PoorMetal": "ポスト遷移金属（その他の金属）",
    "TransitionMetal": "遷移金属",
    "Lanthanide": "ランタノイド",
    "Actinide": "アクチノイド",
}

# 星座名（Wolfram Constellation エンティティ）の日本語訳
CONSTELLATION_JA = {
    "Pegasus": "ペガスス座",
    "Pisces": "うお座",
    "Andromeda": "アンドロメダ座",
    "Sculptor": "ちょうこくしつ座",
    "Cetus": "くじら座",
    "Phoenix": "ほうおう座",
    "Tucana": "きょしちょう座",
    "Cassiopeia": "カシオペヤ座",
    "Triangulum": "さんかく座",
    "Aries": "おひつじ座",
    "Eridanus": "エリダヌス座",
    "Fornax": "ろ座",
    "Hydrus": "みずへび座",
    "Horologium": "とけい座",
    "Cepheus": "ケフェウス座",
    "Perseus": "ペルセウス座",
}

# 現代数秘術（ピタゴラス式）の還元値の一般的な象意（要約）
NUMEROLOGY_MEANINGS = {
    1: "自立・開拓・リーダーシップ",
    2: "協調・受容・調和",
    3: "創造・表現・楽観",
    4: "安定・実務・基盤",
    5: "自由・変化・冒険",
    6: "愛情・調和・責任",
    7: "探求・内省・分析",
    8: "実現・豊かさ・力",
    9: "完結・博愛・統合",
    11: "直感・霊感（マスターナンバー）",
    22: "理想の具現化（マスターナンバー）",
    33: "無条件の愛（マスターナンバー）",
}

# エンジェルナンバー解釈でよく用いられる各桁の一般的な象意（要約）
ANGEL_DIGIT_MEANINGS = {
    0: "無限の可能性・始まり",
    1: "新しい始まり・行動",
    2: "調和・信頼",
    3: "創造性・成長",
    4: "安定・基盤",
    5: "変化・転機",
    6: "愛情・バランス",
    7: "内省・幸運",
    8: "豊かさ・循環",
    9: "完結・奉仕",
}

LORE_CATEGORY_ORDER = ["kikkyo", "folklore", "gogen", "meisu", "goro", "fiction"]
LORE_CATEGORY_JA = {
    "kikkyo": "吉凶・忌み数",
    "folklore": "伝承・神話・名数",
    "gogen": "語源・数詞",
    "meisu": "番号のいわれ",
    "goro": "語呂合わせ・スラング",
    "fiction": "創作作品",
}
LORE_MAX_PER_CATEGORY = 3

NUMEROLOGY_URL = "https://ja.wikipedia.org/wiki/%E6%95%B0%E7%A7%98%E8%A1%93"
ANGEL_NUMBER_URL = "https://en.wikipedia.org/wiki/Angel_numbers"
HEBREW_NUMERALS_URL = "https://en.wikipedia.org/wiki/Hebrew_numerals"
GEMATRIA_URL = "https://ja.wikipedia.org/wiki/%E3%82%B2%E3%83%9E%E3%83%88%E3%83%AA%E3%82%A2"
IMIKAZU_URL = "https://ja.wikipedia.org/wiki/%E5%BF%8C%E3%81%BF%E6%95%B0"


def numerology_reduction(n: int) -> tuple[list[int], int]:
    """ピタゴラス式の数字根還元。マスターナンバー（11/22/33）で停止する。

    戻り値: (還元の途中経過のリスト（n 自身を含む）, 最終値)
    """
    chain = [n]
    cur = n
    while cur > 9 and cur not in (11, 22, 33):
        cur = sum(int(ch) for ch in str(cur))
        chain.append(cur)
    return chain, cur


_HEBREW_VALUES = [
    (400, "ת"), (300, "ש"), (200, "ר"), (100, "ק"),
    (90, "צ"), (80, "פ"), (70, "ע"), (60, "ס"), (50, "נ"),
    (40, "מ"), (30, "ל"), (20, "כ"), (10, "י"),
    (9, "ט"), (8, "ח"), (7, "ז"), (6, "ו"), (5, "ה"),
    (4, "ד"), (3, "ג"), (2, "ב"), (1, "א"),
]


def hebrew_numeral(n: int) -> str | None:
    """1〜999 の標準的なヘブライ数字表記（ゲマトリア数価の逆引き）。

    15/16 は神名を避ける慣習に従い ט״ו / ט״ז とする。
    区切り記号は慣例どおり、1文字ならゲレシュ（׳）、複数文字なら
    最終文字の前にゲルシャイム（״）を挿入する。
    """
    if not (1 <= n <= 999):
        return None
    letters: list[str] = []
    rest = n
    for value, letter in _HEBREW_VALUES:
        while rest >= value:
            # 15/16 の特別処理（十の位＋一の位の部分にのみ適用）
            if rest == 15:
                letters.extend(["ט", "ו"])
                rest = 0
                break
            if rest == 16:
                letters.extend(["ט", "ז"])
                rest = 0
                break
            letters.append(letter)
            rest -= value
    if not letters:
        return None
    if len(letters) == 1:
        return letters[0] + "׳"
    return "".join(letters[:-1]) + "״" + letters[-1]


def _numerology_lines(n: int) -> list[str]:
    """全数字に一律で付与する、機械導出のいわれ（数秘・エンジェル・ヘブライ数字）。"""
    lines: list[str] = []

    # 数秘術（現代数秘/カバラ式の還元値）
    if n == 0:
        lines.append(
            "- **数秘術**: 0 は伝統的な数秘術では還元の対象外とされることが多く、"
            f"『無』や『可能性そのもの』を表すとされる（[数秘術]({NUMEROLOGY_URL})参照）"
        )
    else:
        chain, root = numerology_reduction(n)
        if len(chain) == 1:
            chain_text = f"{n}"
        else:
            steps = []
            for i in range(len(chain) - 1):
                digits = " + ".join(list(str(chain[i])))
                steps.append(f"{digits} = {chain[i + 1]}")
            chain_text = " → ".join(steps)
        meaning = NUMEROLOGY_MEANINGS.get(root, "")
        master_note = "（マスターナンバーとして還元を止める流儀がある）" if root in (
            11, 22, 33) else ""
        lines.append(
            f"- **数秘術（現代数秘/カバラ式の還元値）**: {chain_text} — "
            f"還元値 **{root}** の象意は「{meaning}」とされる{master_note}"
            f"（[数秘術]({NUMEROLOGY_URL})参照）"
        )

    # エンジェルナンバー（一般的な解釈の要約）
    digits = [int(ch) for ch in str(n)]
    uniq_digits: list[int] = []
    for d in digits:
        if d not in uniq_digits:
            uniq_digits.append(d)
    digit_parts = "・".join(
        f"{d}（{ANGEL_DIGIT_MEANINGS[d]}）" for d in uniq_digits)
    if len(digits) == 1:
        angel_body = f"「{n}」は {digit_parts} の意味を持つとされる"
    elif len(set(digits)) == 1:
        angel_body = (
            f"「{n}」は {digit_parts} が {len(digits)} 桁重なるゾロ目で、"
            "特に強い意味を持つとされる"
        )
    elif digits == digits[::-1]:
        angel_body = (
            f"「{n}」は桁の {digit_parts} を組み合わせて読むとされ、"
            "左右対称のミラーナンバーとして言及されることがある"
        )
    else:
        angel_body = f"「{n}」は桁の {digit_parts} を組み合わせて読むとされる"
    lines.append(
        f"- **エンジェルナンバー**: {angel_body}"
        f"（一般的な解釈の要約。[Angel numbers]({ANGEL_NUMBER_URL})参照）"
    )

    # ヘブライ数字（ゲマトリア数価の逆引き表記）
    heb = hebrew_numeral(n)
    if heb is not None:
        lines.append(
            f"- **ヘブライ数字（ゲマトリア数価）**: {n} は {heb} と表記される"
            f"（[Hebrew numerals]({HEBREW_NUMERALS_URL})参照）"
        )

    return lines


def lore_flag_names(n: int) -> list[str]:
    """概要フラグ用: このページの『数秘・占術・文化のいわれ』に収録される種類名の一覧。"""
    lore = _load_number_lore()
    names = ["数秘術", "エンジェルナンバー"]
    if 1 <= n <= 999:
        names.append("ヘブライ数字")
    if (lore.get("notable_gematria") or {}).get(str(n)):
        names.append("ゲマトリア（著名な数価）")
    entries = (lore.get("entries") or {}).get(str(n)) or []
    cats_present: list[str] = []
    for item in entries:
        c = item.get("cat") if isinstance(item, dict) else None
        if c and c not in cats_present:
            cats_present.append(c)
    for cat in LORE_CATEGORY_ORDER:
        if cat in cats_present:
            names.append(LORE_CATEGORY_JA.get(cat, cat))
    return names


def render_lore_section_lines(n: int) -> list[str]:
    """『数秘・占術・文化のいわれ』セクションの本文行を生成する。"""
    lore = _load_number_lore()
    lines: list[str] = [
        "このセクションは、数秘術・占い・語呂合わせなど**科学的根拠のない文化的な『いわれ』**を、"
        "百科事典的な要約として収録するものです（効果や真偽を主張するものではありません）。"
        "断定を避け、一次情報へのリンクを付します。\n",
        "### 数秘術・エンジェルナンバー（機械導出）\n",
        *_numerology_lines(n),
    ]

    # ゲマトリア（著名な数価）
    gem = (lore.get("notable_gematria") or {}).get(str(n))
    if gem and isinstance(gem, dict) and gem.get("text"):
        lines.append("\n### ゲマトリア（著名な数価）\n")
        url = gem.get("url", GEMATRIA_URL)
        lines.append(f"- {gem['text']}（参照: {url}）")

    # キュレーション項目（カテゴリごとに上限付きで描画）
    entries = (lore.get("entries") or {}).get(str(n)) or []
    by_cat: dict[str, list[dict]] = {}
    for item in entries:
        if not isinstance(item, dict) or not item.get("text"):
            continue
        by_cat.setdefault(item.get("cat", "meisu"), []).append(item)

    curated_lines: list[str] = []
    for cat in LORE_CATEGORY_ORDER:
        items = by_cat.get(cat) or []
        for item in items[:LORE_MAX_PER_CATEGORY]:
            url = item.get("url")
            ref = f"（参照: {url}）" if url else ""
            curated_lines.append(
                f"- **{LORE_CATEGORY_JA.get(cat, cat)}**: {item['text']}{ref}")
    if curated_lines:
        lines.append("\n### 吉凶・伝承・名数・語呂（キュレーション）\n")
        lines.extend(curated_lines)

    return lines


def build_info(n: int) -> NumberInfo:
    factors = prime_factorization(n)
    factorization = format_factorization(n, factors)

    prime_flag = is_prime(n)
    even_flag = n % 2 == 0
    digit_sum = sum(int(ch) for ch in str(n))

    if n >= 1:
        if n == 1:
            num_divisors = 1
            sum_divisors = 1
            proper_divisor_sum = 0
        else:
            num_divisors, sum_divisors = divisor_count_and_sum(factors)
            proper_divisor_sum = sum_divisors - n
        if n == 0:
            abundance = None
        else:
            if sum_divisors == 2 * n:
                abundance = "完全数"
            elif sum_divisors > 2 * n:
                abundance = "過剰数"
            else:
                abundance = "不足数"
        totient = euler_totient(n, factors)
    else:
        num_divisors = None
        sum_divisors = None
        proper_divisor_sum = None
        abundance = None
        totient = None

    roman = to_roman(n)

    reps = {
        "2進": bin(n)[2:],
        "8進": oct(n)[2:],
        "16進": hex(n)[2:].upper(),
    }
    if roman is not None:
        reps["ローマ数字"] = roman

    jp_kanji = to_japanese_kanji(n)
    jp_daiji = to_japanese_kanji(n, digits=DAIJI_DIGITS, ten="拾", hundred="佰", thousand="阡")
    jp_reading = japanese_reading(n)
    en_words = english_words(n)

    atomic_element = ELEMENTS_JA[n] if 1 <= n < len(ELEMENTS_JA) else None

    return NumberInfo(
        n=n,
        factorization=factorization,
        is_prime=prime_flag,
        is_even=even_flag,
        digit_sum=digit_sum,
        num_divisors=num_divisors,
        sum_divisors=sum_divisors,
        proper_divisor_sum=proper_divisor_sum,
        abundance=abundance,
        totient=totient,
        is_square=is_perfect_square(n),
        is_cube=is_perfect_cube(n),
        is_triangular=is_triangular(n),
        is_fibonacci=is_fibonacci(n),
        is_mersenne=is_mersenne(n),
        representations=reps,
        jp_kanji=jp_kanji,
        jp_daiji=jp_daiji,
        jp_reading=jp_reading,
        en_words=en_words,
        atomic_element=atomic_element,
    )


def rel_link(from_path: Path, to_path: Path) -> str:
    return Path(os.path.relpath(to_path, start=from_path.parent)).as_posix()


def parse_only_numbers(spec: str) -> list[int]:
    # Examples: "444" / "0-99" / "444,42,100-120"
    spec = spec.strip()
    if not spec:
        raise ValueError("empty spec")

    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start = int(a.strip())
            end = int(b.strip())
            if start > end:
                start, end = end, start
            out.update(range(max(start, 0), min(end, MAX_NUMBER) + 1))
        else:
            n = int(part)
            if 0 <= n <= MAX_NUMBER:
                out.add(n)
    return sorted(out)


def number_file_path(n: int) -> Path:
    return NUMBERS_DIR / number_folder(n) / f"{n:03d}.md"


def _format_wikidata_refs(refs: Sequence[object], limit: int = 10) -> list[str]:
    # `WikidataRef` のように `.label` と `.url` を持つ型を想定
    shown = refs[:limit]
    lines = [f"- {getattr(r, 'label')}（{getattr(r, 'url')}）" for r in shown]
    remaining = len(refs) - len(shown)
    if remaining > 0:
        lines.append(f"- 他 {remaining} 件")
    return lines


def render_number_page(
    info: NumberInfo,
    wikidata: WikidataEnrichment | None,
    wikipedia_intros: dict[int, str] | None,
    wikipedia_properties: dict[int, list[str]] | None,
    wikipedia_properties_legacy: dict[int, list[str]] | None,
    wikipedia_other_items: dict[int, list[str]] | None,
    wikipedia_other_items_legacy: dict[int, list[str]] | None,
    wikipedia_pins: dict[int, dict[str, list[str]]] | None = None,
) -> str:
    n = info.n

    def _merge_current_legacy(
        current: list[str] | None,
        legacy: list[str] | None,
    ) -> list[str]:
        cur = [s for s in (current or []) if isinstance(s, str) and s.strip()]
        leg = [s for s in (legacy or []) if isinstance(s, str) and s.strip()]
        if not cur and not leg:
            return []
        cur_set = set(cur)
        out: list[str] = []
        out.extend(cur)
        for s in leg:
            if s in cur_set:
                continue
            out.append(s)
        return out
    prev_path = number_file_path(n - 1) if n > 0 else None
    next_path = number_file_path(n + 1) if n < MAX_NUMBER else None

    here = number_file_path(n)

    nav_parts: list[str] = []
    if prev_path is not None:
        nav_parts.append(f"前: [{n-1:03d}]({rel_link(here, prev_path)})")
    if next_path is not None:
        nav_parts.append(f"次: [{n+1:03d}]({rel_link(here, next_path)})")

    category_bits: list[str] = []
    if info.is_prime:
        category_bits.append("素数")
    elif n in (0, 1):
        category_bits.append("特殊")
    else:
        category_bits.append("合成数")

    category_bits.append("偶数" if info.is_even else "奇数")

    flag_details = math_flag_details(n, info)
    math_flag_names = [name for name, _ in flag_details]

    reps_lines = "\n".join(
        [f"- **{k}**: `{v}`" for k, v in info.representations.items()])

    factorization_katex = _to_katex_math(info.factorization)
    math_lines: list[str] = [
        f"- **素因数分解**: ${factorization_katex}$",
        f"- **各位の和**: {info.digit_sum}",
    ]

    if n >= 1:
        math_lines.extend(
            [
                f"- **約数の個数**: {info.num_divisors}",
                f"- **約数の和**: {info.sum_divisors}",
                f"- **真の約数の和**: {info.proper_divisor_sum}",
                f"- **オイラーのトーシェント関数** $\\varphi({n})$: {info.totient}",
            ]
        )
    if flag_details:
        math_lines.append("- **フラグの解説**（概要のフラグに対応。機械導出・検算済み）:")
        for _fname, _fdetail in flag_details:
            math_lines.append(f"  - **{_fname}**: {_fdetail}")

    science_lines: list[str] = []
    _enrich = _load_wolfram_enrichment()
    ngc = _enrich.get("ngc") or {}
    # The original Wolfram snapshot covers NGC 1–999 and has no range field.
    ngc_first, ngc_last = ngc.get("range", (1, 999))
    ngc_type = None
    if ngc_first <= n <= ngc_last:
        ngc_type = ngc.get("exceptions", {}).get(str(n), ngc.get("default"))
    if info.atomic_element is not None:
        # Wikipedia の各元素ページは安定しているので、最小限の一次資料リンクとして付ける
        _el = (_enrich.get("elements") or {}).get(str(n)) or {}
        _el_bits: list[str] = []
        _series = ELEMENT_SERIES_JA.get(_el.get("series") or "")
        _period = _el.get("period")
        if _series and _period:
            _el_bits.append(f"第{_period}周期の{_series}に属する元素")
        elif _series:
            _el_bits.append(f"{_series}に属する元素")
        _aw = _el.get("atomic_weight")
        if isinstance(_aw, (int, float)):
            _aw_text = f"{_aw:g}"
            _el_bits.append(f"標準原子量はおよそ {_aw_text}")
        _dy = _el.get("discovery_year")
        if isinstance(_dy, int):
            if _dy < 1000:
                _el_bits.append("古代から知られる")
            else:
                _el_bits.append(f"{_dy}年発見")
        _sym = _el.get("symbol")
        _sym_text = f"（{_sym}）" if _sym else ""
        _detail = "。" + "、".join(_el_bits) if _el_bits else ""
        science_lines.append(
            f"- **原子番号**: {info.atomic_element}{_sym_text}{_detail}"
            f"（[元素](https://ja.wikipedia.org/wiki/{info.atomic_element})参照。詳細データ: Wolfram Knowledgebase）"
        )

    if n >= 1:
        _mp_name = (_enrich.get("minor_planets") or {}).get(str(n))
        if _mp_name:
            _mp_year = (_enrich.get(
                "minor_planet_discovery_years") or {}).get(str(n))
            _mp_year_text = f"{_mp_year}年に発見された、" if isinstance(
                _mp_year, int) else ""
            science_lines.append(
                f"- **小惑星**: 小惑星番号 {n} の小惑星は、{_mp_year_text}「{_mp_name}」"
                f"（一次情報: [JPL Small-Body Database](https://ssd.jpl.nasa.gov/tools/sbdb_lookup.html#/?sstr={n})"
                "。名称・発見年データ: Wolfram Knowledgebase）"
            )
        if ngc_type:
            _const = (_enrich.get("ngc_constellations") or {}).get(str(n))
            _const_ja = CONSTELLATION_JA.get(_const or "", _const)
            _const_text = f"{_const_ja}にある" if _const_ja else ""
            if ngc_type == "?":
                science_lines.append(
                    f"- **天文（NGC）**: NGC {n} は同定が難しい・欠番とされることがある番号です"
                    f"（[NGC天体一覧]({NGC_LIST_URL})参照）"
                )
            else:
                science_lines.append(
                    f"- **天文（NGC）**: NGC {n} は{_const_text}{NGC_TYPE_JA.get(ngc_type, ngc_type)}に分類される天体です"
                    f"（[NGC天体一覧]({NGC_LIST_URL})参照。分類・星座データ: Wolfram Knowledgebase）"
                )

    if not science_lines:
        science_lines.append("- （要約可能な一次情報が見つかったら追記）")

    culture_lines: list[str] = [
        f"- **日本語（漢数字）**: {info.jp_kanji}",
        f"- **日本語（大字）**: {info.jp_daiji}",
        f"- **日本語（読み）**: {info.jp_reading}",
        f"- **英語**: {info.en_words}",
    ]
    if n >= 1:
        culture_lines.append(
            f"- **西暦**: [{n}年](https://ja.wikipedia.org/wiki/{n}%E5%B9%B4)（ユリウス暦）の出来事は Wikipedia 参照"
        )

    wikipedia_points: list[str] = []
    # 注: 分類（素数/合成数）や数学フラグの機械由来の要点は『数学的性質』の
    # 「フラグの解説」に集約し、ここでは Wikipedia 固有の情報のみを載せる（重複回避）。

    intro_extract = (wikipedia_intros or {}).get(n)
    if intro_extract and _looks_like_number_wikipedia_intro(intro_extract):
        facts = extract_wikipedia_facts(intro_extract)
        prime_index = facts.get("prime_index")
        if info.is_prime and isinstance(prime_index, int):
            wikipedia_points.append(
                f"- {prime_index}番目の素数として説明される（Wikipedia参照）")

        fib_index = facts.get("fibonacci_index")
        if info.is_fibonacci and isinstance(fib_index, int):
            wikipedia_points.append(
                f"- {fib_index}番目のフィボナッチ数として説明される（Wikipedia参照）")

        tri_index = facts.get("triangular_index")
        if info.is_triangular and isinstance(tri_index, int):
            wikipedia_points.append(
                f"- {tri_index}番目の三角数として説明される（Wikipedia参照）")

        perfect_index = facts.get("perfect_index")
        if info.abundance == "完全数" and isinstance(perfect_index, int):
            wikipedia_points.append(
                f"- {perfect_index}番目の完全数として説明される（Wikipedia参照）")

        terms = facts.get("terms")
        if isinstance(terms, list):
            skip_terms: set[str] = set()
            skip_terms.update(["素数", "合成数", "平方数", "立方数",
                              "三角数", "フィボナッチ数", "メルセンヌ数"])
            if info.abundance:
                skip_terms.add(info.abundance)
            shown_terms = [t for t in terms if isinstance(
                t, str) and t not in skip_terms][:5]
            for t in shown_terms:
                wikipedia_points.append(f"- {t}（Wikipedia参照）")

        props_pairs = _merge_current_legacy(
            (wikipedia_properties or {}).get(n),
            (wikipedia_properties_legacy or {}).get(n),
        )
        if props_pairs:
            for s in props_pairs:
                if not isinstance(s, str) or not s.strip():
                    continue
                excerpt = _sanitize_excerpt(s)
                excerpt = re.sub(r"^\(\s*\)\s*", "", excerpt)
                excerpt = re.sub(
                    r"^[（(]\s*[0-9一二三四五六七八九十]*\s*[)）]\s*", "", excerpt)
                if not excerpt:
                    continue
                _gate = _split_math_prefix(excerpt)
                if _gate and _math_prefix_is_false(_gate[0]):
                    # 数学的に誤りの等式（出典側の誤植や抽出破損）は掲載しない
                    continue
                omitted = False
                if len(excerpt) > 140:
                    excerpt = excerpt[:140].rstrip() + "…"
                    omitted = True
                split = _split_math_prefix(excerpt)
                if split:
                    prefix, remainder = split
                    normalized = _to_katex_math(prefix)
                    if not _katex_balanced(normalized):
                        # \left/\right や括弧が不均衡な壊れた式は整形しない（素の引用のまま）
                        split = None
                if split:
                    formatted_sentence = f"${normalized}${remainder}".strip()
                    notes: list[str] = ["表記を整形"]
                    if omitted:
                        notes.append("一部省略")
                    note_text = " / " + " / ".join(notes) if notes else ""
                    wikipedia_points.append(
                        f"- Wikipedia『性質』より（短い引用・整形）: 「{formatted_sentence}」（出典: https://ja.wikipedia.org/wiki/{n}#%E6%80%A7%E8%B3%AA / CC BY-SA{note_text}）"
                    )
                else:
                    note = "一部省略" if omitted else ""
                    wikipedia_points.append(
                        f"- Wikipedia『性質』より（短い引用）: 「{excerpt}」（出典: https://ja.wikipedia.org/wiki/{n}#%E6%80%A7%E8%B3%AA / CC BY-SA{(' / ' + note) if note else ''}）"
                    )

    other_points: list[str] = []

    other_pairs = _merge_current_legacy(
        (wikipedia_other_items or {}).get(n),
        (wikipedia_other_items_legacy or {}).get(n),
    )
    if other_pairs:
        pinned_for_n = (wikipedia_pins or {}).get(n, {}).get("other")
        other_pairs = _filter_wikipedia_other_excerpts_for_number(
            other_pairs, n, pinned_substrings=pinned_for_n)
    if other_pairs:
        for s in other_pairs:
            if not isinstance(s, str) or not s.strip():
                continue
            excerpt = _sanitize_excerpt(s)
            excerpt = re.sub(r"^\(\s*\)\s*", "", excerpt)
            excerpt = re.sub(
                r"^[（(]\s*[0-9一二三四五六七八九十]*\s*[)）]\s*", "", excerpt)
            if not excerpt:
                continue
            _gate = _split_math_prefix(excerpt)
            if _gate and _math_prefix_is_false(_gate[0]):
                continue

            # Avoid duplication with the dedicated Science section.
            if info.atomic_element is not None and "原子番号" in excerpt:
                continue

            omitted = False
            if len(excerpt) > 160:
                excerpt = excerpt[:160].rstrip() + "…"
                omitted = True
            split = _split_math_prefix(excerpt)
            if split:
                prefix, remainder = split
                normalized = _to_katex_math(prefix)
                if not _katex_balanced(normalized):
                    # \left/\right や括弧が不均衡な壊れた式は整形しない（素の引用のまま）
                    split = None
            if split:
                formatted_sentence = f"${normalized}${remainder}".strip()
                notes: list[str] = ["表記を整形"]
                if omitted:
                    notes.append("一部省略")
                note_text = " / " + " / ".join(notes) if notes else ""
                other_points.append(
                    f"- Wikipedia『その他』より（短い引用・整形）: 「{formatted_sentence}」（出典: https://ja.wikipedia.org/wiki/{n}#%E3%81%9D%E3%81%AE%E4%BB%96 / CC BY-SA{note_text}）"
                )
            else:
                note = "一部省略" if omitted else ""
                other_points.append(
                    f"- Wikipedia『その他』より（短い引用）: 「{excerpt}」（出典: https://ja.wikipedia.org/wiki/{n}#%E3%81%9D%E3%81%AE%E4%BB%96 / CC BY-SA{(' / ' + note) if note else ''}）"
                )

    # The intro sentence is a generic definition. Use it only as a last resort
    # when there are no other "その他" excerpts.
    if (not other_points) and intro_extract and _looks_like_number_wikipedia_intro(intro_extract):
        facts = extract_wikipedia_facts(intro_extract)
        first_sentence = facts.get("first_sentence")
        if isinstance(first_sentence, str) and first_sentence:
            # Keep it short: this is a *very* small excerpt.
            excerpt = first_sentence
            omitted = False
            if len(excerpt) > 120:
                excerpt = excerpt[:120].rstrip() + "…"
                omitted = True
            note = "一部省略" if omitted else ""
            # Attribution + license hint to stay CC BY-SA-friendly.
            other_points.append(
                f"- Wikipedia冒頭（短い引用）: 「{excerpt}」（出典: https://ja.wikipedia.org/wiki/{n} / CC BY-SA{(' / ' + note) if note else ''}）"
            )

    wikipedia_points = _dedupe_preserve_order(wikipedia_points)
    other_points = _dedupe_preserve_order(other_points)

    wikidata_number_lines: list[str] = []
    if wikidata is not None:
        item = wikidata.number_items.get(n)
        if item is not None:
            desc = f"（説明: {item.description_ja}）" if item.description_ja else ""
            wikidata_number_lines.append(f"- Wikidata: {item.url}{desc}")

    tech_code_lines: list[str] = []
    # HTTP status code (100-599): 実在するコードのみ詳細リンクを出力する
    if 100 <= n <= 599:
        http_entry = HTTP_STATUS_PAGES.get(n)
        tech_code_lines.append("### HTTP ステータスコード（該当する場合）")
        if http_entry is not None:
            http_path, http_has_mdn = http_entry
            if "implementation-dependent" in http_path:
                tech_code_lines.append(
                    "- この数字は、特定の実装（nginx / Cloudflare / プロキシ慣行など）で用いられる**非標準**の HTTP ステータスコードです（意味は要約し、一次情報へリンクします）。"
                )
            else:
                tech_code_lines.append(
                    "- この数字は HTTP ステータスコードとして用いられます（意味・典型例は要約し、一次情報へリンクします）。"
                )
            if http_has_mdn:
                tech_code_lines.append(
                    f"- MDN: https://developer.mozilla.org/ja/docs/Web/HTTP/Status/{n}"
                )
            tech_code_lines.append(
                f"- 解説（チートシート）: {HTTP_STATUS_CODES_REPO_BASE}{http_path}"
            )
            tech_code_lines.append(
                f"- 参照（チートシート目次）: {HTTP_STATUS_CODES_REPO_INDEX}"
            )
        else:
            tech_code_lines.append(
                "- この数字は、IANA 登録済みおよび主要実装の HTTP ステータスコードとしては割り当てられていません（RFC 9110 では未知のコードは同クラスの `x00` と等価に扱われます）。"
            )
            tech_code_lines.append(f"- IANA レジストリ: {IANA_HTTP_STATUS_REGISTRY}")
            tech_code_lines.append(
                f"- 参照（チートシート目次）: {HTTP_STATUS_CODES_REPO_INDEX}"
            )

    if wikidata is not None:
        iso = wikidata.iso3166_numeric.get(n)
        if iso:
            tech_code_lines.append("### ISO 3166-1 numeric（国・地域の3桁コード）")
            tech_code_lines.append(
                "- ISO 3166-1 の数値コードとして、この数字が割り当てられている場合があります（一次情報は Wikidata へ）。"
            )
            tech_code_lines.extend(_format_wikidata_refs(iso, limit=10))

        tel = wikidata.tel_country_code.get(n)
        if tel:
            tech_code_lines.append("### 国番号（国際電話・E.164）")
            tech_code_lines.append(
                "- 国番号（国際電話識別番号）として、この数字が用いられる場合があります（一次情報は Wikidata へ）。"
            )
            tech_code_lines.extend(_format_wikidata_refs(tel, limit=10))

    # 7400 series logic number hints
    logic_hint = LOGIC_74XX_HINTS.get(n)
    logic_number = f"{n:02d}" if n < 100 else str(n)
    tech_code_lines.append("### 7400シリーズ（汎用ロジックICのロジック番号として）")
    if n < 100 or logic_hint is not None:
        tech_code_lines.append(
            f"- ロジック番号 `{logic_number}` は、`74xx{logic_number}`（例: `74HC{logic_number}` / `74LS{logic_number}` など）として現れることがあります。"
        )
    else:
        tech_code_lines.append(
            "- 7400シリーズのロジック番号は 2桁（00/04/74 など）や代表的な3桁（245/374 など）が中心です。"
        )
        tech_code_lines.append(
            f"- `{n}` が直接のロジック番号として一般的かはシリーズ/メーカーに依存するため、まず一覧で該当有無を確認してください。"
        )

    if logic_hint is not None:
        tech_code_lines.append(f"- 代表的な機能（目安）: {logic_hint}")
    tech_code_lines.append(f"- 一覧（一次情報への入口）: {LIST_7400_WIKIPEDIA_EN}")

    # --- 概要の「フラグ」: このページに収録されている『いわれ』の種類を全域から列挙 ---
    science_flag_names: list[str] = []
    if info.atomic_element is not None:
        science_flag_names.append(f"原子番号（{info.atomic_element}）")
    if n >= 1:
        if (_enrich.get("minor_planets") or {}).get(str(n)):
            science_flag_names.append("小惑星")
        if ngc_type and ngc_type != "?":
            science_flag_names.append(f"NGC天体（{NGC_TYPE_JA.get(ngc_type, ngc_type)}）")

    code_flag_names: list[str] = []
    if 100 <= n <= 599 and HTTP_STATUS_PAGES.get(n) is not None:
        code_flag_names.append("HTTPステータスコード")
    if wikidata is not None:
        if wikidata.iso3166_numeric.get(n):
            code_flag_names.append("ISO 3166-1")
        if wikidata.tel_country_code.get(n):
            code_flag_names.append("国番号（E.164）")
    if n < 100 or LOGIC_74XX_HINTS.get(n) is not None:
        code_flag_names.append("7400シリーズ")

    lore_flags = lore_flag_names(n)

    overview_flag_lines: list[str] = [
        "- **フラグ（数学）**: "
        + (" / ".join(math_flag_names) if math_flag_names else "（特記事項なし）")
    ]
    if science_flag_names:
        overview_flag_lines.append(
            "- **フラグ（科学・技術）**: " + " / ".join(science_flag_names))
    if code_flag_names:
        overview_flag_lines.append(
            "- **フラグ（規格・コード）**: " + " / ".join(code_flag_names))
    overview_flag_lines.append(
        "- **フラグ（文化・いわれ）**: " + " / ".join(lore_flags))
    overview_flag_lines.append(
        "- 各フラグの詳しい解説は、ページ内の対応するセクション"
        "（『数学的性質』のフラグの解説 / 『科学・技術』 / 『規格・コード』 / 『数秘・占術・文化のいわれ』）を参照してください（解説は各セクション 1 箇所に集約し、重複させません）。"
    )

    wikipedia_en_ref = f"- Wikipedia（英語）: https://en.wikipedia.org/wiki/{n}"
    thousand_article = "https://en.wikipedia.org/wiki/1000_%28number%29"
    if n == 1000:
        wikipedia_en_ref = f"- Wikipedia（英語）: [1000（数）]({thousand_article})"
    elif 1001 <= n <= 1199:
        first, last = (1001, 1099) if n < 1100 else (1100, 1199)
        wikipedia_en_ref = (
            f"- Wikipedia（英語）: [{first}〜{last} の数の一覧]"
            f"({thousand_article}#{first}_to_{last})"
        )
    refs = [
        f"- Wikipedia（日本語）: https://ja.wikipedia.org/wiki/{n}",
        wikipedia_en_ref,
        f"- OEIS 検索: https://oeis.org/search?q={n}&language=english",
        "- 数列の一覧（OEIS, CC BY-SA 4.0）: 各フラグに付した A 番号から個別の数列ページへ辿れます。",
    ]

    license_lines = [
        "- 本ページは CC BY-SA 4.0 のリポジトリ内コンテンツです。",
        "- Wikipedia のテキストは CC BY-SA（表示-継承）で提供されています。Wikipedia 本文を引用/転載する場合は、出典URL・ライセンス・変更有無を明記してください。",
        "- Wikidata の構造化データは CC0 です（本ページの一部データに利用）。",
    ]

    if nav_parts:
        nav = " / ".join(nav_parts)
        nav_line = f"{nav}\n"
    else:
        nav_line = ""

    def _link_cell(num: int) -> str:
        if not (0 <= num <= MAX_NUMBER):
            return "—"
        return f"[{num:03d}]({rel_link(here, number_file_path(num))})"

    index_link = f"[index.md]({rel_link(here, ROOT / 'index.md')})"
    repo_links_lines = [
        "## リポジトリ内リンク\n",
        f"- 入口: {index_link}",
        "",
        "| -100 | -10 | -1 | +1 | +10 | +100 |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| {_link_cell(n-100)} | {_link_cell(n-10)} | {_link_cell(n-1)} | {_link_cell(n+1)} | {_link_cell(n+10)} | {_link_cell(n+100)} |",
        "",
    ]

    title = f"# {n}（{n:03d}）\n"

    content = "\n".join(
        [
            title,
            nav_line,
            f"> 分類: {' / '.join(category_bits)}\n",
            *repo_links_lines,
            "## 概要\n",
            *overview_flag_lines,
            "\n## 数学的性質\n",
            *math_lines,
            "\n## 表記\n",
            reps_lines,
            "\n## Wikipedia（要点）\n",
            "Wikipedia の『性質』『その他』は有用な入口ですが、本文の長文転載は避け、要点のみ要約してリンクします。\n",
            "### 性質（要約）\n",
            *(wikipedia_points if wikipedia_points else
              ["- 機械導出できる分類・性質の解説は『数学的性質』のフラグの解説に集約しています（重複回避）。追加の要点は Wikipedia を参照。"]),
            "\n### その他（要約）\n",
            *(other_points if other_points else ["- （要約可能な関連が見つかったら追記）"]),
            "\n### Wikidata（CC0）\n",
            *(wikidata_number_lines if wikidata_number_lines else ["- （該当するWikidata項目が見つかったら追記）"]),
            "\n## 科学・技術（例）\n",
            *science_lines,
            "\n## 規格・コード（技術運用の例）\n",
            *tech_code_lines,
            "\n## 文化・言語（例）\n",
            *culture_lines,
            "\n## 数秘・占術・文化のいわれ\n",
            *render_lore_section_lines(n),
            "\n## 参考\n",
            *refs,
            "\n## 出典・ライセンス\n",
            *license_lines,
            "",
        ]
    )
    # GitHub Pages（Jekyll/Liquid）が `{{` / `{%` を構文として誤認して
    # ビルドに失敗しないよう、表示に影響しない空白を挿入して無害化する。
    return content.replace("{{", "{ {").replace("{%", "{ %")


def render_index() -> str:
    lines: list[str] = []
    lines.append("# Index\n")
    lines.append("## 概要\n")
    lines.append(
        f"0〜{MAX_NUMBER} の数字について、数学的な性質（素因数分解・約数・表記など）と、科学/文化に関する一次情報（主に Wikipedia）への導線をまとめたチートシート集です。\n"
    )
    lines.append("- 本文は `numbers/` 配下（基本は 1 数字 = 1 ファイル）")
    lines.append(
        f"- 0〜999 は百の位別のフォルダに3桁で、1000〜{MAX_NUMBER} は `numbers/1xxx/` に4桁で収録します（例: `numbers/0xx/031.md`、`numbers/1xxx/1000.md`）。\n")

    lines.append("## 運用ヒント\n")
    lines.append("- 数字を含む範囲の表から探す")
    lines.append("- 各ページ末尾の Wikipedia リンクから一次情報へ\n")

    for folder, group in groupby(range(MAX_NUMBER + 1), key=number_folder):
        numbers = list(group)
        start, end = numbers[0], numbers[-1]
        lines.append(f"## {folder}（{start:03d}〜{end:03d}）\n")
        lines.append("| " + " | ".join([f"{i}" for i in range(10)]) + " |")
        lines.append("| " + " | ".join(["---" for _ in range(10)]) + " |")
        for row_start in range(start, end + 1, 10):
            row: list[str] = []
            for n in range(row_start, row_start + 10):
                if n > end:
                    row.append("")
                else:
                    path = number_file_path(n).relative_to(ROOT).as_posix()
                    row.append(f"[{n:03d}]({path})")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    return "\n".join(lines)


def render_readme() -> str:
    return "\n".join(
        [
            f"# CheatSheet of Numbers (0-{MAX_NUMBER})",
            "",
            f"0〜{MAX_NUMBER} の数字について、数学的な性質と、科学/文化に関する一次情報への導線をまとめたチートシート集です。",
            "",
            "- 入口: [index.md](index.md)",
            "- ブラウザ閲覧（GitHub Pages）: https://radiann-kswg.github.io/CheatSheet-of_Numbers/",
            f"- 個別ページ: 0〜999 は `numbers/0xx/`〜`numbers/9xx/`、1000〜{MAX_NUMBER} は [numbers/1xxx/](numbers/1xxx/) に収録しています。",
            "- 一部の規格・コード情報は Wikidata（CC0）から自動取得して補強します",
            "- Wikipedia（日本語）の冒頭（概要）に加え、『性質』『その他』から短い引用を抽出して要点の入口を補強します（長文転載はしません）",
            "- 元素・小惑星・NGC 天体の詳細（分類・原子量・発見年・星座など）は Wolfram Knowledgebase 由来のデータ（`tools/wolfram_enrichment_v1.json`）で補強します",
            "- 数秘術・エンジェルナンバー・吉凶・語呂合わせなどの『文化的ないわれ』も収録します（機械導出＋`tools/number_lore_v1.json` のキュレーション。科学的根拠のない伝承である旨を明記）",
            "- 多角数・幸運数・ウラム数・各種特殊素数など **約 60 種の数列への所属** を自前計算で判定し、出典として OEIS の A 番号リンクを添えます（0〜999 の全域を OEIS の公表値と照合済み）",
            "- 数列の補足コメントは OEIS（CC BY-SA 4.0）の和訳を `tools/oeis_comments_ja_v1.json` に収録しています",
            "- 中国語圏の数字文化・英語数詞の語源・パブリックドメイン古典などは、再利用可能なライセンスのものだけを和訳して収録します",
            "",
            "## 方針（公開に耐えるための注意）",
            "",
            "- 外部サイトの本文を長文転載しません（要約＋参照リンク中心）。",
            "- 引用する場合は短くし、出典 URL を必ず添えます。",
            "- 数式表記を KaTeX に整形して掲載する場合は、改変がある旨（例: 『短い引用・整形』）を明記します。",
            "- 数秘・占術などのいわれは断定を避け（『〜とされる』）、科学的事実と区別して掲載します。性的・差別的・反社会的な含意のスラングや、現役占術家の独自体系（数意学・数魂など）は収録しません。",
            "- 外部データを取り込むのは、利用規約が **CC BY-SA 4.0 での再配布** と **プログラムによる取得** の両方を許す場合に限ります（採否の一覧は [AGENTS.md](AGENTS.md) の『情報源とライセンス』を参照）。",
            "- 和訳して収録する場合は翻案にあたるため、出典・ライセンス・『翻訳による改変あり』を必ず併記します。",
            "",
            "## ライセンス",
            "",
            "本リポジトリは **CC BY-SA 4.0** です。詳細は [LICENSE](LICENSE) を参照してください。",
            "",
            "- Wikidata の構造化データは CC0（パブリックドメイン相当）です。取得したデータの出典は各ページの Wikidata リンクを参照してください。",
            "- OEIS（The Online Encyclopedia of Integer Sequences, https://oeis.org/ ）は CC BY-SA 4.0 です。本リポジトリは数列の A 番号リンクと、コメントの和訳・要約を収録しています。",
            "- パブリックドメインの古典（例: W. W. Westcott, \"Numbers: Their Occult Power and Mystic Virtues\", 1911）に由来する記述は、その旨を各項目に明記しています。",
            "",
            "## 生成について",
            "",
            "このリポジトリの `numbers/` 以下は、`tools/generate_numbers.py` で生成できます。",
            "",
            "- 依存: Python 標準ライブラリのみ（追加の `pip install` は不要）",
            "",
            "```powershell",
            "python tools/generate_numbers.py",
            "```",
            "",
            "- VS Code を使う場合は、`Terminal: Run Task` から生成タスクを実行できます（Python 拡張が選択中のインタープリタを使用）。",
            "- macOS/Linux で venv（任意）: `python3 -m venv .venv` → `.venv/bin/python tools/generate_numbers.py`",
            "- Windows で venv（任意）: `py -3 -m venv .venv` → `.venv\\Scripts\\python tools\\generate_numbers.py`",
            "",
            "### 相対リンク（リポジトリ内）",
            "",
            "各数字ページに `リポジトリ内リンク` を自動出力し、近傍（±1/±10/±100）に移動できる相対リンクを付与します。",
            "",
            "### Wikipedia 引用（性質/その他）",
            "",
            "Wikipedia の『性質』『その他』セクションから短い引用を抽出するには `--wikipedia-sections` を指定します。",
            "",
            "```powershell",
            "python tools/generate_numbers.py --wikipedia-sections",
            "```",
            "",
            "- セクション取得キャッシュを更新したい場合: `--refresh-wikipedia-sections`",
            "- ネットワーク無しで生成したい場合: `--offline`（キャッシュのみ使用）",
            "",
            "特定の固有名詞を含む引用を優先したい場合は pins 設定で部分一致ピン留めできます:",
            "- pins: `tools/wikipedia_ja_pins_v1.json`",
            "重要度の採用閾値を数字ごとに調整したい場合は上書き設定を使います:",
            "- overrides: `tools/wikipedia_ja_importance_overrides_v1.json`",
            "",
            "Wikidata 連携の制御（任意）:",
            "",
            "```powershell",
            "python tools/generate_numbers.py --no-wikidata",
            "python tools/generate_numbers.py --refresh-wikidata",
            "```",
            "",
            "Wikipedia（日本語）連携の制御（任意）:",
            "",
            "```powershell",
            "python tools/generate_numbers.py --no-wikipedia",
            "python tools/generate_numbers.py --refresh-wikipedia",
            "```",
            "",
            "### 公開（リリース）",
            "",
            "- 生成スクリプト/設定を更新 → `python tools/generate_numbers.py --wikipedia-sections` で全ページ再生成",
            "- 内部リンクが壊れていないことを確認（例: `python tools/check_internal_links.py`）",
            "- ビューアーのフィルタがページのフラグと同期しているか確認（`python tools/check_viewer_filters.py`）",
            "- main に反映後、タグ（例: `vYYYY.MM.DD`）を作成して GitHub Release を作成（差分/変更点を記載）",
            "",
            "## 参考リンク",
            "",
            "- Wikipedia 数の記事（例）: https://ja.wikipedia.org/wiki/31",
            "",
        ]
    )


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Python 3.9's Path.write_text() does not support newline=.
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=f"Generate number cheat sheets (0..{MAX_NUMBER}).")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use cache only; do not fetch from Wikipedia/Wikidata over the network.",
    )
    parser.add_argument(
        "--no-wikidata",
        action="store_true",
        help="Disable Wikidata(CC0) enrichment.",
    )
    parser.add_argument(
        "--refresh-wikidata",
        action="store_true",
        help="Refresh Wikidata cache (tools/_cache).",
    )
    parser.add_argument(
        "--no-wikipedia",
        action="store_true",
        help="Disable Japanese Wikipedia intro fetching.",
    )
    parser.add_argument(
        "--refresh-wikipedia",
        action="store_true",
        help="Refresh Japanese Wikipedia cache (tools/_cache).",
    )
    parser.add_argument(
        "--wikipedia-sections",
        action="store_true",
        help="Fetch Japanese Wikipedia section text (e.g., 性質/その他) to extract non-trivial properties and notable associations.",
    )
    parser.add_argument(
        "--refresh-wikipedia-sections",
        action="store_true",
        help="Refresh Japanese Wikipedia section cache (tools/_cache).",
    )
    parser.add_argument(
        "--only",
        type=str,
        default="",
        help="Generate only specified numbers: e.g. '444' or '0-99' or '444,42,100-120'.",
    )
    args = parser.parse_args()

    only_numbers: list[int] | None = None
    if args.only:
        only_numbers = parse_only_numbers(args.only)
    numbers_to_generate = only_numbers if only_numbers is not None else list(range(MAX_NUMBER + 1))

    wikidata: WikidataEnrichment | None = None
    if not args.no_wikidata:
        try:
            cache_path = ROOT / "tools" / "_cache" / "wikidata_enrichment_v1.json"
            if args.offline:
                print("[phase] Wikidata cache", flush=True)
                if cache_path.exists():
                    wikidata = load_or_build_enrichment(
                        cache_path=cache_path, refresh=False, offline=True)
            else:
                with ProgressSpinner("Wikidata enrichment"):
                    wikidata = load_or_build_enrichment(
                        cache_path=cache_path, refresh=args.refresh_wikidata)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Wikidata enrichment skipped: {e}")

    wikipedia_intros: dict[int, str] | None = None
    if not args.no_wikipedia:
        try:
            cache_path = ROOT / "tools" / "_cache" / "wikipedia_ja_intros_v1.json"
            if args.offline:
                print("[phase] Wikipedia intro cache", flush=True)
                wikipedia_intros = load_or_build_wikipedia_intros_for_numbers(
                    cache_path=cache_path,
                    refresh=args.refresh_wikipedia,
                    numbers=numbers_to_generate,
                    offline=True,
                )
            else:
                with ProgressSpinner("Wikipedia intros"):
                    wikipedia_intros = load_or_build_wikipedia_intros_for_numbers(
                        cache_path=cache_path,
                        refresh=args.refresh_wikipedia,
                        numbers=numbers_to_generate,
                        offline=False,
                    )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Wikipedia intro fetch skipped: {e}")

    wikipedia_properties: dict[int, list[str]] | None = None
    wikipedia_properties_legacy: dict[int, list[str]] | None = None
    wikipedia_other_items: dict[int, list[str]] | None = None
    wikipedia_other_items_legacy: dict[int, list[str]] | None = None

    pins_path = ROOT / "tools" / "wikipedia_ja_pins_v1.json"
    wikipedia_pins = _load_wikipedia_pins_config(pins_path)
    if args.wikipedia_sections:
        try:
            print("[phase] Wikipedia properties", flush=True)
            cache_path = ROOT / "tools" / "_cache" / "wikipedia_ja_properties_v1.json"
            wikipedia_properties, wikipedia_properties_legacy = (
                load_or_build_wikipedia_property_sentence_sets_for_numbers(
                    cache_path=cache_path,
                    refresh=args.refresh_wikipedia_sections,
                    numbers=numbers_to_generate,
                    offline=args.offline,
                )
            )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Wikipedia section fetch skipped: {e}")

        try:
            print("[phase] Wikipedia other items", flush=True)
            cache_path = ROOT / "tools" / "_cache" / "wikipedia_ja_others_v1.json"
            wikipedia_other_items, wikipedia_other_items_legacy = (
                load_or_build_wikipedia_other_item_sets_for_numbers(
                    cache_path=cache_path,
                    refresh=args.refresh_wikipedia_sections,
                    numbers=numbers_to_generate,
                    offline=args.offline,
                )
            )
        except Exception as e:  # noqa: BLE001
            print(f"[warn] Wikipedia other section fetch skipped: {e}")

    # Generate pages
    with ProgressBar(len(numbers_to_generate), "number pages") as progress:
        for completed, n in enumerate(numbers_to_generate, start=1):
            info = build_info(n)
            write_file(
                number_file_path(n),
                render_number_page(
                    info,
                    wikidata,
                    wikipedia_intros,
                    wikipedia_properties,
                    wikipedia_properties_legacy,
                    wikipedia_other_items,
                    wikipedia_other_items_legacy,
                    wikipedia_pins,
                ),
            )
            progress.update(completed, detail=f"{n:03d}.md")

    # Entry points
    write_file(ROOT / "index.md", render_index())
    write_file(ROOT / "README.md", render_readme())

    # Numbers Lore Viewer（index.html / assets/）の検索インデックスを同期する
    if (ROOT / "assets").is_dir():
        try:
            from build_viewer_index import write_viewer_index

            path = write_viewer_index()
            print(f"[info] viewer index updated: {path}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] viewer index update skipped: {e}")


if __name__ == "__main__":
    main()
