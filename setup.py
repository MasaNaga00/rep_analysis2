"""
setup.py - cx_Freeze による Windows 実行ファイル(1フォルダ形式)のビルド設定

【ビルド方法】(Windows PC で実行)
    python setup.py build_exe

    → build/exe.win-amd64-3.xx/ 以下に
      RepairAnalysis.exe と依存ファイル一式が生成される。
      このフォルダごと配布すればOK(起動が速い1フォルダ形式)。

【前提】
    - ビルドする Windows PC に、このプロジェクトと同じ依存が pip 済みであること
      (pandas, pyodbc, aiohttp, pandastable, matplotlib, tenacity,
       python-dotenv, pyarrow, requests, nest_asyncio, cx_Freeze)
    - クロスコンパイル不可。必ず Windows 上でビルドすること。

【注意】
    - certs/ の中身(実際の dify_ca.pem)はこのリポジトリに含めない運用なら、
      ビルド後に手動で build フォルダの certs/ に配置するか、
      配布先で設定画面からパスを指定する。
    - .env は配布先で各自作成。.env.example を同梱している。
"""
import sys
import os
from pathlib import Path
from cx_Freeze import setup, Executable

# ----------------------------------------------------------------------
# バージョン
# ----------------------------------------------------------------------
APP_NAME = "RepairAnalysis"
APP_VERSION = "1.0.0"
APP_DESCRIPTION = "カメラ修理データ 類似事例検索ツール"

# ----------------------------------------------------------------------
# 同梱するパッケージ・モジュール
# ----------------------------------------------------------------------

# cx_Freeze が自動検出しきれない、または明示しておきたいパッケージ
packages = [
    # GUI
    "tkinter",
    # データ処理
    "pandas",
    "numpy",
    "pyarrow",          # Parquet 読み書き
    # 非同期 HTTP
    "aiohttp",
    "asyncio",
    # SQL
    "pyodbc",
    # テーブル表示
    "pandastable",
    "matplotlib",       # pandastable が内部で使う
    # リトライ・設定
    "tenacity",
    "dotenv",           # python-dotenv のインポート名は dotenv
    "requests",
    "ssl",
    "json",
    "encodings",        # 文字コード周り(日本語処理で重要)
]

# 任意。インストールされていれば同梱(無くてもビルドは通る)
optional_packages = ["nest_asyncio"]
for pkg in optional_packages:
    try:
        __import__(pkg)
        packages.append(pkg)
    except ImportError:
        print(f"⚠️  optional package '{pkg}' が見つかりません(スキップ)")

# トップレベルの自作モジュール(gui/ から import config 等で参照される)
# これらは「パッケージ」ではなく単体モジュールなので includes で明示する
includes = [
    "config",
    "db",
    "dify_client",
    "loader",
    "preprocess",
    "scoring",
    # GUI パッケージ配下(念のため明示。packages 指定でも可だが確実性重視)
    "gui",
    "gui.app",
    "gui.state",
    "gui.settings_store",
    "gui.workers",
    "gui.tabs",
    "gui.tabs.base",
    "gui.tabs.settings_tab",
    "gui.tabs.inquiry_tab",
    "gui.tabs.schema_edit_tab",
    "gui.tabs.data_load_tab",
    "gui.tabs.tagging_tab",
    "gui.tabs.ranking_tab",
    "gui.tabs.export_tab",
    "gui.widgets",
    "gui.widgets.dataframe_view",
    "gui.widgets.mapping_editor",
    "gui.widgets.schema_editor",
]

# ビルドサイズ削減のため除外(使っていない大物)
excludes = [
    "jupyter",
    "notebook",
    "IPython",
    "ipykernel",
    "pytest",
    "sphinx",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",
    "test",            # 自作テストではなく Python 標準の test パッケージ
    "tkinter.test",
]

# ----------------------------------------------------------------------
# 同梱ファイル(データファイル)
# ----------------------------------------------------------------------
# (ソースパス, ビルド先での相対パス) のタプル
include_files = []

# mappings/ ディレクトリ(カラムマッピングのプリセット)
if os.path.isdir("mappings"):
    include_files.append(("mappings", "mappings"))

# certs/ ディレクトリ(README は含める。実証明書は運用次第)
if os.path.isdir("certs"):
    include_files.append(("certs", "certs"))

# .env.example(配布先で .env にコピーして使う)
if os.path.isfile(".env.example"):
    include_files.append((".env.example", ".env.example"))

# README
if os.path.isfile("README.md"):
    include_files.append(("README.md", "README.md"))

# ----------------------------------------------------------------------
# build_exe オプション
# ----------------------------------------------------------------------
build_exe_options = {
    "packages": packages,
    "includes": includes,
    "excludes": excludes,
    "include_files": include_files,
    # zip にまとめないモジュール(動的 import されるものは展開しておくと安全)
    "zip_include_packages": ["*"],
    "zip_exclude_packages": [
        "pandas", "numpy", "pyarrow", "matplotlib", "pandastable", "pyodbc",
    ],
    # 最適化レベル(0=なし。docstring を消したくないので 0 のまま)
    "optimize": 0,
    # ビルド先ディレクトリ
    "build_exe": f"build/{APP_NAME}",
}

# ----------------------------------------------------------------------
# 実行ファイル定義
# ----------------------------------------------------------------------
# Windows で GUI アプリとしてコンソール窓を出さない: base="Win32GUI"
base = None
if sys.platform == "win32":
    base = "Win32GUI"

# アイコン(あれば設定。無ければ None)
icon_path = "app_icon.ico" if os.path.isfile("app_icon.ico") else None

executables = [
    Executable(
        # エントリスクリプト。gui/__main__.py を直接指すのではなく、
        # ラッパースクリプト run_app.py を使う(後述)
        script="run_app.py",
        base=base,
        target_name=f"{APP_NAME}.exe",
        icon=icon_path,
        shortcut_name=APP_NAME,
        shortcut_dir="DesktopFolder",
    )
]

# ----------------------------------------------------------------------
setup(
    name=APP_NAME,
    version=APP_VERSION,
    description=APP_DESCRIPTION,
    options={"build_exe": build_exe_options},
    executables=executables,
)
