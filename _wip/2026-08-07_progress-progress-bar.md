# 進捗レポート（2026-08-07）— Python処理の進捗バー

## 目的

0〜999のページ生成や検索索引作成など、時間のかかるPython処理について、完了割合と待ち時間の目安をターミナルで確認できるようにする。

## 変更点の要約

- Python標準ライブラリだけで動く共通の `ProgressBar` を追加。
- 対話端末では同一行を更新するバーとして表示し、件数、割合、経過時間、推定残り時間（ETA）、現在の処理対象を表示。
- CIやリダイレクトなどの非対話環境では、約10%ごとまたは15秒ごとの通常ログへ自動的に切り替える。
- 数字ページ生成、Wikipediaの番号別取得、ビューアー検索索引作成、Markdown内部リンク検査へ進捗表示を追加。
- `generate_numbers.py --only` では、指定された数字の件数を母数として進捗を計算する。

## 影響範囲（編集したファイル）

- `tools/progress.py`（新規）
- `tools/generate_numbers.py`
- `tools/wikipedia_ja.py`
- `tools/build_viewer_index.py`
- `tools/check_internal_links.py`
- `_wip/2026-08-07_progress-progress-bar.md`（本レポート）

## 検証

- `git diff --check`: エラーなし。
- Python 3.14.6で `.venv` を再構築し、`python -m compileall -q tools` が成功。
- `generate_numbers.py --offline --no-wikidata --no-wikipedia --only 6,57,496` が成功し、数字ページ3件とビューアー索引1000件の進捗・ETA表示を確認。
- `check_internal_links.py` が成功（Markdown 1015ファイル、相対リンク9780件、Missing links: 0）。

## 未完了タスク

- なし。

## 参考リンク

- なし（Python標準ライブラリのみを使用）
