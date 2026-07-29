# 変更履歴 (Changelog)

## Unreleased

### 改善 (Improvements)

- 標準ウェイクワードを、LiveKit WakeWordの専用ONNXモデルによる
  「ねぇ、ヤタガラス」検出へ変更
- OFF状態のSTT常時実行を廃止し、CPU向けONNX推論をVAD連動の可変間隔で実行
- ウェイク検出後に同梱した`VOICEVOX:青山龍星`の「はい」を再生してから命令受付へ遷移
- `LISTEND_WAKE_BACKEND="stt"`で従来の文字列ウェイクを互換backendとして維持
- `yatagarasu doctor`へONNX shape、SHA-256、CPU Provider、smoke inference、
  prompt音声の診断を追加
- 新規標準話者をVOICEVOX 青山龍星（`SPEAKER_ID="13"`）へ変更
- 発話中のウェイク推論を80ms間隔へ高速化
- 連続する80ms音声窓で重複するspeech embedding 15個を再利用し、
  新しい1個だけを計算することでONNX推論のCPU負荷と処理時間を削減
- VAD/RMS活動開始、candidate、ONNX推論、main loop受領、prompt process起動、
  tapovoice送信完了を同一trace IDで追跡するウェイク遅延ログを追加
- Tapoの実再生開始がgo2rtc送信完了より遅れる場合に「はい」を命令として拾わないよう、
  prompt guardの既定値を0.6秒から0.8秒へ延長
- 音声活動終了時に仮想無音を追加し、判定へ影響させず短縮可能時間を測る
  `LISTEND_WAKE_LOOKAHEAD_MODE="shadow"`を追加し、仮想スコアを実際の
  1秒後のスコアと直接照合
- 無音先読みを`active`運用へ移行し、VADで発話終了を確認した時点で
  発話開始から2秒窓までの不足サンプルを無音補完して即時判定
- 無音補完量を壁時計ではなく16kHz音声のサンプル数から算出し、
  RTSP bufferingや推論時間の揺れによる窓位置のずれを解消
- VAD起点の補完要求と結果を通常推論より優先して保持し、
  単一worker内で上書きされる競合を防止
- VAD起点は補完済み窓のscore、VADなしのscore起点は現在scoreと補完scoreの
  二重条件で判定し、実機5回中5回の先読み検出を確認
- 同梱ONNXモデルが「ねぇ、カメラくん」「ねぇ、山田くん」を通常判定で
  誤検出することを既知の制約として記録。閾値では正例と分離できず、
  応答速度を優先してSTT二段階確認は採用しない
- Silero VADがウェイク発話の開始を逃した場合も、軽量なRMS音量判定で
  active推論へ即時移行し、待機間隔由来の遅延を回避
- 通常判定を`0.65`、早期判定を`0.15`の3回連続に設定
- CPU低減候補の120ms推論、2秒待機、1秒保持は実機正例を取りこぼしたため不採用
- heartbeatへONNX推論回数とdrop件数を追加
- STT互換ウェイク語の日本語読点がCSV区切りとして分割される問題を修正
- RTSPが無音PCMを流し続ける場合のgo2rtc/listend再接続手順をセットアップガイドへ追加
- FFmpegのRTSP入力へ`nobuffer`と`low_delay`を適用し、カメラ音声の入力遅延を短縮
- 1ウェイク1命令へ変更し、dispatch完了後に`OFF`へ戻るよう修正
- LLM応答中にRTSP入力へ蓄積した自己音声を破棄し、応答を再び命令として扱う
  自己対話ループを防止
- `bin/yatagarasu` が Codex CLI / Claude Code / opencode を選択実行できるようになった
  - `YATAGARASU_ENGINE`
  - `YATAGARASU_CODEX_MODEL`
  - `YATAGARASU_CODEX_REASONING_EFFORT`
  - `YATAGARASU_CODEX_BYPASS_SANDBOX`
- Codex CLI向けの `workspace/AGENTS.md` と `workspace/.codex/skills/` を追加
- wake ack 音声はVOICEVOX APIで直接WAVを生成し、`tapovoice -i` で再生できるようになった
- カメラスキルの保存先とPython起動を、リポジトリ固有の絶対パスに依存しない形へ整理
- `workspace/.env` は運用固有設定としてGit管理しない方針をドキュメントに明記
- `bin/yatagarasu-doctor` を追加し、`bin/yatagarasu doctor` から実行環境を診断できるようになった
- `listend.py` にSBERT Skill Routerを追加し、`move-camera` / `view` / `recall` をLLM dispatch前に実行できるようになった
- `move-camera` は `ptz_worker` でTapo接続を常駐化し、連続移動時は `YATAGARASU_SBERT_MOVE_SETTLE_SEC` で待機時間を調整できるようになった
- `view` は `GO2RTC_FRAME_API_ENABLED=true` の場合にgo2rtc HTTP frame APIを優先し、画像取得を高速化した
- `LISTEND_WAKE_ACK_WORD` の再生タイミングをLLM dispatch直前へ移動し、移動だけで完結するRouter処理では発話しないようにした
- 画像翻訳Intentでは、翻訳だけを返すようLLM向けプロンプトを調整した
- SemanticMemoryのPyTorchをCPU専用wheelへ固定し、CUDA/NVIDIA依存を除去した
- SemanticMemoryのモデルキャッシュ保存先を永続volumeへ統一した
- SemanticMemoryの運用固有Compose設定を`deploy/semanticmemory.compose.override.yml`へ分離した
- 埋め込みモデル移行を一時Chromaコレクションで検証後に切り替える方式へ変更した
- Ruri v2とRuri v3の検索用接頭辞をモデル世代ごとに適用できるようにした
- 新規SemanticMemory環境の既定埋め込みモデルをRuri v3に変更した
- 既存環境を自動的にRuri v3へ切り替えず、v2を維持する互換方針を明記した
- `docs/semanticmemory-ruri-v3-migration.md`にバックアップ、移行確認、v2への復旧手順を追加した
- SBERT Routerの内部制御プロンプトではなく、元のユーザー発話をSemanticMemoryの
  自動リコール検索語と会話保存本文に使用するよう修正
- 「さっき」「直前」などのリコールは意味検索だけに委ねず、直近会話を優先
- SemanticMemoryの自動リコール・保存失敗をdispatch警告ログへ記録
- systemdが`.env`を読込済みの場合に`recall-context.sh`が`set -e`でAPI呼び出し前に
  終了し、自動リコールだけが動かなくなる不具合を修正

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
YATAGARASU_ENGINE="auto"           # auto / codex / claude / opencode
YATAGARASU_MODEL=""                # Codexでは空ならCodex CLI設定を使用
YATAGARASU_CODEX_MODEL=""          # Codex CLI専用モデル
YATAGARASU_CODEX_REASONING_EFFORT="" # Codex CLI推論強度
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
- AIエージェントCLIとの連携
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
