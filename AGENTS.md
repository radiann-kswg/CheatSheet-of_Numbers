# AGENTS.md — CheatSheet of Numbers (0-1188)

> **このファイルが AI エージェント向け指示の SSOT（Single Source of Truth）です。**
> Codex（Desktop / IDE / CLI / Cloud）・GitHub Copilot（coding agent / VS Code / CLI）・Claude（Claude Code / Cowork / Desktop）・その他の AI ツールは、本ファイルの指示に従ってください。
> `.github/copilot-instructions.md` と `CLAUDE.md` は本ファイルへのポインタであり、内容の重複記載はしません。指示の追加・変更は **必ず本ファイルのみ** を編集してください。

## 前提条件（必読）

- 回答は必ず日本語でしてください。
- 変更量が 500 行を超える可能性が高い場合は、事前に「この指示では変更量が 500 行を超える可能性がありますが、実行しますか?」と確認してください。
- 大きい変更（多数ファイル生成、構成変更、ルール追加など）を加える場合、まず計画を提示し「このような計画で進めようと思います。」と提案してください。
- 大きい変更（複数ファイルにまたがる編集、目次の大幅更新、運用ルールの追加など）を行った場合は、公開可能な範囲で `_wip/` に進捗レポートを残してください。
  - 推奨ファイル名: `YYYY-MM-DD_progress.md`
  - 最低限入れる内容: 目的 / 変更点の要約 / 影響範囲（編集したファイル）/ 未完了タスク / 参考リンク
- 不確かな点がある場合は、既存ファイル（特に `index.md` と `numbers/`）を探索し、ユーザーに「こういう理解で合っていますか？」と確認してください。

## リポジトリ概要

0〜1188 の数字について、次をまとめたチートシート集です。

- 数学的な性質（素因数分解・約数・トーシェント関数・表記など）
- 科学・文化に関する一次情報への導線（主に Wikipedia 等へのリンク）

### 技術スタック

- 形式: Markdown（静的ドキュメント）
- ビルド: なし（ページ生成のための補助スクリプトを同梱）
- 依存: Python 標準ライブラリのみ（追加の `pip install` 不要）

## ディレクトリ構成と役割

```
./
├── AGENTS.md                # AI 向け指示の SSOT（このファイル）
├── CLAUDE.md                # Claude 用ポインタ（編集しない）
├── .github/
│   └── copilot-instructions.md  # Copilot 用ポインタ（編集しない）
├── index.md                 # 入口（0〜1188 目次）
├── index.html               # Numbers Lore Viewer（GitHub Pages の閲覧 UI）
├── assets/                  # ビューアーの JS/CSS と検索インデックス（numbers-index.json は生成物）
├── README.md                # リポジトリ概要
├── numbers/                 # 各数字の個別ページ（基本は 1 数字 = 1 ファイル）
│   ├── 0xx/                 # 000〜099
│   ├── 1xx/                 # 100〜199
│   ├── ...                  # 2xx/〜9xx/（200〜999）
│   └── 1xxx/                # 1000〜1188
├── _template/               # 執筆テンプレート（number.md）
├── tools/                   # 生成・補助スクリプト
│   ├── generate_numbers.py  # メイン生成スクリプト
│   ├── number_range.py      # 収録上限と各数字のフォルダ名
│   ├── build_viewer_index.py    # ビューアー検索インデックス生成（フィルタ定義もここ）
│   ├── check_internal_links.py  # 内部リンク検査
│   ├── check_viewer_filters.py  # ページのフラグとビューアーのフィルタの同期検査
│   ├── wikipedia_ja.py      # Wikipedia（日本語）連携
│   ├── wikidata_cc0.py      # Wikidata（CC0）連携
│   ├── wikipedia_ja_pins_v1.json                 # 引用ピン留め設定
│   ├── wikipedia_ja_importance_overrides_v1.json # 重要度閾値の上書き設定
│   ├── wolfram_enrichment_v1.json                # Wolfram Knowledgebase 由来の科学データ（元素/小惑星/NGC）
│   ├── science_notes_v1.json                     # 核種・波長・メシエ番号などの説明と出典
│   ├── number_math_notes_v1.json                 # 定数の近似・幾何・暦など、個別の数についての数学ノート
│   ├── number_lore_v1.json                       # 数秘・占術・名数など『文化的ないわれ』のキュレーションデータ
│   ├── oeis_comments_ja_v1.json                  # OEIS %C コメントの和訳（CC BY-SA 4.0、oeisdata ミラー由来）
│   └── _cache/              # 取得キャッシュ（通常 Git 管理しない）
├── _wip/                    # 作業途中メモ（公開してよい内容のみ）
├── .private/                # 非公開メモ（コミット対象外の下書き等）
└── LICENSE                  # CC BY-SA 4.0
```

## 執筆ルール（重要）

### 1ファイル=1数字

- 0〜999 は百ごとのフォルダに置き、ファイル名を3桁にゼロ埋めする（例: `numbers/0xx/031.md`、`numbers/4xx/496.md`）。
- 1000〜1188 は `numbers/1xxx/` にまとめ、4桁のファイル名を使う（例: `numbers/1xxx/1188.md`）。

### 生成物の扱い

- `numbers/` 配下と `index.md` / `README.md` は、原則として `tools/generate_numbers.py` で生成します。
- 内容やフォーマットを変更する場合は、個別ファイルの手編集ではなく、**まず生成スクリプト側の更新を優先**してください（整合性維持のため）。
  - `README.md` の文面は `tools/generate_numbers.py` の `render_readme()` から生成されます。

### 数式（KaTeX）記法

VS Code 上で **KaTeX** 記法（拡張機能 `jeff-tian.markdown-katex`、`.vscode/extensions.json` で推奨済み）を用います。

- インライン数式: `$...$` / 別行立て: `$$...$$`（`\(...\)` や `\[...\]` は使わない）
- `numbers/` 配下の表記ゆれを避けるため、数式化が必要な表現は **生成スクリプト側で整形**する
- Wikipedia 由来の短い引用は基本は原文のまま扱う。
  - **数式表記を KaTeX に整形して掲載する場合**は「整形版（改変あり）」として扱い、引用行に `整形`（例: 「短い引用・整形」）と改変がある旨を明記する。
  - 原文と整形版の併記は原則不要（可読性を優先）。
- **整形時の注意（既知の不具合防止）**: HTML 実体参照（`&times;` `&minus;` など）は KaTeX 記号（`\times` `-`）へ**必ずデコードしてから**整形すること。数式と後続の説明文が連結されて誤った等式（例: `$715 = 714$`）にならないよう、式と文の境界を保持すること。

### 内容の方針（公開に耐えるための注意）

- Wikipedia / 解説サイト等の本文を長文で転載しない（要約＋参照リンク中心）。
- 引用する場合は短くし、出典 URL を必ず添える。
- 断定が難しい「文化的ないわれ」は、一次情報へのリンクを付けた上で、言い切りを避ける。
- Wikipedia は CC BY-SA。本リポジトリ（CC BY-SA 4.0）と整合は取りやすいが、無制限の転載は避け「要約＋リンク」を基本とする。
- Wikidata の構造化データは CC0。規格・コード等の"事実データ"は Wikidata 由来で自動拡充し、一次情報へリンクする。
- 数学的性質の記述（素因数分解・約数・トーシェント等）を追加・変更した場合は、可能なら計算機（Python / Wolfram 等)で検算する。
- 数列への所属（多角数・幸運数・ウラム数・各種特殊素数など）は **`generate_numbers.py` 内で自前計算**し、出典として OEIS の A 番号リンクを添える。外部サイトから所属データを取得・転載しない。
- 元素・小惑星・NGC 等の科学データの詳細（分類・原子量・発見年・星座など）は Wolfram Knowledgebase 由来（`tools/wolfram_enrichment_v1.json` に同梱）とし、出典を明記する。
- 個別の数学ノートは `tools/number_math_notes_v1.json` に、科学の補足は `tools/science_notes_v1.json` に説明と出典をまとめる。本文とビューアー検索は同じデータを使う。
- 数秘術・エンジェルナンバー・吉凶・語呂合わせ等の「文化的ないわれ」は『数秘・占術・文化のいわれ』セクションに集約する。科学的根拠のない伝承である旨を各ページで明記し、断定を避ける（『〜とされる』）。
  - 機械導出（数秘還元値・エンジェルナンバー・ヘブライ数字）は `generate_numbers.py`、キュレーション項目は `tools/number_lore_v1.json` を編集する（生成物の手編集をしない）。
  - **収録しないもの**: 性的・差別的・反社会的な含意を持つネットスラング、現役占術家の独自体系（数意学・数魂など。著作権・独自性への配慮）。
- 概要の「フラグ」は、そのページに収録されている『いわれ』の種類（数学/科学・技術/規格・コード/文化・いわれ）を全域から列挙する目次である。**各フラグの詳細な解説は対応セクション 1 箇所のみ**に置き、セクション間で解説を重複させない（数学フラグの定義＋根拠は『数学的性質』の「フラグの解説」に集約。Wikipedia『性質（要約）』には機械導出の分類・フラグを再掲しない）。
- GitHub Pages は **Jekyll を使わず静的配信**する（`.github/workflows/jekyll-gh-pages.yml` がリポジトリを `_site` へコピーし `.nojekyll` を置く）。閲覧 UI は `index.html`＋`assets/`（Numbers Lore Viewer）で、**生の `.md` を fetch して描画する**ため、Jekyll でビルドしてはならない（`.md` が `.html` に変換され動作しなくなる。過去には引用内の `{{` による Liquid 構文エラーでビルド失敗も発生）。
  - 数式は KaTeX auto-render で表示（`index.html` で読込、`assets/app.js` の `renderMathIn`）。
  - ビューアーの検索インデックス `assets/numbers-index.json` は `tools/build_viewer_index.py` で生成する（`generate_numbers.py` 実行時に自動同期）。手編集しない。
  - 生成物には Liquid 構文と誤認される `{{` / `{%` を含めない（`generate_numbers.py` が出力時に `{ {` / `{ %` へ無害化。将来 Jekyll 化する場合への備えとして維持）。

### 情報源とライセンス（採否の判断基準）

外部情報を取り込む前に、**利用規約が (1) CC BY-SA 4.0 での再配布 と (2) プログラムによる取得 を許すか**を必ず確認し、下表を更新してください。

| 情報源 | 用途 | ライセンス | 可否・運用 |
| --- | --- | --- | --- |
| Wikipedia（ja/en） | 概要・性質・文化 | CC BY-SA | **採用**。要約＋短い引用＋出典 URL |
| Wikidata | 規格・コード等の事実データ | CC0 | **採用**。自動拡充 |
| Wolfram Knowledgebase | 元素・小惑星・NGC | — | **採用**。`tools/wolfram_enrichment_v1.json` に同梱（オフライン） |
| [Mattia Verga / OpenNGC](https://github.com/mattiaverga/OpenNGC) | NGC とメシエ番号の対応 | CC BY-SA 4.0 | **採用**。公開 CSV から収録範囲を抽出し、帰属・ライセンス・抜粋した旨を掲載する |
| 原論文、大学・学会・公的機関の資料、国立国会図書館の書影 | 数学・科学・暦の事実、歴史的な記載の確認 | 資料ごと | **参照リンク**。検算した数値や確認した事実を自分の言葉で記述する |
| OEIS | 数列の A 番号・定義 | CC BY-SA 4.0 | **採用（リンクのみ）**。⚠️ 利用規約 §10 と robots.txt が自動アクセスを禁止。`oeis.org/search` をバッチで叩かないこと。データが要る場合は GitHub ミラー `oeis/oeisdata` を clone する |
| ja.Wiktionary / Wikibooks | 漢数字の字源など | CC BY-SA 4.0 | 未採用（採用可）。Wikipedia と同じ基盤で追加できる |
| 青空文庫（PD 本文）/ NDL（保護期間満了資料） | 文化的いわれの一次資料 | PD ほか | 未採用（採用可）。PD 部分は CC BY-SA を後付けせず、由来をファイル単位で明記する |
| OEIS の %C コメント（`oeis/oeisdata` clone 経由） | 数学的性質の補足（**和訳**） | CC BY-SA 4.0 | **採用**。和訳・要約を `tools/oeis_comments_ja_v1.json` に収録し、数列フラグの解説に帰属付きで追記。EULA §3 の帰属（OEIS の名称＋ A 番号 URL）と改変（翻訳）表示を必ず付ける |
| en/zh Wikipedia・en.wiktionary・en.wikiquote | 数字の文化・迷信・語源・引用（**和訳**） | CC BY-SA 4.0 | **採用**。和訳エントリを `tools/number_lore_v1.json` に収録（中国の数字文化＝kikkyo/goro、数詞の語源＝gogen カテゴリ）。text 末尾に出典と「和訳・改変あり」を明記 |
| Project Gutenberg / sacred-texts / Wikisource の PD 古典 | 数のいわれの一次資料（**和訳**） | PD（要ファイル単位確認） | **採用**。Westcott『Numbers: Their Occult Power and Mystic Virtues』(1911) 由来のエントリを `number_lore_v1.json` に収録済み。追加候補: Conant『The Number Concept』(1896)。PG 由来は本文から「Project Gutenberg」の商標表記を除去。sacred-texts は ⚠ 付きファイルと解説文（J.B. Hare 著作権）を除外 |
| ProofWiki | 定義・定理・個別数の例（**和訳**） | CC BY-SA 3.0（翻案は 4.0 で公開可） | 未採用（採用可）。個別数のページあり（例: Perfect Number/Examples/496）。数学的定義の出典として有力 |
| Cheiro『Cheiro’s Book of Numbers』 | 複合数10〜52の歴史的な解釈 | PD 原著 | **採用**。[1927年米国版の書誌・権利情報](https://catalog.hathitrust.org/api/volumes/full/htid/uiug.30112041800472.json)と[英国版第7刷](https://archive.org/details/in.ernet.dli.2015.70770)の第13章を照合。底本・頁・和訳の旨を記載し、番号の象徴と相互参照を短く要約する |
| Groupprops (subwiki) | 位数 n の群の個数・分類 | CC BY-SA 3.0 | 未採用（採用可）。「位数 n の群は◯種類」という各数字に対応する事実の出典に好適 |
| Metamath（set.mm） | 形式証明の参照 | CC0（peano.mm のみ GPL で不可） | 未採用（採用可）。帰属不要だが個別の数の性質はほぼ扱わない |
| MacTutor History of Mathematics | 数学史の記述（**和訳**） | CC BY-SA 4.0（本文のみ。/Extras/ と画像は対象外） | 未採用（採用可）。完全数の歴史など補助的に |
| Encyclopedia of Mathematics | — | wiki 追記分のみ CC BY-SA 3.0。**Kluwer/Springer 由来の原記事は権利留保** | **リンクのみ**。記事単位の履歴精査なしに翻案しない |
| nLab | — | 正式ライセンスなし | **リンクのみ**（再配布・翻案の明示許諾がない） |
| arXiv | 定理の一次出典 | 論文ごと（CC BY / CC BY-SA / CC0 のみ利用可） | 条件付き。abs ページのライセンスバッジで判定。デフォルトの non-exclusive license は不可 |
| Wolfram MathWorld | — | 全権利留保（FAQ で複製・ミラー禁止を明記） | **不可**。和訳（翻案）も不可。事実の自前記述＋外部リンクのみ |
| Number Gossip | — | ライセンス表示を確認できず | **不可扱い**（全権利留保とみなす） |
| number-pedia.com | — | 全権利留保 | **不可**。[利用規約](https://number-pedia.com/terms-of-service/)第五条がスクレイピングと無断複製を禁止。数列名の目録として人手で参照するのは可 |
| Numbers Aplenty | — | ライセンス表示なし | **不可**（全権利留保扱い）。検算用の人手参照のみ |
| Prime Curios! | — | GPLv3 + 投稿者権利留保 | **不可**（CC BY-SA 4.0 と非互換） |
| コトバンク等の辞典サイト | — | 引用条件のみ | **不可**（商用利用禁止条項があり CC BY-SA と非互換） |

#### 和訳（翻案）収録時の出典表記テンプレート

- **OEIS %C 由来**: 「本項は The Online Encyclopedia of Integer Sequences (OEIS) の A00xxxx (https://oeis.org/A00xxxx) のコメントを日本語に翻訳・編集したものです（CC BY-SA 4.0、翻訳・要約による改変あり）。」
- **Wikimedia 系由来**: 「本項は 〈プロジェクト名〉『〈ページ名〉』（パーマリンク URL、YYYY-MM-DD 取得）を日本語に翻訳・編集したものです（CC BY-SA 4.0、改変あり）。」
- **PD 古典由来**: 「本項の一部は 〈著者〉 "〈書名〉" (〈年〉, パブリックドメイン) を底本として翻訳・再構成したものです。底本: 〈URL〉」（PG 由来は本文・書名に「Project Gutenberg」を含めず、出典欄のリンク言及に留める）

## 生成ワークフロー

### 基本生成

```powershell
python tools/generate_numbers.py
```

- VS Code: `Terminal: Run Task` から生成タスクを実行可（選択中インタープリタを使用）
- venv（任意）: Windows `py -3 -m venv .venv`、macOS/Linux `python3 -m venv .venv`

### Wikidata（CC0）連携（自動拡充）

Wikidata Query Service / Action API から以下を自動追記（ネットワーク不可時はスキップ可）:

- 数そのものの Wikidata 項目（説明の要約＋リンク）
- ISO 3166-1 numeric（3桁の国・地域コード）
- 国番号（国際電話・E.164。数字のみの国番号に限定）

オプション: `--no-wikidata`（無効化）/ `--refresh-wikidata`（キャッシュ更新）

### Wikipedia（日本語）連携

- 冒頭（概要）取得で `Wikipedia（要点）` を補強。オプション: `--no-wikipedia` / `--refresh-wikipedia`
- `--wikipedia-sections` で『性質』『その他』から短い引用を抽出。
  - キャッシュ更新: `--refresh-wikipedia-sections` / オフライン生成: `--offline`
  - キャッシュ: `tools/_cache/wikipedia_ja_properties_v1.json` ほか
- 採用制御（ハードコード回避）:
  - 固有名詞のピン留め: `tools/wikipedia_ja_pins_v1.json`（本文内の部分一致）
  - 重要度閾値の上書き: `tools/wikipedia_ja_importance_overrides_v1.json`

### 追加・更新時の最低限手順

1. `tools/` や設定を更新したら、まずサンプル生成（`--only 6,57,496` など）で意図した変更を確認
2. 全数生成: `python tools/generate_numbers.py --wikipedia-sections`
   - ネットワークが使えない環境（Cowork のサンドボックス等）では `--offline` を付けてキャッシュのみで生成する。`--offline` 単体だと Wikipedia の『性質』『その他』が消えるので、**必ず `--wikipedia-sections` と併用**すること。
3. 内部リンク検査: `python tools/check_internal_links.py`（Missing links: 0 を確認）
4. ビューアー同期検査: `python tools/check_viewer_filters.py`（不整合 0 を確認）

### フラグを追加・改名したときの必須手順

数学フラグや『いわれ』カテゴリを増やすと、更新箇所が 3 ファイルに分かれる。**どれか 1 つでも漏れるとページとビューアーがずれる**ので、必ずまとめて更新すること。

| 追加するもの | 更新するファイル |
| --- | --- |
| 数列・数学フラグ | `tools/generate_numbers.py` の `_SEQUENCE_SPECS`（判定と定義文）＋ `tools/build_viewer_index.py` の `PROPERTY_FILTER_DEFS` と `FLAG_NAME_TO_KEY` |
| 科学の補足に使う検索フラグ | `tools/generate_numbers.py` の `SCIENCE_FILTER_LABELS` と `tools/science_notes_v1.json` の `category`。ビューアーは同じ定義を読む |
| いわれカテゴリ | `tools/generate_numbers.py` の `LORE_CATEGORY_ORDER` / `LORE_CATEGORY_JA` ＋ `tools/build_viewer_index.py` の `LORE_FILTER_DEFS` |
| OEIS コメント和訳 | `tools/oeis_comments_ja_v1.json`（キーは `_SEQUENCE_SPECS` の数列名と一致させる） |

最後に `python tools/check_viewer_filters.py` を実行して、不整合 0 を確認する。

### 新しい数列を追加するときの検算

数列の所属は**必ず OEIS の公表値と突き合わせて検算**すること（実装の思い込みで誤りが入りやすい）。過去に見つかった実例:

- 半素数判定で演算子の優先順位（`A or B and C`）を誤り、陳素数から 2・7・23 が欠落
- NSW 素数で「奇数番項のみ」の条件を落とし、3・17・577 が誤って混入
- 六芒星数と中心つき十二角数が同一数列（ともに A003154）で、フラグが二重に立った

検算用データは `oeis.org` を叩かず、GitHub ミラー `oeis/oeisdata` を sparse clone して `%S`/`%T`/`%U`（値）と `%N`（定義）を参照する。

### 公開（リリース）

- 全数生成 → リンク検査成功 → main へ反映
- タグ（例: `vYYYY.MM.DD`）を作成し、GitHub Release に変更点（要約）を記載

## アンチパターン

- 既存の命名規則と異なる場所に新規ファイルを作る（例: `31.md` を `numbers/` 直下に置く）。
- 外部資料の文章をコピペして長文転載する（要約し、参照リンクを付ける）。
- `index.md` と実ファイルのリンクが不整合のまま放置される。
- 生成物（`numbers/` 配下）を手編集して生成スクリプトとの整合性を壊す。
- 本ファイル以外（`copilot-instructions.md` / `CLAUDE.md`）に指示本文を書いて SSOT を崩す。

## ライセンス（CC BY-SA 公開のための注意）

- `LICENSE` は CC BY-SA 4.0。公開可能な内容のみを含めてください。
- 外部資料は「短い引用＋出典」または「要約＋リンク」を基本にし、転載は避けてください。
- Wikipedia 本文を取り込む場合は、CC BY-SA の要件（表示・継承・変更表示など）を満たす形で、出典 URL を明確に付けてください。
