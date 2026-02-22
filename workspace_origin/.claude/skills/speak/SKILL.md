---
name: speak
description: "Tapo TC70ロボット用の発声スキル。zundaスクリプトでテキストを音声に変換し、tapovoiceスクリプトでTapo TC70のスピーカーを鳴らす。ユーザーが「発声して」「喋って」「話して」と言う時や、ロボットに言葉を発させたい場合に使用"
---

# Speak - Tapo TC70 発声スキル

## Overview

このスキルは、Tapo TC70ロボットに日本語を発声させる機能を提供します。zunda音声合成スクリプトとtapovoiceスクリプトを組み合わせて、テキストを音声として出力します。

## Quick Start

基本的な発声コマンド:

```bash
SKILL_PATH/scripts/zunda "発話させたいテキスト" --stdout -s 68 | SKILL_PATH/scripts/tapovoice
```

- `--stdout`: 標準出力にWAV形式で出力
- `-s 68`: 音声の話者ID（68 = あいえるたん）

## Usage

### 基本的な発声

単純にテキストを発声させる場合:

```bash
SKILL_PATH/scripts/zunda "こんにちは、私はたねちゃん" --stdout -s 68 | SKILL_PATH/scripts/tapovoice
```

### スクリプト実行

直接コマンドを実行するには:

```bash
bash -c 'SKILL_PATH/scripts/zunda "$TEXT" --stdout -s 68 | SKILL_PATH/scripts/tapovoice'
```

### 複数文の発声

複数の文を続けて発声させる場合は、パイプで連結:

```bash
(SKILL_PATH/scripts/zunda "こんにちは" --stdout -s 68; SKILL_PATH/scripts/zunda "私はたねちゃんです" --stdout -s 68) | SKILL_PATH/scripts/tapovoice
```

## Parameters

| パラメータ | 説明 | デフォルト |
|-----------|------|----------|
| `-s` | 話者ID | 68 (あいえるたん) |
| `--stdout` | 標準出力にWAV出力 | 必須 |
| `--volume` | 音量 (0-100) | - |

## Speaker IDs

主な話者ID一覧:

- 46: 小夜/SAYO
- 68: あいえるたん
- 0: 四国めたん
- 1: ずんだもん

（必要に応じて他の話者IDも参照ドキュメントに追加可能）

## Notes

- zundaスクリプトは `SKILL_PATH/scripts/zunda` に配置されています
- tapovoiceスクリプトは `SKILL_PATH/scripts/tapovoice` に配置されています
- 日本語テキストのみ対応しています
- 長いテキストは処理に時間がかかる場合があります
