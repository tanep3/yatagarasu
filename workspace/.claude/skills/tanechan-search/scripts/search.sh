#!/bin/bash
# Tanen Chan Search Script - Improved version
set -euo pipefail

# Defaults
SEARXNG_URL="${SEARXNG_URL:-http://localhost:8088}"
QUERY=""
CATEGORY="general"
LANGUAGE="ja"
FORMAT="json"
ENGINES=""
PAGE="1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_usage() {
    echo "Usage: $0 \"QUERY\" [--category CATEGORY] [--language LANG] [--engines ENG1,ENG2] [--page N] [--format FORMAT]"
    echo ""
    echo "Options:"
    echo "  QUERY              Search term (required, quotes if spaces)"
    echo "  --category C       general|it|images|videos|news|science (default: general)"
    echo "  --language L       ja|en|... (default: ja)"
    echo "  --engines E        google,duckduckgo,brave,... (comma-separated)"
    echo "  --page N           Page number (default: 1)"
    echo "  --format F         json|csv|rss (default: json)"
    echo ""
    echo "Examples:"
    echo "  $0 たねちゃんねる"
    echo "  $0 \"TAL ツリー構造\" --category it --engines google,duckduckgo"
    echo "  $0 \"たねちゃんねる 電子工作\" --category videos --page 2"
    exit 1
}

# Parse all arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --category) CATEGORY="$2"; shift 2 ;;
        --language) LANGUAGE="$2"; shift 2 ;;
        --engines)  ENGINES="$2";  shift 2 ;;
        --page)     PAGE="$2";     shift 2 ;;
        --format)   FORMAT="$2";   shift 2 ;;
        *) 
            if [[ -z "$QUERY" ]]; then
                QUERY="$1"
            else
                QUERY="$QUERY $1"  # スペース区切りで連結
            fi
            shift
            ;;
    esac
done

if [[ -z "$QUERY" ]]; then
    echo -e "${RED}Error: Query is required${NC}"
    print_usage
fi

# URL encode query (safe way)
ENCODED_QUERY=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote(' '.join(sys.argv[1:]).strip()))" "$QUERY")

# Build params
PARAMS="q=${ENCODED_QUERY}&format=${FORMAT}&language=${LANGUAGE}&category=${CATEGORY}&pageno=${PAGE}"

if [[ -n "$ENGINES" ]]; then
    PARAMS="${PARAMS}&engines=${ENGINES}"
fi

URL="${SEARXNG_URL}/search?${PARAMS}"

echo -e "${GREEN}Searching: $QUERY${NC}"
echo -e "Category: $CATEGORY | Lang: $LANGUAGE | Page: $PAGE | Engines: ${ENGINES:-default}"
echo -e "URL: $URL${NC}"

# Execute with timeout and fail on error
RESULT=$(curl -s --max-time 30 -f "$URL" || {
    echo -e "${RED}Error: SearXNG request failed (timeout or HTTP error)${NC}"
    exit 2
})

if [[ "$FORMAT" == "json" ]]; then
    # ログをstderrに出す
    echo -e "${GREEN}Searching: $$   QUERY   $${NC}" >&2
    echo -e "Category: $CATEGORY | Lang: $LANGUAGE | Page: $PAGE | Engines: ${ENGINES:-default}" >&2
    echo -e "URL: $$   URL   $${NC}" >&2

    # JSONだけstdoutに
    if ! echo "$RESULT" | python3 -m json.tool 2>/dev/null; then
        echo '{"error": "Invalid JSON from SearXNG", "raw": "'"$RESULT"'" }'
    fi
else
    echo "$RESULT"
fi
