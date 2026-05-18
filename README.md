# カメラ修理データ 類似事例検索システム

## ファイル構成

| ファイル | 役割 |
|---|---|
| `config.py` | 設定(APIキー・DB接続・バッチサイズ・CA証明書パス等) |
| `db.py` | MS SQL Serverからのデータ取得(`loader.py` から呼び出される) |
| `loader.py` | **SQL/CSV 共通データロードレイヤー(NEW)** |
| `mappings/` | **カラムマッピングプリセット(NEW)** |
| `certs/` | **Dify接続用のCA証明書配置先(NEW)** |
| `preprocess.py` | コメント整形・言語検出・バッチ分割 |
| `dify_client.py` | Dify API呼び出し(1回目同期・2回目非同期並列・CA証明書検証) |
| `scoring.py` | スコアリング・DataFrame化・保存 |
| `repair_analysis_notebook.ipynb` | 対話的実行用Notebook |

## セットアップ

```bash
pip install pandas aiohttp requests tenacity nest_asyncio python-dotenv pyarrow tqdm
# SQL Server を使う場合のみ:
pip install pyodbc
```

Macで SQL Server を使う場合は ODBC Driver も必要:
```bash
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew install msodbcsql18
```

`.env` ファイルを作成:
```
DIFY_API_KEY_SCHEMA=app-xxxxxxxxxxxx
DIFY_API_KEY_TAGGING=app-yyyyyyyyyyyy
# CA証明書パスを変えたい場合のみ(デフォルト: certs/dify_ca.pem)
# DIFY_CA_CERT_PATH=certs/my_cert.pem
# SQL を使う場合のみ
MSSQL_SERVER=your-server.database.windows.net
MSSQL_DATABASE=RepairDB
MSSQL_USER=your_user
MSSQL_PASSWORD=your_password
```

## CA証明書の配置(必須)

Dify への HTTPS 接続には CA 証明書ファイルが**必須**です。
`certs/dify_ca.pem` に配置してください。

```
プロジェクトルート/
├── certs/
│   └── dify_ca.pem   ← ここに配置(PEM 形式)
├── config.py
├── ...
```

詳細は `certs/README.md` を参照。

ファイル名を変更する場合は、以下のいずれかで設定:
- `.env` に `DIFY_CA_CERT_PATH=certs/your_cert.pem` を追記
- GUI 設定タブで「CA 証明書パス」を変更
- `config.py` の `DIFY_CA_CERT_PATH` を直接編集

証明書が見つからない場合は `DifyCertificateError` が発生し、
探索した場所を含むエラーメッセージが表示されます。

## データソースの切り替え (SQL or CSV)

`loader.py` 経由でどちらからでも読み込み可能。論理カラム名
(`repair_id`, `user_comment`, `repair_comment`, `internal_1`, `internal_2`)
に統一されたDataFrameが返るので、後段の処理は変更不要。

### CSV から読み込み

```python
import loader

# 利用可能なマッピング一覧
for m in loader.list_mappings():
    print(m['name'], m['display_name'])

# 国内フォーマットのCSVを読み込み
df = loader.load_from_csv(
    "data/repair_export.csv",
    mapping_name="sample_japan",
)
```

### SQL から読み込み

```python
sql = "SELECT repair_id, user_comment, ... FROM repair_records WHERE model = ?"
df = loader.load_from_sql(sql, params=("EOS R7",))
```

SQL の SELECT 句のカラム名が論理名と異なる場合は `mapping_name` を指定。

## マッピングプリセット

`mappings/` 配下に JSON で保存される。同梱されているサンプル:

- `sample_japan.json` - 国内拠点フォーマット用サンプル
- `sample_overseas.json` - 海外拠点フォーマット用サンプル

実際のCSVカラム名に合わせて編集して使用する。

### マッピング JSON の構造

```json
{
  "name": "表示名",
  "description": "説明",
  "columns": {
    "repair_id": "実カラム名_必須",
    "user_comment": "実カラム名",
    "repair_comment": "実カラム名",
    "internal_1": "実カラム名_または_null",
    "internal_2": "実カラム名_または_null"
  },
  "passthrough_columns": [
    "タグ付けには使わないがTableau出力に残したい列名"
  ]
}
```

- `columns` の値を `null` にすると、そのコメントカラムは存在しないものとして扱われ、空列で補完される
- `passthrough_columns` は機種・修理日など、解析には使わないが最終出力に保持したいカラム

### マッピングを新規作成

```python
import loader

# CSVのカラム名を確認
columns, preview = loader.preview_csv_columns("data/new_format.csv")
print(columns)

# マッピング定義
new_mapping = {
    "name": "新フォーマット",
    "description": "...",
    "columns": {
        "repair_id": "ID",
        "user_comment": "user_text",
        "repair_comment": "tech_text",
        "internal_1": None,  # このフォーマットには存在しない
        "internal_2": None,
    },
    "passthrough_columns": ["model", "date"],
}

loader.save_mapping(new_mapping, "new_format")
# → mappings/new_format.json として保存される
```

## 使い方(Notebookで対話的に)

Notebookを開いてセルを上から順に実行:

1. モジュール読み込み(`loader` 含む)
2. 問い合わせ文を書く
3. Dify 1回目でスキーマ生成 → 内容確認
4. **SQL または CSV でデータ取得**(マッピング自動適用)
5. 前処理 → 言語・コメント長分布を確認
6. Dify 2回目でタグ付け(進捗バー付き)
7. タグ分布を確認
8. 問い合わせタグ指定 → スコアリング・絞り込み
9. 上位結果の根拠を確認
10. Parquet/CSVに保存

## Difyワークフロー側

(変更なし。既存ドキュメント参照)

## パラメータチューニング

`config.py` の以下を調整:

| パラメータ | 推奨範囲 | 説明 |
|---|---|---|
| `BATCH_SIZE` | 10〜20 | 1バッチのレコード数 |
| `MAX_CONCURRENT` | 3〜10 | 並列数 |
| `MAX_RETRIES` | 3 | JSON破損・タイムアウト時の再試行 |
| `REQUEST_TIMEOUT` | 120 | バッチ内レコード数が多いなら長めに |

## トラブルシューティング

**`DifyCertificateError: CA証明書ファイルが見つかりません`**
- `certs/dify_ca.pem` が存在するか確認
- パスを変更している場合は `config.DIFY_CA_CERT_PATH` または GUI 設定を確認
- エラーメッセージに「探索した場所」が表示されるので、いずれかにファイルがあるか確認

**`SSL: CERTIFICATE_VERIFY_FAILED` で Dify 接続に失敗**
- 証明書ファイルの内容が壊れていないか確認(BEGIN/END CERTIFICATE で囲まれているか)
- Dify サーバーの証明書が、この CA で署名されているか確認
- 中間 CA が必要な場合は証明書チェーン全体をバンドルした PEM を使う

**CSV読み込み時に必須カラムが見つからない警告**
- マッピング JSON の `columns.repair_id` の値が実カラム名と一致しているか確認
- `loader.preview_csv_columns()` で実際のカラム名を確認

**CSV読み込み時に文字化け**
- UTF-8 でエクスポートされているか確認
- `loader.load_from_csv(..., encoding="utf-8-sig")` で BOM 付き UTF-8 も試す

**ODBC接続エラー**
- `pyodbc.drivers()` でインストール済みドライバ確認
- `MSSQL_DRIVER` の値を確認

**Dify 2回目のJSON破損が頻発**
- `BATCH_SIZE` を5〜8に下げる
- 2回目プロンプトで「JSON配列のみ出力」を強調

## Tableauでの可視化

出力された `*_ranked.csv` または `*_tagged.parquet` をデータソースとして使う。
passthrough_columns で指定した機種・修理日等もそのまま使える。
