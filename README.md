# CheatSheet of Numbers (0-1188)

0〜1188 の数字について、数学的な性質と、科学/文化に関する一次情報への導線をまとめたチートシート集です。

- 入口: [index.md](index.md)
- ブラウザ閲覧（GitHub Pages）: https://radiann-kswg.github.io/CheatSheet-of_Numbers/
- 個別ページ: 0〜999 は `numbers/0xx/`〜`numbers/9xx/`、1000〜1188 は [numbers/1xxx/](numbers/1xxx/) に収録しています。
- 一部の規格・コード情報は Wikidata（CC0）から自動取得して補強します
- Wikipedia（日本語）の冒頭（概要）に加え、『性質』『その他』から短い引用を抽出して要点の入口を補強します（長文転載はしません）
- 元素・小惑星・NGC 天体の詳細（分類・原子量・発見年・星座など）は Wolfram Knowledgebase 由来のデータ（`tools/wolfram_enrichment_v1.json`）で補強します
- 核種・レーザーの波長・メシエ番号などの補足は `tools/science_notes_v1.json` に出典とともに収録しています。メシエ番号は [Mattia Verga / OpenNGC](https://github.com/mattiaverga/OpenNGC) のデータから抜粋しています（CC BY-SA 4.0）。
- 数秘術・エンジェルナンバー・吉凶・語呂合わせなどの『文化的ないわれ』も収録します（機械導出＋`tools/number_lore_v1.json` のキュレーション。科学的根拠のない伝承である旨を明記）
- 多角数・幸運数・ブラジル数など **約 60 種の数列への所属** を自前計算で判定し、各数列の定義を確認できる OEIS の A 番号を示します。
- 定数の有理近似、回転の自由度、暦の周期など、個別の数に結び付く計算と出典を `tools/number_math_notes_v1.json` に収録しています。数学・科学・文化の補足はビューアーから本文中の語句で検索できます。
- Issue #6〜#8 の掲載内容は、ビューアーの検索欄に `#6`（717の回文）、`#7`（フィボナッチ数）、`#8`（IC型番）を入力して探せます。`#8 SRAM` のように続けて語句を入れると、該当するページに絞り込めます。
- [314のページ](numbers/3xx/314.md)では、円周率 π = 3.14159… の先頭3桁「314」と、有効数字4桁に丸めた「3.142」を見比べられます。ビューアーで「実数の数字列」と検索すると、同じ読み方で紹介している数を一覧できます。
- 数列の補足コメントは OEIS（CC BY-SA 4.0）の和訳を `tools/oeis_comments_ja_v1.json` に収録しています
- 中国語圏の数字文化・英語数詞の語源・パブリックドメイン古典などは、再利用可能なライセンスのものだけを和訳して収録します

## 方針（公開に耐えるための注意）

- 外部サイトの本文を長文転載しません（要約＋参照リンク中心）。
- 引用する場合は短くし、出典 URL を必ず添えます。
- 数式表記を KaTeX に整形して掲載する場合は、改変がある旨（例: 『短い引用・整形』）を明記します。
- 数秘・占術などのいわれは断定を避け（『〜とされる』）、科学的事実と区別して掲載します。性的・差別的・反社会的な含意のスラングや、現役占術家の独自体系（数意学・数魂など）は収録しません。
- 外部データを取り込むのは、利用規約が **CC BY-SA 4.0 での再配布** と **プログラムによる取得** の両方を許す場合に限ります（採否の一覧は [AGENTS.md](AGENTS.md) の『情報源とライセンス』を参照）。
- 和訳して収録する場合は翻案にあたるため、出典・ライセンス・『翻訳による改変あり』を必ず併記します。

## ライセンス

本リポジトリは **CC BY-SA 4.0** です。詳細は [LICENSE](LICENSE) を参照してください。

- Wikidata の構造化データは CC0（パブリックドメイン相当）です。取得したデータの出典は各ページの Wikidata リンクを参照してください。
- OEIS（The Online Encyclopedia of Integer Sequences, https://oeis.org/ ）は CC BY-SA 4.0 です。本リポジトリは数列の A 番号リンクと、コメントの和訳・要約を収録しています。
- パブリックドメインの古典（例: W. W. Westcott, "Numbers: Their Occult Power and Mystic Virtues", 1911）に由来する記述は、その旨を各項目に明記しています。

## 生成について

このリポジトリの `numbers/` 以下は、`tools/generate_numbers.py` で生成できます。

- 依存: Python 標準ライブラリのみ（追加の `pip install` は不要）

```powershell
python tools/generate_numbers.py
```

- VS Code を使う場合は、`Terminal: Run Task` から生成タスクを実行できます（Python 拡張が選択中のインタープリタを使用）。
- macOS/Linux で venv（任意）: `python3 -m venv .venv` → `.venv/bin/python tools/generate_numbers.py`
- Windows で venv（任意）: `py -3 -m venv .venv` → `.venv\Scripts\python tools\generate_numbers.py`

### 相対リンク（リポジトリ内）

各数字ページに `リポジトリ内リンク` を自動出力し、近傍（±1/±10/±100）に移動できる相対リンクを付与します。

### Wikipedia 引用（性質/その他）

Wikipedia の『性質』『その他』セクションから短い引用を抽出するには `--wikipedia-sections` を指定します。

```powershell
python tools/generate_numbers.py --wikipedia-sections
```

- セクション取得キャッシュを更新したい場合: `--refresh-wikipedia-sections`
- ネットワーク無しで引用を含めて生成する場合: `--offline --wikipedia-sections`（キャッシュのみ使用）
- 引用の取り込みと数式整形の回帰検査: `python -m unittest discover -s tools -p "test_wikipedia_*.py"`。全ページの引用は公開前にビューアーと同じ版の KaTeX でも検査します。

特定の固有名詞を含む引用を優先したい場合は pins 設定で部分一致ピン留めできます:
- pins: `tools/wikipedia_ja_pins_v1.json`
重要度の採用閾値を数字ごとに調整したい場合は上書き設定を使います:
- overrides: `tools/wikipedia_ja_importance_overrides_v1.json`
同じファイルの `issue_weights` で、Issue の話題に合う引用候補に加点できます。各ルールは対象の数字・節・語句のパターンを指定します。キャッシュのみで生成するときも、ピン留めに続いて該当する引用が上位に並びます。

Wikidata 連携の制御（任意）:

```powershell
python tools/generate_numbers.py --no-wikidata
python tools/generate_numbers.py --refresh-wikidata
```

Wikipedia（日本語）連携の制御（任意）:

```powershell
python tools/generate_numbers.py --no-wikipedia
python tools/generate_numbers.py --refresh-wikipedia
```

### 公開（リリース）

- 生成スクリプト/設定を更新 → `python tools/generate_numbers.py --wikipedia-sections` で全ページ再生成
- 内部リンクが壊れていないことを確認（例: `python tools/check_internal_links.py`）
- ビューアーのフィルタがページのフラグと同期しているか確認（`python tools/check_viewer_filters.py`）
- main に反映後、タグ（例: `vYYYY.MM.DD`）を作成して GitHub Release を作成（差分/変更点を記載）

## 参考リンク

- Wikipedia 数の記事（例）: https://ja.wikipedia.org/wiki/31
