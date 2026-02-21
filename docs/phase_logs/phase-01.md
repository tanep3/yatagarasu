# Phase 01 ログ

## 2026-02-20

### 実施

- `docs` 配下の標準構造を初期化した
- 要件定義、アプリ構成、デプロイ方針の初版を作成した
- 初期バックログをPhase単位で分解した

### 判明

- 現状実装は `python/listend.py` と `workspace/ptz_control` が中心
- `docs/覚書.md` に要件・設計・実装メモが混在している

### リスク

- `listend.py` は wake/sleep の厳密な状態遷移実装が未完
- 設定ファイル位置（`~/.config/yatagarasu`）への統一が未着手

### 次アクション

1. 音声状態機械の仕様を確定する
2. `move-camera` 契約を固定する
3. ハイブリッドデプロイ前提で unit/compose 雛形を作成する
