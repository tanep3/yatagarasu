# Yatagarasu セットアップマニュアル

- 更新日: 2026-07-18
- 対象: `yatagarasu` を新規セットアップする開発者
- 目的: 迷わず再現できるように、前提確認から常駐起動まで手順を一本化する

## 0. このシステムの起動構成

現行は「ハイブリッド構成」です。

- user systemd
  - `go2rtc`（カメラ中継）
  - `listend.py`（常時音声認識 / SBERT Skill Router / AI dispatch）
- host service
  - `Ollama`（SemanticMemory要約用）
- Docker
  - `voicevox_engine`（TTSエンジン）
  - `SemanticMemory`（記憶API、ホストOllamaに接続）
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
- `ollama`（SemanticMemory要約用）
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
ollama --version
```

## 1.2 AIエージェントCLI

`bin/yatagarasu` は内部でAIエージェントCLIを実行します。
現在は **Codex CLI (`codex`)**、**Claude Code CLI (`claude`)**、**opencode (`opencode`)** に対応しています。
`.env` の `YATAGARASU_ENGINE` で利用するエンジンを選択します。

Codex CLIを使う場合の確認:

```bash
codex --version
codex exec "hello"
```

HoshikageをCodexの推論Providerとして使う場合、Codex CLIの導入だけでは接続されません。次の三つをYatagarasu側で指定します。

1. Hoshikage Providerを記述したCodex Profile
2. Hoshikageで利用するModel Bundle名
3. LAN認証用Token

Hoshikage server machineで用途名付きTokenと対話用Profileを生成します。

```bash
hoshikage token create yatagarasu
hoshikage token list
hoshikage codex-config \
  --model unsloth-gemma4-12b-qat-thinking-off \
  --mode interactive \
  --base-url http://<HOSHIKAGE_LAN_IP>:3030/v1 \
  --authenticated
```

最後のコマンドが出力したTOMLを、Yatagarasuを動かすユーザーの`$CODEX_HOME/yatagarasu-local.config.toml`へ配置します。`CODEX_HOME`未設定時は通常`~/.codex`です。Hoshikageは利用者のCodex設定を自動変更しません。

生成結果の`[sandbox_workspace_write] network_access = true`は削除しないでください。Codex sandbox内のSearch、Fetch、RecallなどがLAN・Internetへ接続するために必要で、Doctorもこの設定を検証します。

次に、Git管理外の`workspace/.env`へ設定します。

```bash
YATAGARASU_ENGINE="codex"
YATAGARASU_CODEX_PROFILE="yatagarasu-local"
YATAGARASU_CODEX_MODEL="unsloth-gemma4-12b-qat-thinking-off"
HOSHIKAGE_API_KEY="<hoshikage token listで確認したToken>"
YATAGARASU_CODEX_BYPASS_SANDBOX="false"
```

`HOSHIKAGE_API_KEY`はLAN上のHoshikageへ接続するクライアントを識別するBearer Tokenです。server machineのToken保存ファイルをYatagarasuから直接参照せず、Token本文だけを`workspace/.env`からCodex子プロセスへ渡します。TokenをGit、Profile、コマンド履歴、ログへ残さないでください。

接続診断:

```bash
bin/yatagarasu doctor --no-services --no-logs
```

DoctorはProfileの存在、Provider、モデル、`wire_api`、Token設定、認証付き`/ready`を順番に確認します。Token本文は表示しません。

既に`yatagarasu.service`が稼働している状態で`workspace/.env`のProvider、モデル、Token、sandbox設定を変更した場合は、長時間稼働中の音声processへ再読込させます。

```bash
systemctl --user restart yatagarasu.service
systemctl --user is-active yatagarasu.service
```

`.env`を更新しても再起動しなければ、音声dispatchだけが更新前のモデルや実行条件を使い続ける場合があります。

対話確認:

```bash
cd workspace
../bin/yatagarasu --engine codex "Return exactly OK."
```

対話利用では`YATAGARASU_CODEX_BYPASS_SANDBOX="false"`を維持します。`true`は承認とsandboxを完全に無効化するため、Phase 6Bの無人実行設計に従う場合以外は使用しません。

`yatagarasu.service`は`YATAGARASU_CWD`を`workspace`へ固定します。手動実行でもSkillを自動検出させるため、上記のように`workspace`から起動するか、`YATAGARASU_CWD`を明示してください。

Claude Codeを使う場合の確認:

```bash
claude --version
claude -p "hello" --model haiku
```

Claude Codeの公式インストール例:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

重要:

- `listend.py` から `bin/yatagarasu` を起動する場合、`yatagarasu.service` を動かす **同一ユーザー** で、利用するCLIの導入と認証を済ませてください。
- `systemd --user` は通常 `.bashrc` を読まないため、CLIがnvmやユーザー固有PATH配下にある場合は unit 側の `Environment=PATH=...` を確認してください。

## 1.3 実運用設定を守る更新方針

`workspace/.env` はカメラ認証情報、VOICEVOX接続先、利用モデルなどの固有設定を含むため、Git管理しません。
リポジトリで管理するのは `workspace/.env.example` だけです。

運用環境で更新する時の基本手順:

```bash
git status --short
cp workspace/.env workspace/.env.local.backup
git pull --ff-only
diff -u workspace/.env.example workspace/.env.local.backup
```

`git pull` で固有設定を消さないための原則:
- `workspace/.env` はコミットしない。
- 変更が必要な設定キーは `workspace/.env.example` に追加し、実値は運用側の `.env` に手で反映する。
- 実運用でだけ発生したコード修正は、先に開発用リポジトリへ移植してから運用側へ戻す。
- もし過去に `.env` をGit追跡してしまった場合は、開発リポジトリ側で `git rm --cached workspace/.env` してから `.gitignore` で除外する。

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
LISTEND_RTSP_LOW_LATENCY="true"
LISTEND_WAKE_BACKEND="livekit"
LISTEND_WAKE_WORDS="ねぇ、ヤタガラス,ねえ、ヤタガラス"
LISTEND_STOP_WORDS="ストップ"
LISTEND_STT_BACKEND="faster-whisper"   # or reazonspeech-k2
LISTEND_SILENCE_TIMEOUT_SEC="3"
SPEAKER_ID="13"
```

SBERT Skill Routerを使う場合は、まずdry-runで判定だけ確認してから実行を有効化します。

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

重要:

- 実行時の作業ディレクトリは `workspace` を使う前提です。
- `YATAGARASU_CWD=<repo>/workspace` を systemd と手動実行で統一してください。

## 4. Python環境（`listend.py`）

```bash
cd python
uv venv
uv sync
```

LiveKit WakeWord、SBERT Skill Router用の
`livekit-wakeword` / `sentence-transformers` / `transformers` / `sentencepiece`も
`uv sync`で導入されます。
CUDA 依存を避けるため、`torch` / `torchaudio` は `python/pyproject.toml` の `pytorch-cpu` index から導入します。

`ReazonSpeech k2` を使う場合のみ追加インストール:

```bash
uv pip install ../external/ReazonSpeech/pkg/k2-asr
```

`uv sync`はプロジェクト外から手動導入したReazonSpeechを環境から外すことがあります。
ReazonSpeech利用環境では、コード更新時も必ず`uv sync`の後に上記コマンドを実行してください。

## 4.1 SBERT Skill Router

SBERT Skill Routerは、LLMへ渡す前に「右を向いて」「何が見える？」「前に話したことを思い出して」のような明示Intentを軽く判定します。

初期セットアップでは安全のため、`YATAGARASU_SBERT_ROUTER_ENABLED="false"`、`YATAGARASU_SBERT_DRY_RUN="true"` を推奨します。
有効化する場合は次の順で進めます。

1. `YATAGARASU_SBERT_ROUTER_ENABLED="true"`、`YATAGARASU_SBERT_DRY_RUN="true"` で起動する。
2. ログに `SBERT Router ready` と判定結果が出ることを確認する。
3. 問題なければ `YATAGARASU_SBERT_DRY_RUN="false"` にする。
4. モデルキャッシュ後、外部通信を避けたい運用では `YATAGARASU_SBERT_OFFLINE="true"` にする。

手動判定テスト:

```bash
cd /home/<user>/.../yatagarasu
YATAGARASU_CWD="$(pwd)/workspace" \
  ./python/.venv/bin/python ./python/intent_router.py "右を向いて何が見える？"
```

実行対象:
- `move-camera`: 右/左45度、上/下30度、キャリブレーション。移動だけならLLMを呼ばず、発話もしません。
- `view`: 撮影画像の絶対パスをLLMプロンプトへ渡します。`GO2RTC_FRAME_API_ENABLED="true"` ならHTTP frame APIを優先します。
- `recall`: SemanticMemory検索結果をLLMプロンプトへ渡します。

`move-camera` は `ptz_worker` を常駐させ、Tapo接続を使い回します。複数の移動を連続実行する場合は `YATAGARASU_SBERT_MOVE_SETTLE_SEC` 秒だけ待ってから次の動作へ進みます。

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

## 6.2 Ollama（SemanticMemory依存）

`SemanticMemory` は内部で要約時に `Ollama` を呼び出します。  
このリポジトリの `external/SemanticMemory/docker-compose.yml` は
`OLLAMA_URL=http://host.docker.internal:11434` を使うため、
**ホスト側で Ollama を起動**しておく必要があります。

導入（Linux）:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama --version
```

動作確認:

```bash
curl -s http://127.0.0.1:11434/api/tags
```

SemanticMemory既定モデルの取得:

```bash
ollama pull hf.co/SakanaAI/TinySwallow-1.5B-Instruct-GGUF:Q8_0
```

補足:
- モデルを変える場合は `external/SemanticMemory/.env` の `LLM_MODEL` を合わせて変更してください。

## 6.3 SemanticMemory

```bash
cd external/SemanticMemory
test -f .env || cp .env.example .env
docker compose \
  -f docker-compose.yml \
  -f ../../deploy/semanticmemory.compose.override.yml \
  up -d --build
```

Yatagarasu固有のコンテナ名と運用時のソースマウントは
`deploy/semanticmemory.compose.override.yml`に分離しています。
SemanticMemory本体のCompose設定を直接編集しないため、submoduleを更新しても
運用設定が未コミット変更として残りません。

SemanticMemoryはCPU専用のPyTorch wheelを使用します。GPUを搭載していない環境で
CUDA/NVIDIAパッケージを取得しないため、初回ビルド時間とイメージ容量を抑えられます。

新規Docker環境ではRuri v3を既定の埋め込みモデルとして使用します。
既存環境は、YatagarasuをアップデートしてもRuri v2からRuri v3へ自動移行しません。
v2を継続利用する場合は追加操作不要です。v3を利用する場合は、`.env`の
`SBERT_MODEL`だけを先に変更せず、
[SemanticMemory Ruri v3 移行ガイド](semanticmemory-ruri-v3-migration.md)に従って
バックアップ、安全なベクトル再構築、整合性確認を行ってください。

疎通:

```bash
curl -s http://127.0.0.1:6001/docs > /dev/null && echo ok
```

## 6.4 searxng（`tanechan-search` 用）

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

`~/.config/systemd/user/yatagarasu.service` を作成:

```ini
[Unit]
Description=Yatagarasu voice listener
After=network.target go2rtc.service

[Service]
Type=simple
WorkingDirectory=/home/<user>/.../yatagarasu/workspace
Environment=YATAGARASU_CWD=/home/<user>/.../yatagarasu/workspace
Environment=PATH=/home/<user>/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/<user>/.../yatagarasu/python/.venv/bin/python /home/<user>/.../yatagarasu/python/listend.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

重要:
- `systemd --user` サービスは通常 `.bashrc` を読まないため、`Environment=PATH=...` を unit に明示してください。
- `claude` が `/home/<user>/.local/bin/claude` にある場合、`/home/<user>/.local/bin` を必ず含めてください。

起動:

```bash
systemctl --user daemon-reload
systemctl --user enable --now yatagarasu
systemctl --user status yatagarasu
systemctl --user show yatagarasu -p Environment -p WorkingDirectory
journalctl --user -u yatagarasu -f
```

ログアウト後も user service を動かす場合:

```bash
loginctl enable-linger "$USER"
```

## 8. 動作確認（最短ルート）

## 8.0 doctor

まず環境診断を実行します。

```bash
bin/yatagarasu doctor
bin/yatagarasu doctor --verbose
```

`doctor`は`.env`、AIエージェントCLI、VOICEVOX、go2rtc、音声送信コマンド、
LiveKit WakeWord、ONNXモデル、CPU Provider、prompt音声、systemdサービス、直近ログを確認します。

## 8.1 音声出力チェーン

```bash
cd /home/<user>/.../yatagarasu
./bin/zunda "テストです" --stdout -s 13 | ./bin/tapovoice
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

標準ウェイク動作:

1. カメラから1m程度の位置で「ねぇ、ヤタガラス」と発話する。
2. 青山龍星の「はい」が再生されることを確認する。
3. prompt再生後に「右を向いて」などの命令を発話する。
4. ログに`OFF -> WAKING -> ON`とONNX scoreが記録されることを確認する。

従来のSTTウェイクへ戻す場合:

```env
LISTEND_WAKE_BACKEND="stt"
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

6. `dispatch failed` / `dispatch timed out` でAIエージェントCLI関連エラーが出る
- 対策: `which codex` / `codex --version`、または `which claude` / `claude --version` を、`yatagarasu.service` 実行ユーザーで確認。
- 対策: 手動で `bin/yatagarasu --engine codex "test"` または `bin/yatagarasu --engine claude "test"` を実行して、CLI認証状態を確認。
- 対策: `codex: command not found` / `claude: command not found` の場合、unit に `Environment=PATH=/home/<user>/.local/bin:/usr/local/bin:/usr/bin:/bin` を追加し、`daemon-reload` 後に再起動。

7. `SemanticMemory` で要約だけ失敗する / `OLLAMA_URL` 接続エラー
- 対策: ホストで `curl -s http://127.0.0.1:11434/api/tags` が成功するか確認。
- 対策: `ollama pull hf.co/SakanaAI/TinySwallow-1.5B-Instruct-GGUF:Q8_0` でモデルを取得。
- 対策: `external/SemanticMemory/.env` の `OLLAMA_URL` / `LLM_MODEL` を実環境に合わせる。

8. `右を向いて左を向いて` などの複合移動が詰まる / 速すぎる
- 対策: `YATAGARASU_SBERT_MOVE_SETTLE_SEC` を調整する。実機では `1.0` 秒を基準にする。

9. `何が見える？` で画像取得に失敗する
- 対策: `curl -s "http://127.0.0.1:1984/api/streams"` でgo2rtc APIが見えるか確認。
- 対策: `GO2RTC_FRAME_API_ENABLED="true"` でHTTP frame APIを優先する。失敗時はRTSP取得へフォールバックします。

## 10. セキュリティ注意

- `workspace/.env` にはカメラ認証情報が含まれます。
- 誤ってコミットしないよう注意してください。
- パスワードは必要に応じて定期ローテーションしてください。
