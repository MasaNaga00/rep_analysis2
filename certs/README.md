# certs/

Dify API への HTTPS 接続に使用する CA 証明書ファイルを配置するディレクトリ。

## 必須ファイル

デフォルトのファイル名: **`dify_ca.pem`**

このディレクトリに `dify_ca.pem` を配置してください。
ファイル名を変える場合は、以下のいずれかで設定を変更してください:

- `.env` に `DIFY_CA_CERT_PATH=certs/your_cert.pem` を追記
- GUI 設定タブで「CA 証明書パス」を変更
- `config.py` の `DIFY_CA_CERT_PATH` を直接編集

## ファイル形式

PEM 形式（テキスト）の証明書ファイル。拡張子は `.pem` `.crt` `.cer` のいずれでも構いません。
ファイル内容は以下のような形式である必要があります:

```
-----BEGIN CERTIFICATE-----
MIIDxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
...
-----END CERTIFICATE-----
```

複数の CA を束ねたバンドル形式も可（社内中間 CA + ルート CA など）。

## セキュリティに関する注意

- 証明書ファイルはバージョン管理に含めないでください（`.gitignore` 推奨）
- cx_Freeze での配布時は `setup.py` の `include_files` に `certs/` を含めることで一緒にバンドルできます

## トラブルシューティング

**`DifyCertificateError: CA証明書ファイルが見つかりません`**
- `certs/dify_ca.pem` が存在するか確認
- 設定パスが正しいか確認（GUI 設定タブまたは `.env`）

**`SSL: CERTIFICATE_VERIFY_FAILED`**
- 証明書ファイルの内容が壊れていないか確認
- Dify サーバーの証明書が、この CA で署名されているか確認
- 証明書チェーン全体（中間 CA 含む）が必要な場合があります
