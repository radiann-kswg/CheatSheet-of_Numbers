"""ページのフラグと、ビューアーのフィルタ定義が同期しているかを検査する。

`generate_numbers.py` にフラグを追加したのに `build_viewer_index.py` の
PROPERTY_FILTER_DEFS / FLAG_NAME_TO_KEY / LORE_FILTER_DEFS を更新し忘れると、
ページには出るのにビューアーで絞り込めない状態になる。これを機械的に検出する。

使い方:
    python tools/check_viewer_filters.py

終了コード: 0 = 同期している / 1 = 不整合あり
"""
from __future__ import annotations

import json
import sys

import build_viewer_index as bvi
import generate_numbers as gen
from number_range import MAX_NUMBER


def collect_page_flags() -> set[str]:
    """収録範囲の全ページに実際に現れる数学フラグ名を集める。"""
    names: set[str] = set()
    for n in range(MAX_NUMBER + 1):
        info = gen.build_info(n)
        for name, _detail in gen.math_flag_details(n, info):
            names.add(name)
    return names


def check_science_filters() -> list[str]:
    """科学の補足データ、生成済みページの概要、配布用索引を照合する。"""
    index = json.loads(bvi.OUTPUT_PATH.read_text(encoding="utf-8"))
    chips = {d["key"]: d["label"] for d in index["filters"]["properties"]}
    labels = gen.SCIENCE_FILTER_LABELS
    problems = [
        f"[科学チップ定義] '{key}' の表示名は '{label}' が必要"
        for key, label in labels.items() if chips.get(key) != label
    ]
    records = {record["n"]: set(record["propertyFilters"]) for record in index["numbers"]}
    prefix = "- **フラグ（科学・技術）**: "
    for n in range(MAX_NUMBER + 1):
        expected = set(gen.science_filter_keys(n))
        if n not in records:
            problems.append(f"[検索索引] {n} のレコードがありません")
            continue
        indexed = records[n] & labels.keys()
        page = gen.number_file_path(n).read_text(encoding="utf-8")
        overview = next((line[len(prefix):] for line in page.splitlines() if line.startswith(prefix)), "")
        flags = set(overview.split(" / "))
        shown = {key for key, label in labels.items() if label in flags}
        if expected != indexed or expected != shown:
            problems.append(
                f"[科学フラグ] {n}: データ={sorted(expected)}, "
                f"ページ={sorted(shown)}, 索引={sorted(indexed)}"
            )
    return problems


def main() -> int:
    problems = check_science_filters()

    # --- 数学フラグ ---
    page_flags = collect_page_flags()
    mapped = set(bvi.FLAG_NAME_TO_KEY)
    defined_keys = {d["key"] for d in bvi.PROPERTY_FILTER_DEFS}

    for name in sorted(page_flags - mapped):
        problems.append(
            f"[フラグ未マッピング] '{name}' がページに出るが FLAG_NAME_TO_KEY にない")
    for name in sorted(mapped - page_flags):
        problems.append(
            f"[未使用マッピング] '{name}' は FLAG_NAME_TO_KEY にあるが、どのページにも現れない")
    for name, key in sorted(bvi.FLAG_NAME_TO_KEY.items()):
        if key not in defined_keys:
            problems.append(
                f"[チップ定義なし] '{name}' → '{key}' が PROPERTY_FILTER_DEFS にない")

    # --- いわれカテゴリ ---
    lore_keys = {d["key"] for d in bvi.LORE_FILTER_DEFS}
    for cat in gen.LORE_CATEGORY_ORDER:
        if cat not in lore_keys:
            problems.append(
                f"[いわれカテゴリ未定義] '{cat}' が LORE_FILTER_DEFS にない")
    for key in sorted(lore_keys - set(gen.LORE_CATEGORY_ORDER)):
        if key in ("numerology", "gematria"):
            continue  # 全数付与 / 機械導出なのでカテゴリ表には無い
        problems.append(
            f"[いわれカテゴリ余剰] '{key}' は LORE_CATEGORY_ORDER にない")

    # --- OEIS コメント和訳のキー ---
    seq_names = {name for name, _b, _d in gen._SEQUENCE_SPECS}
    comments = (gen._load_oeis_comments().get("comments") or {})
    for name in sorted(set(comments) - seq_names):
        problems.append(
            f"[OEISコメント孤立] oeis_comments_ja_v1.json の '{name}' に対応する数列がない")

    print(f"ページ上の数学フラグ: {len(page_flags)} 種")
    print(f"ビューアーのフィルタ定義: {len(defined_keys)} 種")
    print(f"OEIS コメント和訳: {len(comments)} 件")

    if problems:
        print(f"\n不整合 {len(problems)} 件:")
        for p in problems:
            print(f"  - {p}")
        return 1

    print("\nOK: フラグとビューアーのフィルタは同期しています。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
