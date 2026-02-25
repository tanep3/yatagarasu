# Tapo Robot デプロイ方針 v0.2

- 更新日: 2026-02-24
- 目的: 常駐安定性とハードウェア制御の両立

## 1. 方針

### A. すべて systemd（ホスト実行）

- 長所
  - デバイスアクセスが単純
  - デバッグしやすい
  - 低レイテンシ
- 短所
  - 依存衝突が起きやすい
  - 配布再現性が弱い

### B. すべて Docker

- 長所
  - 再現性が高い
  - サービス分離が明確
- 短所
  - 音声入出力・RTSP・ONVIF周りの調整が増える
  - 遅延要因が増える

### C. ハイブリッド（採用）

- user systemd: `listend` / `motiond` / orchestrator / wakeup timer / `go2rtc`
- docker compose: `voicevox_engine` / `SemanticMemory`
- 理由
  - go2rtc は host 配置の方が音声連携調整が容易
  - VoiceVox と SemanticMemory はコンテナ化で再現性を確保しやすい

## 2. 実運用構成

### 2.1 user systemd

- `go2rtc.service`
  - `external/go2rtc/go2rtc.yaml` を読み込んで常駐
- `yatagarasu-listend.service`
  - RTSP音声取得
  - VAD/ウェイクワード検知
  - ON/OFF状態遷移
- `yatagarasu-motiond.service`
  - 動体検知トリガ受信
- `yatagarasu-orchestrator@.service`
  - trigger payload から単発推論
- `yatagarasu-wakeup.timer` + `yatagarasu-wakeup.service`
  - 定時ウェイク

### 2.2 docker compose

- `external/voicevox_engine/docker-compose.yml`
  - `voicevox_engine`
- `external/SemanticMemory/docker-compose.yml`
  - `semanticmemory`

## 3. ストリーム分離（推奨）

- `listend` 用: `tapo_tc70`
- `speak` 用: `tapo_tc70_speak`

補足:
- `bin/tapovoice` のデフォルト送信先は `tapo_tc70_speak`。
- `listend` の `LISTEND_RTSP_URL` は通常 `tapo_tc70` を参照する。

## 4. 設定・秘密情報

- 設定は `YATAGARASU_CWD/.env` に集約する（標準運用例: `workspace/.env`）。
- `YATAGARASU_CWD` は systemd unit の `Environment=` で明示する。
- `.config.yml` は現行運用では不使用。

## 5. 起動順序

1. `go2rtc` 起動（user systemd）
2. Docker サービス起動（VoiceVox / SemanticMemory）
3. `yatagarasu-listend` と `motiond` 起動
4. `wakeup.timer` 起動
5. trigger 受信ごとに `orchestrator@` 実行

## 6. 運用ルール

- 失敗時は必ずログを保存し、原因を切り分ける。
- リグレッション確認として最低限以下を毎回実行する。
1. `speak` 実行確認
2. `move-camera` 実行確認
3. `view` 実行確認
4. `listend` ON/OFF遷移確認
5. `orchestrator` 単発起動確認
