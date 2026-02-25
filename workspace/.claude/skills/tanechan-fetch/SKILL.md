---
name: tanechan-fetch
description: Fetch and extract/summarize content from a specific webpage URL. Use this after tanen-chan-search to read detailed page content from selected results. Supports text extraction, title/meta, main article, or custom instructions-based summarization. Returns clean JSON.
---

# Tanen Chan Page Fetcher

## Overview
Fetches a webpage and processes it (extract main content, summarize, etc.) using a local Python script. Ideal for chaining: search first → pick promising URL → fetch here.

## Quick Start
```bash
FETCH_SCRIPT="/home/tane/.claude/skills/scripts/fetch.sh"
$FETCH_SCRIPT "https://tanep.work/some-page" --summarize "TALの最新進捗を要約"
$FETCH_SCRIPT "https://youtube.com/watch?v=xxx" --extract "動画タイトルと説明文"

## Usage
```bash
./scripts/fetch.sh "URL" [options]
```

| Argument       | Description                                      | Default    |
|----------------|--------------------------------------------------|------------|
| URL            | Target webpage URL (required)                    | -          |
| `--summarize`  | Summarization prompt (日本語OK)                  | (なし)     |
| `--extract`    | Extraction instruction (e.g. "タイトルと日付")   | (なし)     |
| `--fulltext`   | Raw main text (no summary)                       | false      |
| `--format`     | json (default)                                   | json       |

## Tips
- Claudeに「search結果のURLからこれをfetchして」と指示すれば自動チェーン
- YouTube URLもOK（transcriptやdescription抽出可能、ただし専用ツールがあればそっち優先）
- 長いページは要約推奨（コンテキスト節約）

## Resources
scripts/fetch.sh - Main fetch script
