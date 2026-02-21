# Tapo Robot アプリ構成案 v0.1

- 作成日: 2026-02-20
- 目的: 既存スクリプト資産を活かしつつ、責務分離された構造に再配置する

## 1. 設計方針

- 処理中心ではなく、構造中心で分割する。
- トリガ層、推論層、デバイス層、記憶層を分離する。
- AI（Claude Code）から呼ぶI/Fはコマンド契約で固定する。

## 2. 現状配置（観測）

- `python/listend.py`: 音声取得と簡易状態管理
- `workspace/ptz_control`: PTZ操作CLI
- `go2rtc.yaml`: ストリーム設定
- `docs/覚書.md`: 要件・設計メモ混在

## 3. 目標フォルダ構成

```text
yatagarasu/
  docs/
    plan/
    tasks/
    phase_logs/
    considerations/
    research/
  python/
    pyproject.toml
    src/yatagarasu/
      config/
        loader.py
        schema.py
      contracts/
        events.py
        results.py
      triggers/
        voice_listener.py
        motion_watcher.py
        scheduled_wakeup.py
      orchestrator/
        pipeline.py
        prompt_builder.py
        claude_runner.py
      skills/
        speak.py
        move_camera.py
        view.py
        memory.py
      infra/
        tapo_client.py
        go2rtc_client.py
        voicevox_client.py
      app/
        main.py
  workspace/
    bin/
      speak
      move-camera
      view
      tapovoice
    prompts/
      motion_prompt.txt
      voice_prompt.txt
    systemd/
      yatagarasu-listend.service
      yatagarasu-motiond.service
      yatagarasu-orchestrator@.service
      yatagarasu-wakeup.timer
      yatagarasu-wakeup.service
```

## 4. モジュール責務

### 4.1 `triggers`

- 音声・動体・定時のイベントを検知し、共通 `TriggerEvent` に正規化する。

### 4.2 `orchestrator`

- `TriggerEvent` を受け、記憶参照 -> プロンプト構築 -> AI推論 -> スキル実行を制御する。

### 4.3 `skills`

- 外部副作用を持つ操作（発声、PTZ、映像取得、記憶保存）を単機能で提供する。

### 4.4 `infra`

- Tapo、go2rtc、VoiceVoxなどデバイス/外部サービス依存を隔離する。

### 4.5 `config`

- `~/.config/yatagarasu/.env` と `.config.yml` を読み込み、型付き設定へ変換する。

## 5. インタフェース契約（最小）

### TriggerEvent

- `source`: `voice` | `motion` | `cron`
- `timestamp`: ISO8601
- `payload`: transcribed text / motion summary / schedule metadata

### SkillResult

- `ok`: bool
- `message`: str
- `artifacts`: optional dict（生成ファイル、画像、音声など）

## 6. 既存資産の移行方針

- `workspace/ptz_control` は挙動維持を最優先し、まず `skills/move_camera.py` の内部呼び出し元として再利用する。
- `python/listend.py` は段階的に `triggers/voice_listener.py` に再編する。
- `docs/覚書.md` は一次情報として残し、確定事項は各ドキュメントへ転記する。
