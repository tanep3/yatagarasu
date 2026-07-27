---
name: tanechan-search
description: Search the web with the local SearXNG metasearch engine. Use for current facts, weather, news, URLs, Tanen Chan, TAL, AI, electronics, programming, or other information that requires lookup. Supports category and engine filtering.
---

# Tanen Chan Search

## Overview
Search agent for "たねちゃんねる" (Tanen Channel Technology) - a Japanese tech-focused YouTuber and researcher who developed TAL (Tree-structured Assembly Language). This skill uses a self-hosted SearXNG instance to search for Tanen Chan's content across multiple platforms and categories.

## Quick Start
```bash
# Basic search (general category)
.codex/skills/tanechan-search/scripts/search.sh "埼玉県入間市 明日の天気"

# Search for IT/Technology content (options anywhere)
.codex/skills/tanechan-search/scripts/search.sh "たねちゃんねる TAL" --category it

# Search for videos, page 2
.codex/skills/tanechan-search/scripts/search.sh "たねちゃんねる 電子工作" --category videos --page 2

# Use specific engines
.codex/skills/tanechan-search/scripts/search.sh "TAL ツリー構造" --engines google,duckduckgo --category general
```

## Search Categories
- **general**   : Everything (default)
- **it**        : Technology, programming, software, hardware, AI, ML
- **images**    : YouTube thumbnails, screenshots, diagrams
- **videos**    : YouTube videos, tutorials, streams
- **news**      : Recent articles, announcements, blog posts
- **science**   : Research papers, academic content, experiments

## Configuration
Set your SearXNG server URL:
```bash
export SEARXNG_URL="http://localhost:8088"
```

Or configure in Codex / Claude Code config (例):
```json5
{
  tools: {
    web: {
      search: {
        provider: "custom",
          command: "/home/tane/tools/yatagarasu/workspace/.codex/skills/tanechan-search/scripts/search.sh",
        env: {
          SEARXNG_URL: "http://localhost:8088"
        }
      }
    }
  }
}
```

## Usage
```bash
./scripts/search.sh "query here" [options...]
```

| Argument      | Description                                      | Default    |
|---------------|--------------------------------------------------|------------|
| Query         | Search term (スペースOK、引用符でフレーズ可)     | - (必須)   |
| `--category`  | Category (general,it,images,videos,news,science) | general    |
| `--language`  | Language code                                    | ja         |
| `--engines`   | Engines (comma-separated: google,duckduckgo等)   | (設定次第) |
| `--page`      | Page number                                      | 1          |
| `--format`    | Output format (json,csv,rss)                     | json       |

## Available Search Engines
google, duckduckgo, brave, bing など（SearXNG設定による）

## Tips
- siteフィルタ：`site:youtube.com たねちゃんねる` や `site:tanep.work TAL`
- フレーズ検索：`"TAL Tree-structured Assembly Language"`
- 動画狙い：`--category videos`
- 言語変更：`--language en` で英語結果も混ぜる

## Resources
scripts/search.sh - Main script
