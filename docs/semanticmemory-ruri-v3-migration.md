# SemanticMemory Ruri v3 移行ガイド

## まず知っておくこと

Yatagarasuは、SemanticMemoryに保存した記憶を保護しながら、埋め込みモデルを
`cl-nagoya/ruri-small-v2`から`cl-nagoya/ruri-v3-70m`へ移行できるようになりました。

- 新規Docker環境は、最初からv3を使用します。
- 通常のアップデートだけでは、既存環境のモデルはv2のままです。
- v2をそのまま使い続けても問題ありません。
- v3を使う場合だけ、このガイドに従って一度移行します。
- 会話本文はSQLiteに保持され、そこからv3用の検索ベクトルを作り直します。
- 移行に失敗した場合は、従来のモデルと検索ベクトルが維持されます。

SBERT Skill Routerで使うRuri v3と、SemanticMemoryの埋め込みモデルは別々の設定です。
RouterがRuri v3でも、SemanticMemoryを急いで移行する必要はありません。

## 既存環境をv3へ移行する

以下の操作は、Yatagarasuのリポジトリ直下から開始します。

### 1. ソースとsubmoduleを更新する

```bash
git pull --ff-only
git submodule update --init --recursive
```

### 2. 音声サービスを一時停止する

移行中に新しい記憶が追加されないようにします。

```bash
systemctl --user stop yatagarasu.service
```

### 3. 記憶データをバックアップする

```bash
cd external/SemanticMemory
docker compose \
  -f docker-compose.yml \
  -f ../../deploy/semanticmemory.compose.override.yml \
  stop semanticmemory

backup_dir="$HOME/semanticmemory-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$backup_dir"
cp -a datas/semantic_memory.db datas/chroma "$backup_dir/"
echo "バックアップ先: $backup_dir"
```

表示されたバックアップ先は、動作確認が終わるまで削除しないでください。

### 4. CPU版SemanticMemoryを起動する

```bash
docker compose \
  -f docker-compose.yml \
  -f ../../deploy/semanticmemory.compose.override.yml \
  up -d --build semanticmemory
```

初回ビルドやモデル取得には時間がかかります。APIが起動するまで待ちます。

```bash
until curl -fsS http://127.0.0.1:6001/docs >/dev/null; do sleep 2; done
```

### 5. v3用の検索ベクトルを作る

```bash
curl -fsS -X POST \
  "http://127.0.0.1:6001/api/rebuild_vector?sbert_model=cl-nagoya/ruri-v3-70m" \
  | jq .
```

初回はRuri v3モデルを取得するため、しばらく応答が返らないことがあります。
途中でSemanticMemoryを停止しないでください。

成功時は、応答に次の内容が含まれます。

```text
"status": "rebuild completed"
"embedding_model": "cl-nagoya/ruri-v3-70m"
"embedding_dimension": 384
"integrity": {
  "ok": true
}
```

### 6. 整合性と設定を確認する

```bash
curl -fsS http://127.0.0.1:6001/api/check_integrity | jq .
curl -fsS http://127.0.0.1:6001/api/settings | jq .
```

次の状態なら移行成功です。

- `ok`が`true`
- `matched`、`total_db`、`total_chroma`が同じ件数
- `sbert_model`が`cl-nagoya/ruri-v3-70m`
- `collection_metadata.embedding_dimension`が`384`

### 7. 起動時の既定値もv3に合わせる

移行成功を確認してから、`external/SemanticMemory/.env`を編集します。

```bash
SBERT_MODEL=cl-nagoya/ruri-v3-70m
```

この設定は、将来データベースを新規作成または復旧するときの既定値です。
移行前にこの値だけを変更しないでください。

### 8. Yatagarasuを再開する

```bash
systemctl --user start yatagarasu.service
systemctl --user is-active yatagarasu.service
```

最後に、過去の会話を尋ねて記憶検索が動くことを確認します。

## 新規インストール

新規Docker環境はRuri v3が既定値です。`external/SemanticMemory/.env.example`から
`.env`を作成し、[セットアップマニュアル](setup-manual.md)どおりに起動してください。

```bash
cd external/SemanticMemory
cp .env.example .env
```

配布用設定には、あらかじめ次の値が設定されています。

```bash
SBERT_MODEL=cl-nagoya/ruri-v3-70m
```

保存済みベクトルがないため、移行APIの実行は不要です。

## 失敗した場合

移行APIは一時コレクションでv3用ベクトルを作り、SQLiteとの全件一致を確認してから
切り替えます。処理がエラーで終了した場合は、原則としてv2の設定とベクトルが
そのまま使われます。

1. `external/SemanticMemory/.env`をv3へ変更していないことを確認します。
2. SemanticMemoryが応答することを確認します。
3. `yatagarasu.service`を再開します。
4. 原因を確認してから、移行を再実行します。

```bash
docker compose \
  -f docker-compose.yml \
  -f ../../deploy/semanticmemory.compose.override.yml \
  logs --tail=200 semanticmemory
curl -fsS http://127.0.0.1:6001/api/check_integrity | jq .
systemctl --user start yatagarasu.service
```

## v2へ戻す

v3からv2へ戻す場合も、同じ安全な再構築APIを使います。

```bash
systemctl --user stop yatagarasu.service
curl -fsS -X POST \
  "http://127.0.0.1:6001/api/rebuild_vector?sbert_model=cl-nagoya/ruri-small-v2" \
  | jq .
curl -fsS http://127.0.0.1:6001/api/check_integrity | jq .
```

成功を確認したら、`external/SemanticMemory/.env`を次へ戻し、音声サービスを再開します。

```bash
SBERT_MODEL=cl-nagoya/ruri-small-v2
```

```bash
systemctl --user start yatagarasu.service
```

APIで復旧できない場合に限り、SemanticMemoryを停止してから、手順3で作成した
バックアップの`semantic_memory.db`と`chroma`を`external/SemanticMemory/datas/`へ
戻してください。
