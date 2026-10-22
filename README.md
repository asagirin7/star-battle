# Star Battle ✦

スマホで遊べる、日本語の Star Battle。各行・各列・各色のエリアに星を1つずつ置き、星同士は斜めを含めて隣接させないロジックパズルです。

- 6×6 / 7×7 / 8×8、各12問、計36問。全問、エリアの連結性と解の一意性を検証済み。
- 初回クリアで100 / 180 / 280ポイント。クリア記録をDBに保存し、累計ポイントでランキング。
- サーバーで正解判定と加点。同一プレイヤー・同一問題への再送や複数タブでも二重加点しません。
- 名前登録、名前変更、個人履歴、途中の盤面保存、戻す・リセット、キーボード操作に対応。
- FastAPI + SQLAlchemy + Alembic + PostgreSQL。フロントエンドはHTML/CSS/JavaScriptで、ビルド不要。

## Kamui にデプロイ

[Kamui Python 構成](https://docs.kamui-platform.com/ja/gui/apps/python.html)に従い、リポジトリルートを実行ディレクトリにしてください。資料には `python/main.py` の例もありますが、ルートディレクトリで `python main.py` を実行する設定のため、本リポジトリはルートに配置しています。

| 設定 | 値 |
|---|---|
| 実行ディレクトリ | リポジトリルート |
| セットアップコマンド | `pip install -r requirements.lock` |
| 起動前コマンド | `alembic upgrade head` |
| アプリ起動コマンド | `python main.py` |
| Python | 3.12以上 |
| ヘルスチェック | `/health` |

1. 公開リポジトリを接続し、Python アプリを作成。
2. PostgreSQL データベースを作成し、アプリで選択。
3. 上記コマンドを指定。HTTPSでは環境変数 `COOKIE_SECURE=true` を追加。
4. デプロイ後、アプリURLからプレイヤー名を登録して遊べます。

`PORT` に従って `0.0.0.0` で Uvicorn を起動します。DB 接続は `DATABASE_URL` を優先し、未指定時は `DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASSWORD` を使用します。どちらもない場合は開発用 SQLite に接続します。本番の記録は必ず PostgreSQL を利用してください。

`.env.example` は設定例です。アプリは `.env` を自動読込しないため、環境変数として設定してください。

## ローカル起動

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
alembic upgrade head
python main.py
```

http://localhost:8000 で開きます。SQLite は `star-battle.db` に保存します。

## プレイヤーとポイントの仕様

プレイヤーは推測困難なトークンを HttpOnly / SameSite=Strict Cookie に保存し、DBにはそのハッシュのみを記録します。名前は識別子ではないため同名も登録できます。パスワードやメールは不要です。**別端末への引継ぎ・Cookie削除後の復旧には対応していません。** ランキングには名前とポイント・クリア数が公開されます。

問題ごとの初回クリアのみ加点し、速度ボーナスはありません。履歴の時間は最初に問題を開始してから初回クリアまでの実時間で、閉じている間も含みます。再挑戦は練習として扱います。盤面の途中保存には localStorage を使用します。

難易度は盤面サイズによる区分です。ランキングは累計ポイント、クリア数、プレイヤーIDの順で並びます。カジュアルなゲームを想定しており、自動解答や複数アカウントの抑止は含みません。

## 検証

```sh
pip install -r requirements-dev.txt
pytest -q
alembic upgrade head
alembic check
playwright install chromium
# 別ターミナルでアプリを起動してから
python scripts/browser_smoke.py
```

APIテストは正解判定・他人のゲームへのアクセス拒否・二重加点防止・履歴・ランキング・CSRFを検証します。全36問の一意解・エリア連結性も検証します。ブラウザテストはスマホとデスクトップで、登録から星の配置・クリア・ランキング・リロード後の記録まで確認します。

問題の再生成: `python scripts/generate_puzzles.py`。既存の問題IDとクリア記録が関連するため、運用開始後は問題を上書きせず、新しいIDを追加してください。

## License

MIT
