# `listend.py` インストール手順 v0.3

- 更新日: 2026-02-24
- 対象: `python/listend.py`

## 1. 前提

- リポジトリ: `yatagarasu`
- ワークスペース: 例 `workspace`（任意パス）
- `ffmpeg` が利用可能
- `uv` が利用可能
- `claude`（Claude Code CLI）が利用可能
- 実行時は `YATAGARASU_CWD=<workspace>` を指定する

補足:
- `LISTEND_DISPATCH_CMD` 未指定時は `<workspace親>/bin/yatagarasu` が使われる。
- `bin/yatagarasu` は内部で `claude -p ...` を実行するため、`claude` の導入・認証が必要。

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
LISTEND_WAKE_WORDS="ヤタガラス"
LISTEND_STOP_WORDS="ストップ"
LISTEND_STT_BACKEND="faster-whisper"
LISTEND_WHISPER_MODEL="base"
LISTEND_SESSION_END_SILENCE_SEC="3"
LISTEND_SILENCE_TIMEOUT_SEC="10"
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
5. `LISTEND_LOG_LEVEL=DEBUG` 時、`[listend chunk#....]` と `[listend match#....]` が表示される

補足:
- `dispatch timed out` が出る場合は `LISTEND_DISPATCH_TIMEOUT_SEC` を増やす（例: 180）。
- 現在実装では `ON` 中の再wake時 ack は抑止（`OFF -> ON` 時のみ ack）。
- OFF遷移時は `LISTEND_STANDBY_WORD` を発声する（空文字で無効）。

`461 Unsupported transport` が出る場合:
- `LISTEND_RTSP_TRANSPORT="auto"` か `udp` で再試行する。
- go2rtc 経由運用では `tcp` を優先する。

ストリーム分離（推奨）:
- `listend`: `tapo_tc70`
- `tapovoice`: `tapo_tc70_speak`（`bin/tapovoice` のデフォルト）

## 5. user systemd 登録

`~/.config/systemd/user/yatagarasu-listend.service` を作成:

```ini
[Unit]
Description=Yatagarasu listend service
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
- `systemd --user` は通常 `.bashrc` を読まないため、`claude` が見つからない場合は unit 側で `Environment=PATH=...` を明示する。
- 例: `claude` が `/home/<user>/.local/bin/claude` の場合、`/home/<user>/.local/bin` を PATH に含める。

有効化:

```bash
systemctl --user daemon-reload
systemctl --user enable yatagarasu-listend
systemctl --user start yatagarasu-listend
systemctl --user status yatagarasu-listend
systemctl --user show yatagarasu-listend -p Environment -p WorkingDirectory
```

ログ確認:

```bash
journalctl --user -u yatagarasu-listend -f
```
