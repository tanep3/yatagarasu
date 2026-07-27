#!/usr/bin/env python3
import json
import sys
import unicodedata
from typing import Any


RESULT_LIMIT = 10


def bounded_text(value: Any, max_bytes: int) -> str:
    text = " ".join(str(value or "").split())
    text = "".join(
        character if unicodedata.category(character) != "Cc" else " "
        for character in text
    )
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def bounded_list(value: Any, limit: int, max_bytes: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [bounded_text(item, max_bytes) for item in value[:limit]]


def compact_result(value: Any) -> dict[str, str]:
    source = value if isinstance(value, dict) else {}
    return {
        "title": bounded_text(source.get("title"), 200),
        "url": bounded_text(source.get("url"), 512),
        "content": bounded_text(source.get("content"), 500),
        "publishedDate": bounded_text(source.get("publishedDate"), 64),
        "engine": bounded_text(source.get("engine"), 80),
    }


def main() -> int:
    source = json.load(sys.stdin)
    if not isinstance(source, dict):
        raise ValueError("SearXNG response must be a JSON object")

    source_results = source.get("results")
    results = source_results if isinstance(source_results, list) else []
    output = {
        "query": bounded_text(source.get("query"), 500),
        "number_of_results": source.get("number_of_results", len(results)),
        "returned_results": min(len(results), RESULT_LIMIT),
        "results": [
            compact_result(result) for result in results[:RESULT_LIMIT]
        ],
        "answers": bounded_list(source.get("answers"), 3, 200),
        "suggestions": bounded_list(source.get("suggestions"), 3, 200),
        "unresponsive_engines": bounded_list(
            source.get("unresponsive_engines"), 3, 100
        ),
    }
    json.dump(output, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
