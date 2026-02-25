# Tapo Robot 初期バックログ

- 更新日: 2026-02-20

## Phase 1 基盤整理

- [ ] `docs/覚書.md` から確定事項を各正式ドキュメントへ移管する
- [ ] `python/listend.py` の要件ギャップ（wake/sleep処理不足）を洗い出す
- [ ] `workspace/ptz_control` のI/Fを `move-camera` 契約として固定する

## Phase 2 トリガ統合

- [ ] 音声トリガ（wake/sleep、無音タイムアウト）を状態機械として実装する
- [ ] 動体検知トリガ `motiond` を常駐サービス化する
- [ ] 定時ウェイクアップを `systemd timer` で実装する

## Phase 3 オーケストレーション

- [ ] トリガ共通イベント `TriggerEvent` を定義する
- [ ] prompt builder を実装し、文字起こしと記憶を統合する
- [ ] `claude -p` 単発起動ラッパを実装する
- [ ] AI出力から `speak` / `memory` スキル実行を行う

## Phase 4 記憶

- [ ] Semantic Memoryの保存I/Fを定義する
- [ ] 直近記憶と長期記憶の検索戦略を実装する
- [ ] 記憶参照をプロンプトテンプレートに組み込む

## Phase 5 デプロイ

- [ ] docker compose（voicevox/SemanticMemory）を確定する
- [ ] go2rtc の user systemd 運用を確定する
- [ ] systemd unit群を作成し、再起動ポリシーを設定する
- [ ] `workspace/.env`（`YATAGARASU_CWD/.env`）の設定ローダを実装する

## Phase 6 回帰テスト

- [ ] `speak` 回帰
- [ ] `move-camera` 回帰
- [ ] `view` 回帰
- [ ] `listend` ON/OFF遷移回帰
- [ ] motion -> orchestrator -> speak のE2E回帰
