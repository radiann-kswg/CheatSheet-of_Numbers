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
- Python構文検査、サンプル生成、内部リンク検査を実行しようとしたが、環境の `.venv` が削除済みのPython 3.14実体を参照しており、また `python` / `py` がPATHに存在しないため未実行。

## 未完了タスク

- Python実行環境を復旧後、次を実行する。

  ```powershell
  python -m py_compile tools/progress.py tools/generate_numbers.py tools/wikipedia_ja.py tools/build_viewer_index.py tools/check_internal_links.py
  python tools/generate_numbers.py --offline --no-wikidata --no-wikipedia --only 6,57,496
  python tools/check_internal_links.py
  ```

## 参考リンク

- なし（Python標準ライブラリのみを使用）
