---
name: memorize
description: Memorize/Store information to long-term memory. TRIGGER WORDS: "覚えて", "記憶して", "メモして", "memorize", "save this", "覚えてね", "覚えておいて". Use when user explicitly wants to save/store information.
---

# Memorize - 記憶保存スキル

SemanticMemory APIを使って情報を長期記憶として保存します。

## Quick Start

```bash
# 基本的な使い方
memorize "ユーザーは猫を飼っている"

# サブテキスト付き（追加情報）
memorize "WiFiパスワードはhogehoge" --sub "自宅のWiFi"

# 要約なし（そのまま保存）
memorize "単純なメモ" --no-summarize
```

## 使用例

```bash
# ユーザー設定を記憶
memorize "ユーザーの名前はたねちゃん"

# 会話中の重要事項を記憶
memorize "ユーザーはRustが好き"

# 複雑な情報を記憶（要約付き）
memorize "プロジェクトの設定ファイルは ~/dev/AI/yatagarasu/.env にある" --sub "環境設定"
```

## オプション

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--sub TEXT` | サブテキスト（追加情報） | なし |
| `--no-summarize` | 要約をスキップ | 要約あり |

## 環境変数

`.env` で設定：

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `SEMANTIC_MEMORY_API_URL` | SemanticMemory APIのURL | http://localhost:6001/api |