# 変更履歴 (Changelog)

## V1.1.0 (2026-02-28)

### 新機能 (Features)

#### SemanticMemory統合
- **yatagarasuコマンド**にSemanticMemoryによる記憶機能を統合
  - 過去の会話文脈を参照して応答を生成
  - 関連知識をベクトル検索で自動取得
  - 会話は `[user]入力\n[agent]応答` 形式で自動保存

**追加スクリプト:**
- `bin/memorize.sh` - SemanticMemoryに記憶を保存
- `bin/recall-context.sh` - 過去の文脈と関連知識を取得（`/api/retrieve`使用）

**新しい設定項目 (.env):**
```bash
# Yatagarasu設定
YATAGARASU_MODEL="haiku"           # デフォルトのClaudeモデル
YATAGARASU_SPEAKER="68"            # デフォルトの話者ID
YATAGARASU_MEMORY_ENABLED="true"   # 記憶機能の有効/無効

# SemanticMemory設定
SEMANTIC_MEMORY_RECALL_LIMIT=3      # 関連知識取得件数
SEMANTIC_MEMORY_RECENT_LIMIT=3      # 過去の文脈取得件数
SEMANTIC_MEMORY_RECALL_THRESHOLD=0.7 # 類似度閾値
```

**yatagarasuコマンドのオプション追加:**
- `--no-memory` - 記憶機能を一時的に無効化

**プロンプト構造:**
```
以下は過去の会話の記憶と関連知識です。これらを参考にしつつ、現在のプロンプトに応答してください。

memory_context:
  recent_history: |
    - [user]今日の天気は？[agent]晴れです。
  related_knowledge: |
    - [0.85] WiFiパスワードはhogehogeです

---
現在のプロンプト: [ユーザーの入力]
```

### 改善 (Improvements)

#### listend.py (音声監視サービス)
- **ウェイクワード検出の統一**
  - faster-whisper と reazonspeech-k2 で同じ挙動に統一
  - Two-Passアプローチを廃止し、元のロジック（全文保持→ACK発話→ディスパッチ）に戻した
  - `LISTEND_WAKE_PROMPT_WORD` 設定は使用しなくなった（コードには残存）

- **ストップワード検出の改善**
  - ストップワード検出時はディスパッチせずにキャンセルしてOFFに戻る
  - ストップワード発言時のみ「ストップ」を発話（無音タイムアウト時は発話しない）
  - `LISTEND_STANDBY_WORD` が設定されている場合のみ発話

- **空セッションのキャンセル**
  - ウェイクワード検出後に無発話で無音が続いた場合、OFFに戻る
  - 空のセッションがLLMに渡されるのを防止

### 設定変更 (Configuration Changes)

#### .env.exampleの更新
- `LISTEND_WAKE_PROMPT_WORD` - 使用しなくなった（残存）
- `SEMANTIC_MEMORY_RECALL_DEFAULT_LIMIT` → `SEMANTIC_MEMORY_RECALL_LIMIT` に改名
- `SEMANTIC_MEMORY_RECENT_LIMIT` を追加

### 内部変更 (Internal Changes)

- `bin/yatagarasu` に `.env` ファイル読み込み機能を追加
  - `workspace/.env` を優先、なければプロジェクトルートの `.env` を使用
  - `YATAGARASU_CWD` 環境変数でworkspaceを明示指定可能

### 修正 (Bug Fixes)

- 「考えるね。」が2回発話される問題を修正
  - `_handle_on_silence()` から重複する `_play_wake_ack()` 呼び出しを削除

---

## V1.0.0 (2025-02-22)

### 初回リリース

#### 基本機能
- 音声認識によるウェイクワード検出
- Claude Codeとの連携
- ずんだもん音声合成
- Tapo TC70カメラ制御（PTZ）
- 視覚スキル（画像取得）
- SemanticMemoryスキル（記憶の検索・保存）

#### Skills
- `speak` - 音声合成
- `view` - カメラ画像取得
- `move-camera` - カメラPTZ制御
- `recall` - 記憶の検索
- `memorize` - 記憶の保存
- `tanechan-search` - たねちゃんねる検索
- `tanechan-fetch` - Webページ取得
