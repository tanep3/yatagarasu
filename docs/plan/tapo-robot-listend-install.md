# `listend.py` インストール手順 v0.4

- 更新日: 2026-07-18
- 対象: `python/listend.py`

## 1. 前提

- リポジトリ: `yatagarasu`
- ワークスペース: 例 `workspace`（任意パス）
- `ffmpeg` が利用可能
- `uv` が利用可能
- `codex`（Codex CLI）、`claude`（Claude Code CLI）、または `opencode` が利用可能
- 実行時は `YATAGARASU_CWD=<workspace>` を指定する

補足:
- `LISTEND_DISPATCH_CMD` 未指定時は `<workspace親>/bin/yatagarasu` が使われる。
- `bin/yatagarasu` は `YATAGARASU_ENGINE` に応じてAIエージェントCLIを実行するため、利用するCLIの導入・認証が必要。

### 1.1 サブモジュール同期（初回/更新時）

```bash
cd /path/to/yatagarasu
git submodule update --init --recursive
```

補足:
- `external/ReazonSpeech` と `external/SemanticMemory` を同期する。

## 2. Python 環境作成

```bash
cd /path/to/yatagarasu/python
uv venv
uv sync
```

補足:
- `python/pyproject.toml` は `requires-python >=3.11`。
- `uv sync` で `faster-whisper` / `silero-vad` / `torch` を導入する。
- `uv sync`で`livekit-wakeword`とCPU版ONNX Runtimeを導入する。
- SBERT Skill Router 用の `sentence-transformers` / `transformers` / `sentencepiece` も `uv sync` で導入する。
- CUDA 依存を避けるため、`torch` / `torchaudio` は `python/pyproject.toml` の `pytorch-cpu` index から導入する。

### 2.1 ReazonSpeech k2 を使う場合（任意）

`LISTEND_STT_BACKEND="reazonspeech-k2"` を使うなら追加導入する。

```bash
cd /path/to/yatagarasu/python
uv pip install ../external/ReazonSpeech/pkg/k2-asr
```

## 3. `.env` 設定

`workspace/.env.example` をコピーして `workspace/.env` を作る。

```bash
cd /path/to/yatagarasu
cp workspace/.env.example workspace/.env
```

最低限設定（faster-whisper 例）:

```env
LISTEND_RTSP_URL="rtsp://localhost:8554/tapo_tc70"
LISTEND_RTSP_TRANSPORT="tcp"
LISTEND_RTSP_LOW_LATENCY="true"
LISTEND_WAKE_BACKEND="livekit"
LISTEND_WAKE_MODEL_PATH=""
LISTEND_WAKE_THRESHOLD="0.6"
LISTEND_WAKE_EARLY_THRESHOLD="0.15"
LISTEND_WAKE_EARLY_CONSECUTIVE="3"
LISTEND_WAKE_WARMUP_SEC="0.0"
LISTEND_WAKE_PROMPT_AUDIO=""
LISTEND_WAKE_PROMPT_GUARD_SEC="0.6"
LISTEND_WAKE_PROMPT_TIMEOUT_SEC="2.0"
LISTEND_WAKE_WORDS="ねぇ、ヤタガラス,ねえ、ヤタガラス"
LISTEND_STOP_WORDS="ストップ"
LISTEND_STT_BACKEND="faster-whisper"
LISTEND_WHISPER_MODEL="base"
LISTEND_SESSION_END_SILENCE_SEC="3"
LISTEND_SILENCE_TIMEOUT_SEC="3"
```

ReazonSpeech k2 を使う場合:

```env
LISTEND_STT_BACKEND="reazonspeech-k2"
LISTEND_REAZON_LANGUAGE="ja"
LISTEND_REAZON_DEVICE="cpu"
LISTEND_REAZON_PRECISION="int8"
```

主要任意設定:

```env
LISTEND_MIN_SEGMENT_SEC="0.3"
LISTEND_OFF_TRANSCRIBE_COOLDOWN_SEC="0"
LISTEND_DISPATCH_CMD=""
LISTEND_DISPATCH_TIMEOUT_SEC="180"
LISTEND_WAKE_ACK_WORD="考えるね。"
LISTEND_STANDBY_WORD="待機します。"
LISTEND_WAKE_ACK_SPEAKER_ID=""
LISTEND_WAKE_ACK_TIMEOUT_SEC="5"
LISTEND_LOG_LEVEL="INFO"
```

SBERT Skill Routerを使う場合:

```env
YATAGARASU_SBERT_ROUTER_ENABLED="true"
YATAGARASU_SBERT_DRY_RUN="true"
YATAGARASU_SBERT_MODEL="cl-nagoya/ruri-v3-70m"
YATAGARASU_SBERT_DEVICE="cpu"
YATAGARASU_SBERT_HIGH_THRESHOLD="0.78"
YATAGARASU_SBERT_MIDDLE_THRESHOLD="0.68"
YATAGARASU_SBERT_MOVE_SETTLE_SEC="1.0"
GO2RTC_FRAME_API_ENABLED="true"
```

英語運用の切替:
- ReazonSpeech k2: `LISTEND_REAZON_LANGUAGE="ja-en"`
- faster-whisper: `LISTEND_WHISPER_LANGUAGE="en"`（または `auto`）

補足:
- `LISTEND_DISPATCH_CMD` を空にすると `<workspace親>/bin/yatagarasu` を使用する。
- `ffmpeg` 音声フィルタは `.env` ではなく `python/listend.py` の `DEFAULT_AUDIO_FILTER` を使う。

## 4. 手動起動テスト

```bash
cd /path/to/yatagarasu
YATAGARASU_CWD="/path/to/yatagarasu/workspace" \
  ./python/.venv/bin/python ./python/listend.py
```

確認ポイント:
1. wakeワードで `OFF -> ON` に遷移する
2. 発話後、無音3秒で dispatch される
3. stopワードで `ON -> OFF` に遷移する
4. 起動ログに `stt_backend=...` が期待値で表示される
5. Router有効時、起動ログに `SBERT Router ready` が表示される
6. `LISTEND_LOG_LEVEL=DEBUG` 時、`[listend chunk#....]` と `[listend match#....]` が表示される

補足:
- `dispatch timed out` が出る場合は `LISTEND_DISPATCH_TIMEOUT_SEC` を増やす（例: 180）。
- `LISTEND_WAKE_ACK_WORD` はLLM dispatch直前にだけ再生する。Routerが `move-camera` だけで完結する場合は発話しない。
- OFF遷移時は `LISTEND_STANDBY_WORD` を発声する（空文字で無効）。
- Router有効時の `move-camera` は `ptz_worker` を使う。複数移動の間隔は `YATAGARASU_SBERT_MOVE_SETTLE_SEC` で調整する。

`461 Unsupported transport` が出る場合:
- `LISTEND_RTSP_TRANSPORT="auto"` か `udp` で再試行する。
- go2rtc 経由運用では `tcp` を優先する。

ストリーム分離（推奨）:
- `listend`: `tapo_tc70`
- `tapovoice`: `tapo_tc70_speak`（`bin/tapovoice` のデフォルト）

## 5. user systemd 登録

`~/.config/systemd/user/yatagarasu.service` を作成:

```ini
[Unit]
Description=Yatagarasu voice listener
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/yatagarasu/workspace
Environment=YATAGARASU_CWD=/path/to/yatagarasu/workspace
Environment=PATH=/home/<user>/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/path/to/yatagarasu/python/.venv/bin/python /path/to/yatagarasu/python/listend.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

注意:
- `systemd --user` は通常 `.bashrc` を読まないため、`codex` / `claude` が見つからない場合は unit 側で `Environment=PATH=...` を明示する。
- 例: CLIが `/home/<user>/.local/bin` や nvm 配下にある場合、そのディレクトリを PATH に含める。

有効化:

```bash
systemctl --user daemon-reload
systemctl --user enable yatagarasu
systemctl --user start yatagarasu
systemctl --user status yatagarasu
systemctl --user show yatagarasu -p Environment -p WorkingDirectory
```

ログ確認:

```bash
journalctl --user -u yatagarasu -f
```
