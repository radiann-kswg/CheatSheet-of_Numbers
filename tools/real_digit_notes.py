"""実数の十進展開を数字ページの数学ノートに対応付ける。"""

from decimal import Decimal, ROUND_HALF_UP, localcontext
import re


def _leading_digits(value: Decimal, count: int) -> str:
    digits = "".join(map(str, value.as_tuple().digits))
    return digits.ljust(count, "0")[:count]


def _rounded_digits(value: Decimal, count: int) -> tuple[str, str]:
    with localcontext() as context:
        context.prec = count
        context.rounding = ROUND_HALF_UP
        rounded = context.plus(value)
    places = count - 1 - rounded.adjusted()
    if places < 0 or (places == 0 and rounded % 10 == 0):
        # 科学記数法なら 1.00 × 10³ の有効な末尾ゼロも見える。
        mantissa, exponent = f"{rounded:.{count - 1}E}".split("E")
        display = rf"{mantissa} \times 10^{{{int(exponent)}}}"
    else:
        display = f"{rounded:.{places}f}"
    return _leading_digits(rounded, count), display


def build_real_digit_notes(constants: list[dict], max_number: int) -> dict[str, list[dict]]:
    notes: dict[str, list[dict]] = {}
    for constant in constants:
        raw = constant["decimal"]
        if not isinstance(raw, str) or not re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", raw):
            raise ValueError(f"{constant['name']} の decimal は固定小数点の文字列で指定してください")
        value = Decimal(raw)
        if value.is_zero() or len(value.as_tuple().digits) < 5:
            raise ValueError(f"{constant['name']} の decimal には最初の非ゼロ桁から5桁以上を指定してください")

        first3 = _leading_digits(value, 3)
        first4 = _leading_digits(value, 4)
        rounded3, approximation3 = _rounded_digits(value, 3)
        rounded4, approximation4 = _rounded_digits(value, 4)
        # 最初の有効数字8桁と整数部を保ち、長い小数展開を省略する。
        raw = format(value, "f")
        integer, point, fraction = raw.partition(".")
        visible = max(1, 7 - value.adjusted())
        expansion = raw
        if len(fraction) > visible:
            expansion = integer + point + fraction[:visible] + r"\ldots"

        for key in sorted({first3, first4, rounded3, rounded4}, key=int):
            if int(key) > max_number:
                continue

            def mark(digits: str) -> str:
                return f"**{digits}**" if digits == key else digits

            text = (
                f"{constant['description']}十進表記は ${expansion}$ で始まる。"
                f"符号・小数点・先行する0を除くと、先頭3桁は {mark(first3)}、先頭4桁は {mark(first4)}。"
                f"四捨五入すると、有効数字3桁で ${approximation3}$（数字列 {mark(rounded3)}）、"
                f"有効数字4桁で ${approximation4}$（数字列 {mark(rounded4)}）になる。"
            )
            notes.setdefault(key, []).append({
                "title": f"実数の数字列・{constant['name']}（{constant['symbol']}）",
                "text": text,
                "sources": constant["sources"],
            })
    return notes
