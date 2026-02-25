# Tapo Robot `listend.py` システム設計 v0.4

- 更新日: 2026-02-24
- 対象: `python/listend.py`
- 目的: RTSP 常時リッスンとウェイク制御を、STT切替可能な構造で安定運用する

## 1. 実装方針（現行）

- ウェイク/ストップ判定は、発話セグメントの文字起こし結果で実施する。
- `OFF` で wake ワードを含むセグメントを検出したら `ON` に遷移する。
- wake を含むセグメントは前置きを捨てず全文採用する。
- `ON` では文字起こしをセッション蓄積し、無音で1ターン確定して dispatch する。
- STT バックエンドは `LISTEND_STT_BACKEND` で `faster-whisper` / `reazonspeech-k2` を切替する。

## 2. 構成

1. `Config`
- `YATAGARASU_CWD/.env` を読み込み設定を構築する。
- `LISTEND_DISPATCH_CMD` 未指定時は `<workspace親>/bin/yatagarasu` を自動採用する。

2. `AudioIngestor`
- `ffmpeg` で RTSP 音声を `s16le / 16kHz / mono` に変換して読む。
- `LISTEND_RTSP_TRANSPORT=auto` の場合は `tcp -> udp` の順で初期接続probeを行う。

3. `SegmentDetector`
- Silero VAD で有音判定する。
- セグメント境界はコード定数 `DEFAULT_SEGMENT_END_SILENCE_CHUNKS=5` で管理する。
- VAD の瞬断吸収に `DEFAULT_VAD_HANGOVER_CHUNKS=6` を使う。

4. `Transcriber`
- `faster-whisper` と `ReazonSpeech k2` を切替可能。
- 低音量ノイズの誤認識抑制に `DEFAULT_MIN_TRANSCRIBE_RMS_DBFS=-50.0` を適用する。
- ReazonSpeech は長尺入力を `DEFAULT_REAZON_MAX_SEGMENT_SEC=28.0` 単位に分割する。

5. `StateMachine`
- `OFF/ON` 遷移、無音タイマ、wake/stop 判定を管理する。

6. `Dispatcher`
- 確定テキストを `LISTEND_DISPATCH_CMD` に標準入力で渡す。

## 3. 状態機械

### 3.1 状態

- `OFF`: 待機（wake 判定のみ）
- `ON`: セッション中（蓄積 + dispatch）

### 3.2 イベント

- `E_WAKEWORD_DETECTED`
- `E_STOPWORD_DETECTED`
- `E_SESSION_END_SILENCE`（`LISTEND_SESSION_END_SILENCE_SEC`）
- `E_OFF_TIMEOUT_SILENCE`（`LISTEND_SILENCE_TIMEOUT_SEC`）

### 3.3 遷移

1. `OFF` + `E_WAKEWORD_DETECTED` -> `ON`
2. `ON` + `E_STOPWORD_DETECTED` -> `OFF`
3. `ON` + `E_SESSION_END_SILENCE` -> `ON`（dispatchのみ）
4. `ON` + `E_OFF_TIMEOUT_SILENCE` -> `OFF`

## 4. フィードバック音声（現行挙動）

- `OFF -> ON` 遷移時:
  - `LISTEND_WAKE_ACK_WORD` が設定されていれば `zunda --stdout | tapovoice` で再生する。
  - 再生失敗時は `wake_ack_pending=True` にし、次回 dispatch 前に再試行する。
- `ON` 中に再度 wake 検出:
  - 現在は確認音声を抑止している（連続中断回避の一時対応）。
- `ON -> OFF` 遷移時:
  - `LISTEND_STANDBY_WORD`（デフォルト `待機します。`）を再生する。

## 5. データフロー

1. RTSP音声取得
2. VADで発話セグメント抽出
3. 選択バックエンドで文字起こし
4. `OFF`:
- wake hit なら `ON` 遷移 + セグメント全文をセッション追加
- wake miss なら破棄
5. `ON`:
- stop hit なら stop語を除去して必要なら最終dispatchし `OFF`
- stop miss ならセッション追加
6. `ON` 無音でターン確定時に dispatch
7. `ON` 無音タイムアウトで `OFF`

## 6. 設定仕様（`workspace/.env`）

### 6.1 必須

- `LISTEND_RTSP_URL`
- `LISTEND_WAKE_WORDS`
- `LISTEND_STOP_WORDS`

### 6.2 主要任意設定

- STT:
  - `LISTEND_STT_BACKEND`（`faster-whisper` / `reazonspeech-k2`）
  - `LISTEND_STT_LANGUAGE`
  - `LISTEND_WHISPER_*`
  - `LISTEND_REAZON_*`
- 音声/VAD:
  - `LISTEND_RTSP_TRANSPORT`
  - `LISTEND_VAD_THRESHOLD`
  - `LISTEND_MIN_SEGMENT_SEC`
  - `LISTEND_OFF_TRANSCRIBE_COOLDOWN_SEC`
  - `LISTEND_CHUNK_MS`
- タイマ:
  - `LISTEND_SESSION_END_SILENCE_SEC`
  - `LISTEND_SILENCE_TIMEOUT_SEC`
  - `LISTEND_NO_DATA_TIMEOUT_SEC`
  - `LISTEND_HEARTBEAT_SEC`
  - `LISTEND_RECONNECT_DELAY_SEC`
  - `LISTEND_MAX_RECONNECT_ATTEMPTS`
- dispatch:
  - `LISTEND_DISPATCH_CMD`
  - `LISTEND_DISPATCH_TIMEOUT_SEC`
- 音声フィードバック:
  - `LISTEND_WAKE_ACK_WORD`
  - `LISTEND_STANDBY_WORD`
  - `LISTEND_WAKE_ACK_SPEAKER_ID`
  - `LISTEND_WAKE_ACK_TIMEOUT_SEC`
  - `LISTEND_WAKE_ACK_ZUNDA_CMD`
  - `LISTEND_WAKE_ACK_TAPOVOICE_CMD`
- ログ:
  - `LISTEND_LOG_LEVEL`

### 6.3 `.env` で管理しない値（コード定数）

- `DEFAULT_AUDIO_FILTER="highpass=f=120,lowpass=f=5000"`
- `DEFAULT_SEGMENT_END_SILENCE_CHUNKS=5`
- `DEFAULT_VAD_HANGOVER_CHUNKS=6`
- `DEFAULT_MIN_TRANSCRIBE_RMS_DBFS=-50.0`
- `DEFAULT_REAZON_MAX_SEGMENT_SEC=28.0`

補足:
- `LISTEND_SEGMENT_END_SILENCE_CHUNKS` を `.env` に書いても無視される（警告ログを出す）。

### 6.4 デフォルト値の扱い

- コード上のフォールバック値と `workspace/.env.example` は一致しない場合がある。
- 実運用時は `workspace/.env` の値が優先される。
- 例:
  - `LISTEND_SILENCE_TIMEOUT_SEC`: コード既定 `30`、`.env.example` は `10`
  - `LISTEND_DISPATCH_TIMEOUT_SEC`: コード既定 `20`、`.env.example` は `180`

## 7. 英語認識への切替

- ReazonSpeech で日英混在:
  - `LISTEND_STT_BACKEND="reazonspeech-k2"`
  - `LISTEND_REAZON_LANGUAGE="ja-en"`
- faster-whisper で英語中心:
  - `LISTEND_STT_BACKEND="faster-whisper"`
  - `LISTEND_WHISPER_LANGUAGE="en"`（または `auto`）

## 8. 障害設計

1. `ffmpeg` 切断/無音タイムアウト
- 再接続し、上限超過時は終了（systemd再起動へ委譲）。

2. 文字起こし失敗
- 当該セグメントは破棄して継続する。

3. dispatch失敗
- エラーログのみ出して継続する。

## 9. テスト観点

1. `OFF` で wake hit すると `ON` へ遷移する
2. wake を含むセグメント全文が採用される
3. `ON` で無音ターン確定後に dispatch される
4. `ON` で stop hit すると `OFF` へ遷移する
5. `ON` で無音タイムアウトすると `OFF` へ遷移する
6. wake/stop 未設定時は起動エラーになる
7. `LISTEND_STT_BACKEND` 切替で対応バックエンドが初期化される
