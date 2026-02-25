---
name: recall
description: Retrieve past memories from SemanticMemory API via semantic search. Use when user says "思い出して", "覚えてる？", "何か記憶ある？", "recall", "remember", or wants to reference past conversations or information.
---

# Recall - 記憶検索スキル

SemanticMemory APIから過去の記憶を検索・想起します。

## Quick Start

```bash
# 基本的な使い方
recall "猫について"

# 取得件数を指定
recall "WiFi" --limit 5

# 類似度閾値を調整
recall "プロジェクト" --threshold 0.6
```

## 使用例

```bash
# ユーザー情報を思い出す
recall "たねちゃん"

# 過去の設定を思い出す
recall "環境設定"

# 複数の記憶を取得
recall "Rust" --limit 10 --threshold 0.5
```

## オプション

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--limit N` | 取得する記憶の最大件数 | 3 |
| `--threshold N` | 類似度閾値（0.0〜1.0） | 0.7 |

## レスポンス形式

```json
{
  "status": "success",
  "count": 2,
  "memories": [
    {
      "id": 64,
      "main_text": "ユーザーは猫を飼っている",
      "sub_text": "ペット情報",
      "summary_text": "ユーザーの猫関連情報",
      "similarity_score": 0.85
    }
  ]
}
```

## 環境変数

`.env` で設定：

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `SEMANTIC_MEMORY_API_URL` | SemanticMemory APIのURL | http://localhost:6001/api |
| `SEMANTIC_MEMORY_RECALL_DEFAULT_LIMIT` | デフォルト取得件数 | 3 |
| `SEMANTIC_MEMORY_RECALL_THRESHOLD` | デフォルト類似度閾値 | 0.7 |
