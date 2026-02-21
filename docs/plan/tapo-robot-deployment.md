# Tapo Robot デプロイ方針 v0.1

- 作成日: 2026-02-20
- 目的: 常駐安定性とハードウェア制御の両立

## 1. 比較対象

### A. すべて systemd（ホスト実行）

- 長所
  - デバイスアクセスが単純
  - デバッグしやすい
  - 低レイテンシ
- 短所
  - 依存の衝突が起きやすい
  - 配布再現性が弱い

### B. すべて Docker

- 長所
  - 再現性が高い
  - サービス分離が明確
- 短所
  - 音声入出力・RTSP・ONVIF周りの調整が増える
  - 常時運用時の遅延要因が増える

### C. ハイブリッド（推奨）

- systemd: トリガ監視、オーケストレーション、ローカル制御CLI
- Docker: VoiceVox、go2rtc など外部依存の強いサービス
- 長所
  - レイテンシと再現性のバランスが最も良い
  - 障害切り分けがしやすい

## 2. 推奨構成

### 2.1 常駐サービス（systemd）

- `yatagarasu-listend.service`
  - RTSP音声取得
  - VAD/ウェイクワード検知
  - ON/OFF状態遷移
- `yatagarasu-motiond.service`
  - 動体検知トリガ受信
  - オーケストレータ起動
- `yatagarasu-orchestrator@.service`
  - trigger payloadを受けて単発推論実行
  - `claude -p ...` 呼び出し
- `yatagarasu-wakeup.timer` + `yatagarasu-wakeup.service`
  - 定時ウェイクアップ

### 2.2 コンテナサービス（docker compose）

- `voicevox_engine`
- `go2rtc`

## 3. 設定・秘密情報の配置

- `~/.config/yatagarasu/.env`
  - 接続情報、トークン、パスワード
- `~/.config/yatagarasu/.config.yml`
  - タイムアウト、閾値、モデル名、トリガ設定
- ファイル権限
  - `chmod 600 ~/.config/yatagarasu/.env`

## 4. 起動順序

1. Dockerサービス起動（voicevox/go2rtc）
2. `listend` と `motiond` 起動
3. timer開始
4. trigger受信ごとに `orchestrator@` を起動

## 5. 運用ルール

- 失敗時は必ずログ保存し、次フェーズへ進まない。
- リグレッション確認として、最低限以下を毎回実行する。
1. `speak` 実行確認
2. `move-camera` 実行確認
3. `view` 実行確認
4. `listend` のON/OFF遷移確認
5. `orchestrator` の単発起動確認
