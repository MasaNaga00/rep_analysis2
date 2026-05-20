"""
run_app.py - アプリケーション起動エントリポイント

通常実行でもこれを使える:
    python run_app.py

cx_Freeze でビルドする際のエントリスクリプトでもある。

frozen(exe化)されている場合、カレントディレクトリが
どこになるか不定なので、exe のあるディレクトリに移動してから起動する。
これにより certs/dify_ca.pem や mappings/ などの相対パス解決が安定する。
"""
import os
import sys


def _fix_working_directory():
    """
    frozen 環境では、exe のあるディレクトリを作業ディレクトリにする。
    通常実行では何もしない(プロジェクトルートで実行される前提)。
    """
    if getattr(sys, "frozen", False):
        # cx_Freeze でビルドされた exe
        exe_dir = os.path.dirname(sys.executable)
        os.chdir(exe_dir)


def main():
    _fix_working_directory()
    
    # gui パッケージの起動関数を呼ぶ
    from gui.app import main as app_main
    app_main()


if __name__ == "__main__":
    main()
