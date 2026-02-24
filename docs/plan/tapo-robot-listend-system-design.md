# Tapo Robot `listend.py` システム設計 v0.3

- 作成日: 2026-02-24
- 対象: `python/listend.py`
- 目的: STTバックエンド切替（faster-whisper / ReazonSpeech k2）で日本語ウェイク検出を安定運用する

## 1. 方針

- ウェイク/ストップ判定は文字起こし結果から行う。
- `OFF` でウェイクワードを含む発話セグメントを検出したら `ON` に遷移する。
- ウェイクワードを含むセグメントは、前置きを切り捨てず全文採用する。
- `ON` では発話を蓄積し、無音3秒（デフォルト）で1ターン確定して Yatagarasu へ渡す。
- `ON` の無音30秒（デフォルト）で `OFF` に戻す。

## 2. 構成要素

1. `ConfigLoader`
- `YATAGARASU_CWD/.env` を読み込み設定を構築する。

2. `AudioIngestor`
- `ffmpeg` で RTSP 音声を `s16le/16kHz/mono` に変換する。

3. `SegmentDetector`
- Silero VAD で有音/無音を判定し、発話セグメントを切り出す。

4. `Transcriber`
- `.env` の `LISTEND_STT_BACKEND` に応じて STT を切替する。
- `faster-whisper` バックエンド: `LISTEND_WHISPER_*` を使用。
- `ReazonSpeech k2` バックエンド: `LISTEND_REAZON_*` を使用。

5. `SessionAssembler`
- `ON` 状態の文字起こしを1ターン単位で連結する。

6. `Dispatcher`
- 確定テキストを `LISTEND_DISPATCH_CMD` へ標準入力で渡す。

## 3. 状態機械

## 3.1 状態

- `OFF`: 待機。文字起こし結果から wake 判定のみ行う。
- `ON`: セッション中。文字起こしを蓄積し dispatch する。

## 3.2 イベント

- `E_WAKEWORD_DETECTED`
- `E_STOPWORD_DETECTED`
- `E_SESSION_END_SILENCE`（デフォルト3秒）
- `E_OFF_TIMEOUT_SILENCE`（デフォルト30秒）

## 3.3 遷移

1. `OFF` + `E_WAKEWORD_DETECTED` -> `ON`
2. `ON` + `E_STOPWORD_DETECTED` -> `OFF`
3. `ON` + `E_SESSION_END_SILENCE` -> `ON`（dispatchのみ）
4. `ON` + `E_OFF_TIMEOUT_SILENCE` -> `OFF`

## 4. データフロー

1. RTSP から音声取得
2. VAD で発話セグメント抽出
3. セグメントを選択中の STT バックエンドで文字起こし
4. `OFF`:
- wake ワードあり -> `ON` へ遷移し、そのセグメント全文をセッションに追加
- wake ワードなし -> 破棄
5. `ON`:
- stop ワードあり -> 必要なら最終 dispatch 後に `OFF`
- stop ワードなし -> セッションに追加
6. `ON` で無音3秒 -> セッション確定して dispatch
7. `ON` で無音30秒 -> `OFF` へ戻る

## 5. `.env` 仕様（`workspace/.env`）

## 5.1 必須

- `LISTEND_RTSP_URL`
- `LISTEND_WAKE_WORDS`（例: `ヤタガラス`）
- `LISTEND_STOP_WORDS`（例: `ストップ`）

## 5.2 任意

- `LISTEND_STT_BACKEND=faster-whisper`（`faster-whisper` / `reazonspeech-k2`）
- `LISTEND_STT_LANGUAGE=ja`（共通デフォルト）

- `LISTEND_WHISPER_MODEL=base`
- `LISTEND_WHISPER_COMPUTE_TYPE=int8`
- `LISTEND_WHISPER_LANGUAGE=ja`
- `LISTEND_WHISPER_BEAM_SIZE=1`

- `LISTEND_REAZON_LANGUAGE=ja`（`ja` / `ja-en`）
- `LISTEND_REAZON_DEVICE=cpu`
- `LISTEND_REAZON_PRECISION=int8`（`int8` / `fp16` / `fp32`）

- `LISTEND_RTSP_TRANSPORT=auto`（`auto/tcp/udp`）
- `LISTEND_VAD_THRESHOLD=0.5`
- `LISTEND_MIN_SEGMENT_SEC=0.35`
- `LISTEND_OFF_TRANSCRIBE_COOLDOWN_SEC=0`
- `LISTEND_SESSION_END_SILENCE_SEC=3`
- `LISTEND_SILENCE_TIMEOUT_SEC=30`
- `LISTEND_CHUNK_MS=80`
- `LISTEND_DISPATCH_CMD=<command>`
- `LISTEND_DISPATCH_TIMEOUT_SEC=20`
- `LISTEND_LOG_LEVEL=INFO`
- 音声帯域フィルタは `.env` ではなく `python/listend.py` の `DEFAULT_AUDIO_FILTER` で管理する。
- セグメント区切り無音チャンク数は `.env` ではなく `python/listend.py` の `DEFAULT_SEGMENT_END_SILENCE_CHUNKS` で管理する。

## 5.3 STTバックエンド切替

1. faster-whisper を使う場合
- `LISTEND_STT_BACKEND="faster-whisper"`
- `LISTEND_WHISPER_MODEL` / `LISTEND_WHISPER_LANGUAGE` などを調整する。

2. ReazonSpeech k2 を使う場合
- `LISTEND_STT_BACKEND="reazonspeech-k2"`
- `LISTEND_REAZON_LANGUAGE` / `LISTEND_REAZON_DEVICE` / `LISTEND_REAZON_PRECISION` を設定する。

## 5.4 英語認識へ切替

- ReazonSpeech k2 で英語を含む運用にする場合:
  - `LISTEND_STT_BACKEND="reazonspeech-k2"`
  - `LISTEND_REAZON_LANGUAGE="ja-en"`（日英混在）
- faster-whisper で英語中心にする場合:
  - `LISTEND_STT_BACKEND="faster-whisper"`
  - `LISTEND_WHISPER_LANGUAGE="en"`（または `auto`）

## 5.3 `LISTEND_DISPATCH_CMD` のデフォルト

- 未指定時は `<workspace の1階層上>/bin/yatagarasu` を使う。
- 実行時は `YATAGARASU_CWD=<workspace>` を環境変数で渡す。

## 6. タイマー仕様

1. `LISTEND_SESSION_END_SILENCE_SEC`（デフォルト3秒）
- `ON` 状態の1ターン確定用。
- 発話終了後、この秒数無音なら dispatch する。

2. `LISTEND_SILENCE_TIMEOUT_SEC`（デフォルト30秒）
- `ON` 状態自体のタイムアウト用。
- この秒数無音なら `OFF` へ戻る。

## 6.1 負荷抑制パラメータ

1. `LISTEND_MIN_SEGMENT_SEC`
- この秒数未満の短いセグメントは文字起こししない。

2. `LISTEND_OFF_TRANSCRIBE_COOLDOWN_SEC`
- `OFF` 状態での連続文字起こしを抑制する。
- 連続ノイズ環境での CPU 使用率抑制に有効。

## 6.2 デバッグ可視化

- `LISTEND_LOG_LEVEL=DEBUG` で、文字起こししたチャンクをログ出力する。
- 出力例:
  - `[listend chunk#0001] state=OFF duration=1.12s text=...`
- ウェイク/ストップ判定は正規化して比較する（全半角、カタカナ/ひらがな、句読点差を吸収）。
- `LISTEND_LOG_LEVEL=DEBUG` で、正規化後文字列とヒット有無も出力する。

## 7. 障害設計

1. `ffmpeg` 切断
- 再接続を試行し、上限超過時は終了（systemd再起動へ委譲）。

2. 文字起こし失敗
- 当該セグメントを破棄し継続。
- ReazonSpeech k2 は長尺入力が不安定になりやすいため、実装側で約28秒単位に分割して処理する。

3. dispatch失敗
- エラーログ化して処理継続。

## 8. テスト観点

1. `OFF` で wake ワード含有セグメントを検知すると `ON` へ遷移する
2. wake セグメントの前置きが切り捨てられず全文採用される
3. `ON` で無音3秒後に dispatch される
4. `ON` で無音30秒後に `OFF` へ戻る
5. stop ワードで `OFF` へ遷移する
6. `.env` の wake/stop 未設定時は起動エラーになる
7. `LISTEND_STT_BACKEND` 切替時に想定バックエンドで初期化される
