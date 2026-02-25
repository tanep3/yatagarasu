# Yatagarasu セットアップマニュアル

- 更新日: 2026-02-25
- 対象: `yatagarasu` を新規セットアップする開発者
- 目的: 迷わず再現できるように、前提確認から常駐起動まで手順を一本化する

## 0. このシステムの起動構成

現行は「ハイブリッド構成」です。

- user systemd
  - `go2rtc`（カメラ中継）
  - `listend.py`（常時音声認識）
- Docker
  - `voicevox_engine`（TTSエンジン）
  - `SemanticMemory`（記憶API）
  - `searxng`（`tanechan-search` 用の検索エンジン）

## 1. 前提条件

## 1.1 必要コマンド

以下が使えることを確認します。

- `git`
- `docker` / `docker compose`
- `python3`（3.11以上）
- `uv`
- `ffmpeg` / `ffprobe` / `ffplay`
- `curl`
- `jq`
- `systemctl --user`

確認コマンド:

```bash
git --version
docker --version
docker compose version
python3 --version
uv --version
ffmpeg -version | head -n 1
```

## 1.2 Claude CLI

`bin/yatagarasu` は内部で **Claude Code CLI (`claude`)** を実行します。  
そのため `claude` コマンドが使える状態である必要があります。

公式インストール（推奨）:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

インストール後の確認:

```bash
claude --version
```

認証状態の確認（初回）:

```bash
claude
```

補足:
- `PATH` 反映のため、シェル再起動または `source ~/.bashrc` などが必要な場合があります。

重要:

- `listend.py` から `bin/yatagarasu` を起動する場合、`yatagarasu-listend.service` を動かす **同一ユーザー** で `claude` の導入と認証を済ませてください。

## 2. リポジトリ取得

```bash
git clone https://github.com/tanep3/yatagarasu.git
cd yatagarasu
git submodule update --init --recursive
```

補足:

- `external/SemanticMemory`
- `external/ReazonSpeech`

は submodule として管理されています。

## 3. ワークスペース設定（`.env`）

まず `.env` を作成します。

```bash
cp workspace/.env.example workspace/.env
```

最低限、以下を埋めてください。

```env
# Tapo
TAPO_HOST="192.168.x.x"
TAPO_PASSWORD="<tapo-app-password>"
TAPO_RTSP_USER="<camera-account-user>"
TAPO_RTSP_PASSWORD="<camera-account-password>"

# listend
LISTEND_RTSP_URL="rtsp://localhost:8554/tapo_tc70"
LISTEND_WAKE_WORDS="ヤタガラス"
LISTEND_STOP_WORDS="ストップ"
LISTEND_STT_BACKEND="faster-whisper"   # or reazonspeech-k2
```

重要:

- 実行時の作業ディレクトリは `workspace` を使う前提です。
- `YATAGARASU_CWD=<repo>/workspace` を systemd と手動実行で統一してください。

## 4. Python環境（`listend.py`）

```bash
cd python
uv venv
uv sync
```

`ReazonSpeech k2` を使う場合のみ追加インストール:

```bash
uv pip install ../external/ReazonSpeech/pkg/k2-asr
```

## 5. go2rtc セットアップ（user systemd）

## 5.1 バイナリ配置

```bash
mkdir -p ~/bin
wget https://github.com/AlexxIT/go2rtc/releases/download/v1.9.3/go2rtc_linux_amd64 -O ~/bin/go2rtc
chmod +x ~/bin/go2rtc
```

## 5.2 ストリーム設定

`external/go2rtc/go2rtc.yaml` を編集し、実機情報に置き換えます。

```yaml
streams:
  tapo_tc70:
    - rtsp://<RTSP_USER>:<RTSP_PASS>@<CAMERA_IP>:554/stream1
    - tapo://<TAPO_APP_PASSWORD>@<CAMERA_IP>
  tapo_tc70_speak:
    - rtsp://<RTSP_USER>:<RTSP_PASS>@<CAMERA_IP>:554/stream1
    - tapo://<TAPO_APP_PASSWORD>@<CAMERA_IP>
```

ポイント:

- `tapo_tc70`: listen 用
- `tapo_tc70_speak`: speak 用  
  (`bin/tapovoice` のデフォルト送信先)

## 5.3 user service 登録

```bash
mkdir -p ~/.config/systemd/user
cp external/go2rtc/go2rtc.service ~/.config/systemd/user/go2rtc.service
```

`~/.config/systemd/user/go2rtc.service` の `ExecStart=` を実環境パスに修正します。

```ini
ExecStart=/home/<user>/bin/go2rtc -config /home/<user>/.../yatagarasu/external/go2rtc/go2rtc.yaml
```

起動:

```bash
systemctl --user daemon-reload
systemctl --user enable --now go2rtc
systemctl --user status go2rtc
```

## 6. Dockerサービス起動

## 6.1 VoiceVox

```bash
cd external/voicevox_engine
docker compose up -d
```

疎通:

```bash
curl -s http://127.0.0.1:50021/version
```

## 6.2 SemanticMemory

```bash
cd external/SemanticMemory
docker compose up -d
```

疎通:

```bash
curl -s http://127.0.0.1:6001/docs > /dev/null && echo ok
```

## 6.3 searxng（`tanechan-search` 用）

`external/searxng/docker-compose.yml` を使います。

```bash
cd external/searxng
mkdir -p searxng
docker compose up -d
```

疎通:

```bash
curl -I http://127.0.0.1:8088
```

## 7. listend を user systemd で常駐

`~/.config/systemd/user/yatagarasu-listend.service` を作成:

```ini
[Unit]
Description=Yatagarasu listend service
After=network.target go2rtc.service

[Service]
Type=simple
WorkingDirectory=/home/<user>/.../yatagarasu/workspace
Environment=YATAGARASU_CWD=/home/<user>/.../yatagarasu/workspace
ExecStart=/home/<user>/.../yatagarasu/python/.venv/bin/python /home/<user>/.../yatagarasu/python/listend.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

起動:

```bash
systemctl --user daemon-reload
systemctl --user enable --now yatagarasu-listend
systemctl --user status yatagarasu-listend
journalctl --user -u yatagarasu-listend -f
```

ログアウト後も user service を動かす場合:

```bash
loginctl enable-linger "$USER"
```

## 8. 動作確認（最短ルート）

## 8.1 音声出力チェーン

```bash
cd /home/<user>/.../yatagarasu
./bin/zunda "テストです" --stdout -s 68 | ./bin/tapovoice
```

## 8.2 go2rtc 経由の音声取り込み

```bash
RTSP_URL='rtsp://localhost:8554/tapo_tc70'
ffmpeg -hide_banner -loglevel info -i "$RTSP_URL" -vn -ac 1 -ar 16000 -t 8 -y /tmp/listend_dbg.wav
ffplay -nodisp -autoexit /tmp/listend_dbg.wav
```

## 8.3 listend 手動起動（デバッグ）

```bash
cd /home/<user>/.../yatagarasu
YATAGARASU_CWD="$(pwd)/workspace" LISTEND_LOG_LEVEL=DEBUG ./python/.venv/bin/python ./python/listend.py
```

## 9. よくあるトラブル

1. `461 Unsupported transport`
- 対策: `LISTEND_RTSP_TRANSPORT="auto"` または `udp` で再試行。

2. `reconnecting in 3.0s...` が頻発
- 対策: `go2rtc` の `tapo_tc70` / `tapo_tc70_speak` 分離を確認。
- 対策: `journalctl --user -u go2rtc -f` で同時に原因を追う。

3. `dispatch timed out`
- 対策: `LISTEND_DISPATCH_TIMEOUT_SEC` を増やす（例: `180`）。

4. wake/stop を拾わない
- 対策: `LISTEND_LOG_LEVEL=DEBUG` で `[listend chunk#...]` / `[listend match#...]` を確認。
- 対策: STT backend（`faster-whisper` / `reazonspeech-k2`）を切替比較。

5. `tapovoice` で音が出ない
- 対策: `tapo_tc70_speak` ストリーム定義、`go2rtc` APIポート（1984）を確認。

6. `dispatch failed` / `dispatch timed out` で `claude` 関連エラーが出る
- 対策: `which claude` と `claude --version` を、`yatagarasu-listend.service` 実行ユーザーで確認。
- 対策: 手動で `bin/yatagarasu "test"` を実行して、`claude` 認証状態を確認。

## 10. セキュリティ注意

- `workspace/.env` にはカメラ認証情報が含まれます。
- 誤ってコミットしないよう注意してください。
- パスワードは必要に応じて定期ローテーションしてください。
