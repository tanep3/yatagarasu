---
name: move-camera
description: "Tapo TC70ロボット用のカメラ制御スキル。Pytapoを使用してカメラのPTZ（Pan-Tilt-Zoom）制御を行う。ユーザーが「左を見て」「右に向けて」「カメラを動かして」「上を見て」「下を見て」と言う時や、ロボットに視線を移動させたい場合に使用"
---

# Move Camera - Tapo TC70 カメラ制御スキル

## Overview

このスキルは、Tapo TC70ロボットのカメラをPTZ制御する機能を提供します。Pytapoライブラリを使用して、カメラの水平移動（パン）、垂直移動（チルト）、座標指定移動、キャリブレーションなどをサポートします。

## Requirements

- Pytapoがインストールされていること
  ```bash
  cd /path/to/python && uv pip install pytapo
  ```
- Tapoカメラの認証情報（IPアドレス、ユーザー名、パスワード）

## Quick Start

基本的なカメラ制御コマンド:

```bash
# <workspace>/.envファイルで認証情報を設定（推奨）

# 左に回転
SKILL_PATH/scripts/ptz_control.sh --left

# 右に回転
SKILL_PATH/scripts/ptz_control.sh --right
```

## Usage

### 基本的な移動

```bash
# 左に45度回転
SKILL_PATH/scripts/ptz_control --left

# 右に45度回転
SKILL_PATH/scripts/ptz_control --right

# 上に30度向ける
SKILL_PATH/scripts/ptz_control --up

# 下に30度向ける
SKILL_PATH/scripts/ptz_control --down
```

**移動角度と可動範囲:**
- **水平移動（パン）**: left/right は45度ずつ移動、**キャリブレーション中央点を中心に左右180度ずつ（合計360度）**
- **垂直移動（チルト）**: up/down は30度ずつ移動、**上下約120度の可動範囲**

**座標系の説明:**
- `moveMotor(x, y)` は現在地を起点に相対移動します
- `x`: 水平方向（パン）- 負値で左、正値で右
- `y`: 垂直方向（チルト）- 正値で上、負値で下

### 座標指定移動

```bash
# 座標指定で移動 (x, y) - 現在値から座標指定で差分移動
SKILL_PATH/scripts/ptz_control --move 100 50

# 中央に戻す
SKILL_PATH/scripts/ptz_control --move 0 0
```

### その他の機能

```bash
# モーターキャリブレーション
SKILL_PATH/scripts/ptz_control --calibrate

# モーター能力を取得
SKILL_PATH/scripts/ptz_control --capability
```

## Parameters

| オプション | 説明 |
|-----------|------|
| `--left` | 左に45度回転（move -45 0） |
| `--right` | 右に45度回転（move 45 0） |
| `--up` | 上に30度向ける（move 0 30） |
| `--down` | 下に30度向ける（move 0 -30） |
| `--move X Y` | 現在値から角度指定で差分移動（x: 水平, y: 垂直、負値も可） |
| `--calibrate` | モーターキャリブレーション |
| `--capability` | モーター能力を取得 |
| `--host HOST` | カメラのIPアドレス |
| `--user USER` | ユーザー名 |
| `--password PASSWORD` | パスワード |

## Environment Variables

| 変数 | 説明 | デフォルト |
|------|------|----------|
| `TAPO_HOST` | カメラのIPアドレス | 192.168.0.132 |
| `TAPO_USER` | ユーザー名 | admin |
| `TAPO_PASSWORD` | パスワード | 必須 |

## Notes

- 環境変数は `<workspace>/.env` ファイルで一元管理することを推奨します
- Pytapoはpythonディレクトリでuvを使ってインストールする必要があります
- スクリプト実行時は `ptz_control.sh` ラッパー経由で実行することを推奨します
- カメラの認証情報はTapoアプリの「詳細設定」→「カメラアカウント」で作成してください
- キャリブレーションはカメラの位置がずれている場合や、正確な位置を把握したい場合に実行してください

### ⚠️ 移動位置の管理について

**重要**: 各コマンドは現在位置からの相対移動です。連続して移動する場合は、現在位置を把握する必要があります。

**移動例（右→左→中央）:**
```bash
# 現在位置: 中央
ptz_control --right    # 右に45度移動 → 現在位置: 右45度
ptz_control --left     # 左に45度移動 → 現在位置: 中央に戻る
ptz_control --left     # 左に45度移動 → 現在位置: 左45度
```

**探索パターン例（360度パノラマ）:**
```bash
# キャリブレーション後、中央から開始
ptz_control --right    # 右45度
ptz_control --right    # 右90度
ptz_control --right    # 右135度
ptz_control --right    # 右180度（右限界）
ptz_control --left     # 右135度
ptz_control --left     # 右90度
ptz_control --left     # 右45度
ptz_control --left     # 中央に戻る
ptz_control --left     # 左45度
ptz_control --left     # 左90度
ptz_control --left     # 左135度
ptz_control --left     # 左180度（左限界）
# 左右各180度、合計360度の範囲をカバー
```

**上下移動の最大範囲:**
```bash
# 垂直方向の最大可動範囲は約120度（up/down 各4回分）
# 超えるとエラーになるので注意してください
ptz_control --up       # 上に30度（残り90度）
ptz_control --up       # 上に30度（残り60度）
ptz_control --up       # 上に30度（残り30度）
ptz_control --up       # 上に30度（最大到達）
# ptz_control --up   # これはエラーになります
```
