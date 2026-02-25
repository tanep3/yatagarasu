#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "requests>=2.28",
#   "beautifulsoup4>=4.12",
# ]
# ///
# -*- coding: utf-8 -*-
"""
tanen-chan-fetch: Fetch and process webpage content
Claude Code / Clawdbot向け。JSON出力でAIが扱いやすい。
GitHub blobページ対応強化 + raw URL自動変換
"""

import sys
import json
import argparse
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urlunparse

def print_usage(exit_code=1):
    """Usageを表示して終了"""
    print("""
Usage: ./fetch.sh <URL> [options]

Arguments:
  URL                  取得したいページのURL（必須）

Options:
  --summarize TEXT     要約指示（例: "TALの進捗を日本語で要約"）
  --extract TEXT       抽出指示（例: "タイトルと更新日時だけ"）
  --fulltext           クリーンな全文テキストを返す（要約なし）
  --help, -h           このヘルプを表示

Examples:
  ./fetch.sh "https://tanep.work/tal-intro"
  ./fetch.sh "https://github.com/tanep3/TAL/blob/main/README_jp.md" --fulltext

GitHub blobページは自動でraw URLに変換します。
エラー時はJSON形式で {"error": "メッセージ"} を出力します。
""")
    sys.exit(exit_code)

def convert_to_raw_github_url(url):
    """GitHub blobページをraw URLに変換（修正版）"""
    parsed = urlparse(url)
    if 'github.com' in parsed.netloc and '/blob/' in parsed.path:
        # /owner/repo/blob/branch/file → /owner/repo/branch/file
        new_path = parsed.path.replace('/blob/', '/', 1)  # 最初の /blob/ のみ置換
        return urlunparse((
            parsed.scheme or 'https',
            'raw.githubusercontent.com',
            new_path,
            parsed.params,
            parsed.query,
            parsed.fragment
        ))
    return url

def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("url", nargs="?", help="Target URL")
    parser.add_argument("--summarize", help="Summarization instruction")
    parser.add_argument("--extract", help="Extraction instruction")
    parser.add_argument("--fulltext", action="store_true", help="Return full cleaned text")
    parser.add_argument("-h", "--help", action="store_true", help="Show this help")

    args = parser.parse_args()

    if args.help or not args.url:
        print_usage(0 if args.help else 1)

    original_url = args.url
    url = convert_to_raw_github_url(original_url)  # GitHub blob → raw 自動変換

    result = {
        "url": original_url,
        "fetched_url": url,  # 実際に取得したURLを表示（変換された場合にわかる）
        "title": "",
        "meta_description": "",
        "main_content": "",
        "summary": "",
        "extracted": "",
        "error": None
    }

    try:
        headers = {"User-Agent": "TanenChan-Fetch/1.0 (compatible; Claude Code skill)"}
        resp = requests.get(url, timeout=15, headers=headers, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException as e:
        result["error"] = f"Failed to fetch URL: {str(e)}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(2)

    content_type = resp.headers.get('content-type', '').lower()

    # raw GitHubの場合（text/plainなど）はそのまま本文として扱う
    if 'text/plain' in content_type or 'markdown' in content_type or url.endswith(('.md', '.txt')):
        cleaned_text = resp.text.strip()
        lines = [line for line in cleaned_text.splitlines() if line.strip()]
        result["main_content"] = "\n".join(lines)
        result["title"] = "Raw content from " + urlparse(url).path.split('/')[-1]
    else:
        # HTMLの場合（通常のウェブページ）
        try:
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            result["error"] = f"Failed to parse HTML: {str(e)}"
            print(json.dumps(result, ensure_ascii=False, indent=2))
            sys.exit(3)

        # タイトル
        if soup.title:
            result["title"] = soup.title.string.strip()

        # meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            result["meta_description"] = meta_desc["content"].strip()

        # GitHub blobページ特化抽出（raw変換したので基本ここは通らないが念のため残す）
        main_content = ""
        markdown_body = soup.find("article", class_="markdown-body")
        if markdown_body:
            for tag in markdown_body.find_all(["div", "span", "a"], class_=["highlight", "react-code-text", "file-header", "gh-header", "notification", "js-flash", "js-socket-channel", "octicon"]):
                tag.decompose()
            main_content = markdown_body.get_text(separator="\n", strip=True)
        else:
            for unwanted in soup(["script", "style", "header", "footer", "nav", "aside", "form"]):
                unwanted.decompose()
            main_content = soup.get_text(separator="\n", strip=True)

        lines = [line.strip() for line in main_content.splitlines() if line.strip()]
        cleaned_text = "\n".join(lines)

        if len(cleaned_text) > 15000:
            cleaned_text = cleaned_text[:15000] + "\n... (truncated)"

        result["main_content"] = cleaned_text

    # モード処理
    if args.summarize:
        preview = "\n".join(result["main_content"].splitlines()[:15]) if result["main_content"] else ""
        result["summary"] = f"{preview}\n... (要約指示: {args.summarize})"
    elif args.extract:
        result["extracted"] = f"抽出指示: {args.extract}\n{result['main_content'][:2000]}..."
    elif args.fulltext:
        pass  # 既にmain_contentにフルが入ってる
    else:
        result["summary"] = "\n".join(result["main_content"].splitlines()[:8]) + "..." if result["main_content"] else ""

    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
