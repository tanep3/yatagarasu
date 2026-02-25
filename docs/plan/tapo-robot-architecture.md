# Tapo Robot アプリ構成案 v0.2

- 更新日: 2026-02-24
- 目的: 既存スクリプト資産を活かしつつ、責務分離された構造を維持する

## 1. 設計方針

- 処理中心ではなく、構造中心で分割する。
- トリガ層、推論層、デバイス層、記憶層を分離する。
- AI（Claude Code）から呼ぶI/Fはコマンド契約で固定する。

## 2. 現状配置（実装準拠）

- `python/listend.py`: 音声取得、VAD、STT、wake/stop状態管理、dispatch
- `bin/yatagarasu`: `claude -p` 実行とTTS連携
- `bin/zunda`: 音声合成
- `bin/tapovoice`: go2rtc 経由で Tapo へ音声送信（既定 `tapo_tc70_speak`）
- `external/go2rtc/go2rtc.yaml`: ストリーム設定（listen/speak 分離）
- `external/go2rtc/HowToInstall.md`: go2rtc host/systemd 導入手順
- `external/voicevox_engine/docker-compose.yml`: VoiceVox コンテナ
- `external/SemanticMemory/docker-compose.yml`: SemanticMemory コンテナ
- `workspace/.env`: 実行設定の単一ソース

## 3. 目標フォルダ構成（段階的移行）

```text
yatagarasu/
  bin/
    yatagarasu
    zunda
    tapovoice
  python/
    listend.py
    pyproject.toml
    src/yatagarasu/
      config/
      contracts/
      triggers/
      orchestrator/
      skills/
      infra/
  external/
    go2rtc/
      go2rtc.yaml
      HowToInstall.md
    voicevox_engine/
      docker-compose.yml
    SemanticMemory/
      docker-compose.yml
    ReazonSpeech/
  workspace/
    .env
    .env.example
    media/
  docs/
    plan/
    tasks/
    phase_logs/
    considerations/
    research/
```

## 4. モジュール責務

### 4.1 triggers

- 音声・動体・定時イベントを検知し、共通イベント形式へ正規化する。

### 4.2 orchestrator

- trigger入力を受け、記憶参照 -> プロンプト構築 -> AI推論 -> スキル実行を制御する。

### 4.3 skills

- 外部副作用を持つ操作（発声、PTZ、映像取得、記憶保存）を単機能で提供する。

### 4.4 infra

- Tapo、go2rtc、VoiceVox、SemanticMemory など外部依存を隔離する。

### 4.5 config

- `YATAGARASU_CWD/.env` を読み込み、型付き設定へ変換する。
- 現行運用では `.config.yml` は使わない。

## 5. インタフェース契約（最小）

### TriggerEvent

- `source`: `voice` | `motion` | `cron`
- `timestamp`: ISO8601
- `payload`: transcribed text / motion summary / schedule metadata

### SkillResult

- `ok`: bool
- `message`: str
- `artifacts`: optional dict（生成ファイル、画像、音声など）

## 6. 移行方針

- `python/listend.py` は現行単体運用を維持しつつ、将来的に `src/yatagarasu/triggers/voice_listener.py` へ分割する。
- `bin/*` のCLI契約は維持し、内部実装のみ段階的に整理する。
- 確定事項は `docs/plan` に反映し、未確定は `docs/considerations` で管理する。
