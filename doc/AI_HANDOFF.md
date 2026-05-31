# AI開発引き継ぎドキュメント（カメラ修理データ 類似事例検索システム）

> **このファイルを最初に読むAIへ**
> あなたはこのプロジェクトの開発を引き継ぎます。背景情報を持っていない前提で書いています。
> まず本ファイル全体を読み、特に「2. 絶対に守る不変条件」と「3. やってはいけないこと」を
> 理解してからコードに触れてください。詳細な経緯は既存の `HANDOFF.md` にもありますが、
> **最新の状態と設計理由は本ファイルが優先**です（HANDOFF.md は一部古い記述を含みます）。

---

## 0. このプロジェクトは何か（30秒で把握）

カメラ・レンズ・CPプリンタ・アクセサリ等の**修理データから、入力した問い合わせに似た過去事例を検索する**Windowsデスクトップアプリ。

- 言語: Python / GUI: Tkinter（7タブ）/ 配布: cx_Freeze で exe 化
- AI基盤: **Dify**（社内ホストのLLMワークフロー）を**2回**呼ぶ
  1. スキーマ生成（同期 / requests）: 問い合わせ文 → 分類軸（タグスキーマ）を生成
  2. タグ付け（非同期並列 / aiohttp）: 各レコードをスキーマでタグ付け
- 出力: Excel（2シート）・Parquet・JSON。Tableau でも開く想定。
- 開発はMac、配布先はPython非搭載のWindows PC。

処理の流れ（GUIタブも左→右でこの順）:
```
問い合わせ入力 → スキーマ生成(Dify1) → スキーマ編集 → データ取得(CSV/SQL)
  → タグ付け(Dify2) → 絞り込み(スコアリング) → 出力(Excel/Parquet/JSON)
```

---

## 2. 絶対に守る不変条件（壊すと動かなくなる）

これらは**意図的にそうなっている**。「冗長」「古い」と感じても、理由を理解せずに変えないこと。

1. **scoring は core軸ちょうど1個を前提にしている。**
   `scoring.py` の `score_record` 系は `tier == "core"` の軸を1つ取り出す。
   core軸が0個だと `StopIteration`、複数だと最初の1個しか使われない。
   スキーマ生成プロンプト（Dify側）でも「core軸はちょうど1個」と制約している。

2. **`tier` は文字列 `"core"` / `"detail"` の2値のみ。** 他の値（"main"等）を入れない。

3. **`insufficient_info` 列は bool に正規化必須。**
   Dify は bool / 文字列 "true" / キー欠落（None）を混在で返すことがある。
   そのまま DataFrame に入れると列が object 型になり、**Parquet/Excel 書き込みが
   `Conversion failed for column insufficient_info with type object` で失敗する。**
   → `scoring.py` の `_to_bool` / `_to_float` / `_coerce_dtypes` で正規化している。
   **この防御コードを「不要」と判断して削除しないこと。** 実際に発生したバグの対策。

4. **数値列（`overall_relevance`, `conf__*`, `match_score`）も float 正規化必須。** 理由は上と同じ。

5. **candidates には「不明」または「該当なし」を必ず含める。**
   `score_record` の detail一致ボーナスが `rec_val not in ("不明","該当なし",None)` で
   除外判定している。これらが無いと情報が薄いレコードの扱いが壊れる。

6. **証明書は truststore を使う（後述）。`python-certifi-win32` に戻さないこと。**

7. **修理データは user_comment / repair_comment の「どちらか一方」あれば動く。**
   `repair_id` のみ必須。internal_1/2 は任意。これは仕様（必須化しない）。
   バリデーションは `mapping_editor.py` / `loader.py` で「コメント最低1つ」になっている。

8. **frozen(exe)で「書き込み先」に `Path(__file__).parent` を使わない。**
   cx_Freeze ではソースは `lib\library.zip` 内に入るため、`__file__` 基準のパスへ
   mkdir/書き込みすると `[WinError 183]` 等で失敗する。
   - 書き込み可能領域はユーザー領域（`%APPDATA%\repair-analysis\` / `~/.repair-analysis/`）を使う。
   - exe 隣の読み取り専用リソースが必要なら `sys.frozen` を見て `sys.executable` の親を使う
     （実装例: `loader._get_app_root()`, `dify_client._get_app_root()`）。
   詳細は §4-5, §9-5。

---

## 3. やってはいけないこと（AIが good intentions で改悪しがちな点）

- ❌ **証明書を `python-certifi-win32` で実装し直す。** 同パッケージは公式に非推奨・
  メンテ終了で、pip を壊す既知の不具合がある。truststore を使うこと（理由は §5）。
- ❌ **`_coerce_dtypes` や `_to_bool`/`_to_float` を「冗長」として削除する。** §2-3,4 参照。
- ❌ **Dify レスポンスの解凍ロジック（`_unwrap_*` / `_normalize_list_items`）を簡略化する。**
  Dify ワークフローの出力ノード設定次第で多様なラップ形式が来る。実バグ対策の防御。
- ❌ **core軸を複数許容する／tier に新しい値を足す。** scoring が前提を崩す（§2-1,2）。
- ❌ **settings.json をパスワード暗号化前提で書き換える。** 配布先PCのOSキーチェーン
  非対応を想定して平文（ユーザー判断）にしている。変えるなら要相談。
- ❌ **出力の Excel を単一シートに戻す／CSV を復活させる。** ユーザー要望で
  「1つのxlsxにtagged/rankedの2シート」に確定済み。CSV出力は廃止済み。
- ❌ **artifact 等でブラウザ localStorage を使う実装を足す。** このアプリはデスクトップ。

---

## 4. このセッション（直近）で行った変更履歴

引き継ぎ元のClaudeセッションで以下を実施済み。コードには反映済み。

### 4-1. 出力を Excel 2シート化、CSV廃止（`scoring.py`, `gui/tabs/export_tab.py`）
- `save_results` は `results.xlsx`（シート `tagged`=全件 / `ranked`=絞り込み）を出力。
- 旧 `ranked_csv` と個別xlsxは廃止。出力は results_xlsx / tagged_parquet /
  ranked_parquet / schema_json / meta_json の5つ。
- Excel出力に `openpyxl` が必要（requirements.txt / setup.py に追加済み）。

### 4-2. 型正規化（`scoring.py`）
- `_to_bool` / `_to_float` / `_coerce_dtypes` を追加。§2-3,4 のバグ対策。
- `flatten_tagging_results` の行生成時点でも正規化。保存直前にも `_coerce_dtypes`。

### 4-3. タグ付け件数の警告ポップアップ（`tagging_tab.py`, `config.py`, `settings_store.py`, `settings_tab.py`）
- 件数 > しきい値 のとき「N件をタグ付けします。トークンを多く消費します。続行?」を表示。
- しきい値はデフォルト**500**。`.env` の `TAGGING_WARN_THRESHOLD` で変更可。
- GUI設定タブの「タグ付け警告件数」でも変更可。
- 優先順位: GUIで明示変更 > .env > デフォルト500。
  （`settings_store.apply_to_config_module` は値が500のままなら config を上書きせず、
   .env を尊重する分岐になっている。ここはデリケートなので注意。）

### 4-4. 証明書のフォールバック（`dify_client.py`, `settings_tab.py`, requirements/setup）
- §5 参照。ファイル優先・無ければ Windows 証明書ストア（truststore）。

### 4-5. マッピング保存の frozen 対応（`loader.py`）
- 症状: exe 実行時、マッピング新規作成・保存で
  `[WinError 183] すでに存在するファイルを作成することはできません: ...\lib\library.zip`。
- 原因: `MAPPINGS_DIR = Path(__file__).parent / "mappings"` が、frozen 時に
  `loader.py` が `lib\library.zip` 内に入るため `...\lib\library.zip\mappings` を指し、
  そこへ `mkdir` すると実在ファイル library.zip 配下にディレクトリを作れず失敗。
- 修正: 保存先を2系統に分離。
  - `BUNDLED_MAPPINGS_DIR`（同梱・読み取り専用、frozen時は exe 隣）
  - `USER_MAPPINGS_DIR`（`%APPDATA%\repair-analysis\mappings`、読み書き）
  - 読み込みは両方から（同名はユーザー優先）、保存は常にユーザー領域へ。
  - `_get_app_root()` を loader.py にも追加（dify_client と同じ frozen 判定）。
- GUI 改修は不要（名前で save/load を呼ぶだけのため）。

### 4-6. ドキュメント
- `利用ガイド.md`（非エンジニア向け総合マニュアル）を新規作成。証明書の二段構えも反映済み。
  - 文中に `〔要確認〕` マーカーが複数残っている（配布形態・APIキー配布方法・Dify URL・
    データ種別・問い合わせ先 等）。**運用が固まったら埋める必要がある。**

---

## 5. 証明書（CA）まわりの設計 — 特に重要

### 現在の実装（二段構え）
`dify_client.py`:
- `resolve_ca_cert_path()` … 証明書ファイルを探し、**見つからなければ `None` を返す**
  （以前は例外だった。`None` 返却に変更済み。呼び出し側で分岐する設計）。
- ファイルあり → そのファイルで検証（従来動作）。
- ファイル無し → **`truststore` で Windows 証明書ストアを使う**。
  - aiohttp 経路: `_build_truststore_context()` が `truststore.SSLContext` を返す。
  - requests 経路: `truststore.inject_into_ssl()` してから `verify=True`。
- ファイルも truststore も無い → `DifyCertificateError` で安全に停止（検証を無効化しない）。

### なぜ truststore か（再議論しないため）
- `python-certifi-win32` は**公式に非推奨・メンテ終了**。pip を壊す既知バグあり。
  cx_Freeze（frozen）環境での runtime monkey-patch も不安定。
- `truststore` は標準 `ssl` に統合する現行主流の方式で、cx_Freeze と相性が良い。
- 後継候補 `pip-system-certs` は v5系で pip を壊した事例があり、バージョン固定が必要なため避けた。

### 注意
- `db.py` の SQL接続は `TrustServerCertificate=yes` で、CA証明書ファイルとは無関係。
  証明書フォールバックの対象は **Dify への HTTPS（dify_client.py）のみ**。
- 配布時は setup.py の packages に `truststore` が入っていること（frozen同梱必須）。

---

## 6. ファイル別の役割（編集時の地図）

### コアロジック（トップレベル）
| ファイル | 役割 | 触るとき注意 |
|---|---|---|
| `config.py` | 設定値・環境変数。`TAGGING_WARN_THRESHOLD` 等 | .env と settings.json の二系統がある |
| `dify_client.py` | Dify API（同期スキーマ生成＋非同期タグ付け）、証明書、レスポンス解凍 | §2,§3,§5 の塊。最も慎重に |
| `loader.py` | CSV/SQL 共通ロード、マッピング適用 | 必須は repair_id のみ |
| `preprocess.py` | コメント整形・言語検出・バッチ分割 | `.get()` で欠損に強い作り |
| `scoring.py` | フラット化・スコアリング・保存 | §2-3,4 の型正規化、Excel 2シート |
| `db.py` | SQL Server 接続 | 証明書とは無関係 |

### GUI（`gui/`）
- `app.py`（メイン、7タブ、セッション）/ `state.py` / `settings_store.py` / `workers.py`
- `tabs/`: settings, inquiry, schema_edit, data_load, tagging, ranking, export ＋ base
- `widgets/`: dataframe_view, mapping_editor, schema_editor

### 配布・データ・ドキュメント
- `setup.py`（cx_Freeze）/ `run_app.py`（エントリポイント）/ `requirements.txt`
- `mappings/*.json`（カラムマッピングのプリセット）
- `certs/`（`dify_ca.pem` を置く。無くても Windows ストアで動く）
- `README.md` / `HANDOFF.md`（旧）/ `利用ガイド.md`（利用者向け）/ 本ファイル

### テスト
- `test_schema_unwrap.py`（Difyレスポンス解凍）/ `test_phase3_integration.py`（タブ統合・save_results含む）
- `test_phase4_session.py` / `test_phase4_edge_cases.py`（セッション）
- 注: `aiohttp` 等の依存が無い環境では import 時点で落ちるテストがある（環境問題、コードバグではない）。

---

## 7. データ構造クイックリファレンス

### スキーマ
```python
{
  "query_summary": "問い合わせの要約",
  "axes": [
    {"name": "症状カテゴリ", "tier": "core",    # ちょうど1個
     "description": "...", "candidates": ["...", "不明"], "priority": "high"},
    {"name": "発生環境",   "tier": "detail",   # 0..max_detail_axes 個
     "description": "...", "candidates": ["...", "該当なし"], "priority": "medium"},
  ],
}
```

### batch_results（タグ付けの戻り値）
```python
[
  {"batch_idx":0, "success":True, "input_ids":[...], "results":[
     {"repair_id":"R001", "language_detected":"ja",
      "tags":{軸:値}, "confidence":{軸:0.0-1.0}, "evidence":{軸:"根拠"},
      "overall_relevance":0.0-1.0, "relevance_reason":"...",
      "insufficient_info":False, "insufficient_reason":""}, ...]},
  {"batch_idx":1, "success":False, "error":"...", "input_ids":[...]},
]
```
※ `insufficient_info` / 数値は Dify が型を崩して返すことがある → §2-3,4 で正規化。

### scoring.py 主要関数
- `flatten_tagging_results(batch_results, schema) -> DataFrame`
  （1行=1レコード。`tag__軸`, `conf__軸`, `evidence__軸` 列を生成。行生成時に型正規化）
- `rank_results(df, query_tags, schema, min_relevance, top_n) -> DataFrame`
- `save_results(tagged_df, ranked_df, schema, inquiry_text, tag) -> dict[str,Path]`
  （results.xlsx[tagged/ranked] ＋ parquet×2 ＋ json×2 を出力）

---

## 8. 動かし方・ビルド

```bash
# 開発起動（Mac/Win）
python run_app.py            # または python -m gui

# Windows exe ビルド
python setup.py build_exe    # → build/RepairAnalysis/ をフォルダごと配布

# 依存インストール
pip install -r requirements.txt
```

### 設定の二系統（混同しやすい）
- `.env`（config.py が読む）: `DIFY_CA_CERT_PATH`, `TAGGING_WARN_THRESHOLD` 等。
- `settings.json`（GUI設定タブが読み書き）:
  Windows `%APPDATA%\repair-analysis\settings.json` / Mac `~/.repair-analysis/settings.json`。
  起動時に読まれ config を上書きする。**平文保存。**
  → 「.env を消したのに値が入っている」のはこの settings.json が原因（バグではない）。

---

## 9. 既知の落とし穴

1. **Dify レスポンスの形式揺れ**: 出力ノード設定で変わる。`_unwrap_*` で吸収。
   新形式が来たら `dify_client.py` のそれらを確認。タグ付けタブはフラット化失敗時に構造をログ出力する。
2. **pandas/numpy バージョン差**: 開発環境と本番でバージョンが違う。requirements は下限のみ。
3. **ODBC Driver**: SQL利用時、配布先PCに「ODBC Driver 18 for SQL Server」が別途必要（exe同梱不可）。
4. **しきい値の優先順位ロジック**（§4-3）: settings.json が500のままなら .env を尊重する分岐。
   ここを単純な「常に上書き」に変えると「.envで変更可」の仕様が壊れる。
5. **frozen(exe)時の `Path(__file__)` と library.zip**: cx_Freeze ではソースが
   `lib\library.zip` 内に入る。`__file__` 基準のパスへ書き込む/mkdir すると
   `[WinError 183]`（library.zip は実在ファイルでその中に dir を作れない）で失敗する。
   - 実例: マッピング保存が `...\lib\library.zip\mappings` を mkdir しようとして失敗（§4-5で修正済み）。
   - 書き込みはユーザー領域（`%APPDATA%\repair-analysis\`）へ。読み取り専用リソースは
     `sys.frozen`→`sys.executable` の親で解決（`_get_app_root()`）。
   - 新たに「ファイルを保存する」機能を足すときは、保存先が `__file__` 基準になっていないか必ず確認すること。

---

## 10. 未完了・次の候補

- `利用ガイド.md` の `〔要確認〕`（配布形態・APIキー配布方法・Dify URL・データ種別・
  ODBC導入状況・Windows警告時の対処・問い合わせ先）を運用確定後に埋める。
- 旧 `HANDOFF.md` の記述更新（出力がCSV前提のまま等、古い箇所あり）。本ファイルが優先。
- Dify ワークフロー側（プロンプト/出力ノード）の安定化は継続テーマ。
  特に1回目の `max_detail_axes` が効くよう、開始ノードに Number 変数があり、
  かつ LLM プロンプトに埋め込まれているかが要確認ポイント。

---

## 11. ChatGPT/GPT-5 で作業を始めるときの最初の指示例

> このプロジェクト（カメラ修理データ類似事例検索）の開発を引き継ぎます。
> まず `AI_HANDOFF.md` を読んでください。特に「絶対に守る不変条件」と
> 「やってはいけないこと」を厳守してください。証明書は truststore のままにし、
> 型正規化やレスポンス解凍の防御コードは削除しないでください。
> 把握できたら、〇〇（依頼内容）を一緒に進めたいです。

---

*本ファイルは引き継ぎ元のセッション時点の最新状態を反映しています。*
*以後の変更を行ったら、§4 と §2/§3 を更新してください。*
