#!/bin/bash
# recall - SemanticMemoryから記憶を検索するスクリプト

set -e

# .envファイルから環境変数を読み込む
load_env_file() {
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local current_dir="$script_dir"
    local env_file=""

    # 上に遡って.envを探す（最大10階層）
    for i in {1..10}; do
        if [[ -f "${current_dir}/.env" ]]; then
            env_file="${current_dir}/.env"
            break
        fi
        current_dir="$(dirname "$current_dir")"
        if [[ "$current_dir" == "/" ]]; then
            break
        fi
    done

    if [[ -f "${env_file}" ]]; then
        while IFS='=' read -r key value; do
            [[ "${key}" =~ ^#.*$ ]] && continue
            [[ -z "${key}" ]] && continue
            value=$(echo "${value}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//;s/^"//;s/"$//;s/^'"'"'//;s/'"'"'$//')
            [[ -z "${!key}" ]] && export "${key}=${value}"
        done < "${env_file}"
    fi
}

load_env_file

# デフォルト設定
API_URL="${SEMANTIC_MEMORY_API_URL:-http://localhost:6001/api}"
LIMIT="${SEMANTIC_MEMORY_RECALL_DEFAULT_LIMIT:-3}"
THRESHOLD="${SEMANTIC_MEMORY_RECALL_THRESHOLD:-0.7}"
QUERY=""

# ヘルプメッセージ
show_help() {
    cat << EOF
使用法: $(basename "$0") "検索クエリ" [オプション]

オプション:
    --limit N             取得する記憶の最大件数 (デフォルト: 3)
    --threshold N         類似度閾値 0.0-1.0 (デフォルト: 0.7)
    -h, --help            このヘルプを表示

環境変数:
    SEMANTIC_MEMORY_API_URL           SemanticMemory APIのURL
    SEMANTIC_MEMORY_RECALL_DEFAULT_LIMIT    デフォルト取得件数
    SEMANTIC_MEMORY_RECALL_THRESHOLD       デフォルト類似度閾値

例:
    $(basename "$0") "猫について"
    $(basename "$0") "WiFi" --limit 5
    $(basename "$0") "プロジェクト" --threshold 0.6
EOF
}

# 引数解析
QUERY="$1"
shift

while [[ $# -gt 0 ]]; do
    case $1 in
        --limit)
            LIMIT="$2"
            shift 2
            ;;
        --threshold)
            THRESHOLD="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "エラー: 不明なオプション: $1" >&2
            show_help
            exit 1
            ;;
    esac
done

# クエリチェック
if [[ -z "$QUERY" ]]; then
    echo "エラー: 検索クエリが指定されていません" >&2
    show_help
    exit 1
fi

# JSONペイロード構築
JSON=$(cat <<EOF
{
  "query": $(printf '%s' "$QUERY" | jq -Rs .),
  "limit": $LIMIT,
  "threshold": $THRESHOLD
}
EOF
)

# APIリクエスト
RESPONSE=$(curl -s -X POST "${API_URL}/mcp/recall_memory" \
    -H "Content-Type: application/json" \
    -d "$JSON")

# エラーチェック
if echo "$RESPONSE" | jq -e '.status == "success"' >/dev/null 2>&1; then
    COUNT=$(echo "$RESPONSE" | jq -r '.count')
    echo "${COUNT}件の記憶を見つけました" >&2
    echo "$RESPONSE"
elif echo "$RESPONSE" | jq -e '.error' >/dev/null 2>&1; then
    echo "エラー: $(echo "$RESPONSE" | jq -r '.error')" >&2
    exit 1
else
    echo "エラー: 不明なレスポンス" >&2
    echo "$RESPONSE" >&2
    exit 1
fi
