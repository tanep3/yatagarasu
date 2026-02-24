# `listend.py` インストール手順 v0.2

- 作成日: 2026-02-24
- 対象: `python/listend.py`

## 1. 前提

- リポジトリ: `yatagarasu`
- ワークスペース: 例 `workspace2`（任意パス）
- `ffmpeg` が利用可能
- `uv` が利用可能

## 2. Python 環境作成

```bash
cd /path/to/yatagarasu/python
uv venv
uv sync
```

補足:
- `python/.python-version` は `3.13`。
- 別バージョンを使う場合は `uv venv --python <version>` を明示する。

### 2.1 ReazonSpeech k2 を使う場合（任意）

`LISTEND_STT_BACKEND="reazonspeech-k2"` を使うなら、追加で ReazonSpeech k2 パッケージを入れる。

```bash
cd /path/to/yatagarasu
git clone https://github.com/reazon-research/ReazonSpeech.git external/ReazonSpeech
cd /path/to/yatagarasu/python
uv pip install ../external/ReazonSpeech/pkg/k2-asr
```

## 3. `.env` 設定

`<workspace>/.env.example` をコピーして `<workspace>/.env` を作る。

最低限設定:

```env
LISTEND_RTSP_URL="rtsp://localhost:8554/tapo_tc70"
LISTEND_RTSP_TRANSPORT="auto"
LISTEND_WAKE_WORDS="ヤタガラス"
LISTEND_STOP_WORDS="ストップ"
LISTEND_STT_BACKEND="reazonspeech-k2"
LISTEND_REAZON_LANGUAGE="ja"
LISTEND_SESSION_END_SILENCE_SEC="3"
LISTEND_SILENCE_TIMEOUT_SEC="30"
```

任意設定:

```env
LISTEND_STT_BACKEND="faster-whisper"
LISTEND_STT_LANGUAGE="ja"

LISTEND_WHISPER_MODEL="base"
LISTEND_WHISPER_COMPUTE_TYPE="int8"
LISTEND_WHISPER_LANGUAGE="ja"
LISTEND_WHISPER_BEAM_SIZE="1"

LISTEND_REAZON_LANGUAGE="ja"
LISTEND_REAZON_DEVICE="cpu"
LISTEND_REAZON_PRECISION="int8"

LISTEND_MIN_SEGMENT_SEC="0.35"
LISTEND_OFF_TRANSCRIBE_COOLDOWN_SEC="0"
LISTEND_DISPATCH_CMD=""
LISTEND_LOG_LEVEL="INFO"
```

英語運用の切替:
- ReazonSpeech k2: `LISTEND_REAZON_LANGUAGE="ja-en"`
- faster-whisper: `LISTEND_WHISPER_LANGUAGE="en"`（または `auto`）

`ffmpeg` の音声帯域フィルタは `python/listend.py` の `DEFAULT_AUDIO_FILTER`（デフォルト: `highpass=f=120,lowpass=f=5000`）で管理する。

`LISTEND_DISPATCH_CMD` を空にした場合:
- `<workspaceの1階層上>/bin/yatagarasu` が自動使用される。

## 4. 手動起動テスト

```bash
cd /path/to/yatagarasu
YATAGARASU_CWD="/path/to/yatagarasu/workspace2" \
  ./python/.venv/bin/python ./python/listend.py
```

確認ポイント:
1. wakeワード（ヤタガラス）で `OFF -> ON` に遷移する
2. 発話後、無音3秒で dispatch される
3. 無音30秒で `ON -> OFF` に戻る
4. ログに `[listend chunk#....]` 形式で聞き取ったチャンクが表示される
5. ログに `[listend match#....]` 形式でマッチ判定詳細が表示される
6. 起動ログに `stt_backend=...` が期待値で表示される

補足:
- 4, 5 の確認には `LISTEND_LOG_LEVEL="DEBUG"` を設定する。

`461 Unsupported transport` が出る場合:
- `LISTEND_RTSP_TRANSPORT="udp"` を設定して再試行する。

## 5. user systemd 登録

`~/.config/systemd/user/yatagarasu-listend.service` を作成:

```ini
[Unit]
Description=Yatagarasu listend service
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/yatagarasu/workspace2
Environment=YATAGARASU_CWD=/path/to/yatagarasu/workspace2
ExecStart=/path/to/yatagarasu/python/.venv/bin/python /path/to/yatagarasu/python/listend.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

有効化:

```bash
systemctl --user daemon-reload
systemctl --user enable yatagarasu-listend
systemctl --user start yatagarasu-listend
systemctl --user status yatagarasu-listend
```

ログ確認:

```bash
journalctl --user -u yatagarasu-listend -f
```
