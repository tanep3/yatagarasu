---
name: view
description: "Tapo TC70ロボット用の視覚スキル。go2rtc経由でカメラ画像を取得し、LLM入力に適したサイズにリサイズする。ユーザーが「見て」「確認して」「何が見える？」「画像を取得」と言う時や、ロボットに周囲を認識させたい場合に使用"
---

# View - Tapo TC70 視覚スキル

## Overview

このスキルは、Tapo TC70ロボットのカメラから画像を取得する機能を提供します。go2rtcストリーミングサーバー経由でRTSPストリームにアクセスし、画像をキャプチャしてLLM入力に適したサイズにリサイズします。

## Quick Start

基本的な画像取得コマンド（workspace/mediaに保存）:

```bash
SKILL_PATH/scripts/capture
```

ファイル名を指定して保存:

```bash
SKILL_PATH/scripts/capture -o photo.jpg
```

標準出力にJPEG画像を出力:

```bash
SKILL_PATH/scripts/capture > image.jpg
```

## Usage

### 基本的な使用法

```bash
# workspace/mediaにタイムスタンプ付きで保存（デフォルト）
SKILL_PATH/scripts/capture

# ファイル名を指定して保存（workspace/media配下）
SKILL_PATH/scripts/capture -o photo.jpg

# 絶対パスで保存
SKILL_PATH/scripts/capture -o /tmp/photo.jpg

# サイズ指定（640x480）
SKILL_PATH/scripts/capture -o photo.jpg -w 640 -h 480

# 標準出力に出力
SKILL_PATH/scripts/capture > image.jpg

# 環境変数で設定
STREAM=tapo_tc70 WIDTH=1280 HEIGHT=720 SKILL_PATH/scripts/capture -o hd.jpg
```

### LLM入力用サイズ推奨

- **小さい画像（高速）**: 320x240 - テキスト認識や単純な物体検出
- **標準サイズ**: 640x480 - 一般的な画像認識
- **高画質**: 1280x720 - 詳細な認識が必要な場合

## Parameters

| オプション | 説明 | デフォルト |
|-----------|------|----------|
| `-s, --stream NAME` | ストリーム名 | tapo_tc70 |
| `-w, --width WIDTH` | 出力幅 | 640 |
| `-h, --height HEIGHT` | 出力高さ | 480 |
| `-q, --quality QUALITY` | JPEG品質 1-100 | 85 |
| `-o, --output FILE` | 出力ファイル（相対パスはmedia配下） | タイムスタンプ付き |
| `--host HOST` | go2rtcホスト | localhost |
| `--rtsp-port PORT` | RTSPポート | 8554 |

## Environment Variables

| 変数 | 説明 | デフォルト |
|------|------|----------|
| `GO2RTC_HOST` | go2rtcホスト | localhost |
| `GO2RTC_RTSP_PORT` | RTSPポート | 8554 |
| `STREAM` | ストリーム名 | tapo_tc70 |
| `WIDTH` | 出力幅 | 640 |
| `HEIGHT` | 出力高さ | 480 |
| `QUALITY` | JPEG品質 | 85 |
| `OUTPUT` | 出力ファイル | - |
| `WORKSPACE_MEDIA` | 画像保存先ディレクトリ | workspace/media |

## Requirements

- go2rtcが実行中であること
- ffmpegがインストールされていること
- ストリームがgo2rtcに設定されていること

## Notes

- 環境変数は `workspace/.env` ファイルで一元管理することを推奨します
- 出力ファイル名を指定しない場合、`workspace/media/capture_YYYYMMDD_HHMMSS.jpg` に保存されます
- 相対パスを指定した場合、`workspace/media/` 配下に保存されます
- 画像取得には1-2秒かかる場合があります
- カメラの起動時間によっては、最初の数回の取得で失敗する可能性があります
- アスペクト比は維持され、指定されたサイズ内に収まるようにリサイズされます
