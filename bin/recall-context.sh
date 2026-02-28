#!/bin/bash
# recall-context - SemanticMemoryから過去の文脈と関連知識を取得するスクリプト

set -e

# .envファイルから環境変数を読み込む
load_env_file() {
    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local project_root="$(dirname "$script_dir")"
    local workspace="${YATAGARASU_CWD:-$project_root/workspace}"
    local env_file=""

    # workspace/.envを優先、なければプロジェクトルートの.env
    if [[ -f "${workspace}/.env" ]]; then
        env_file="${workspace}/.env"
    elif [[ -f "${project_root}/.env" ]]; then
        env_file="${project_root}/.env"
    fi

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
RECENT_LIMIT="${SEMANTIC_MEMORY_RECENT_LIMIT:-3}"
RECALL_LIMIT="${SEMANTIC_MEMORY_RECALL_LIMIT:-3}"
THRESHOLD="${SEMANTIC_MEMORY_RECALL_THRESHOLD:-0.7}"
QUERY=""

# ヘルプメッセージ
show_help() {
    cat << EOF
使用法: $(basename "$0") "検索クエリ" [オプション]

オプション:
    --recent-limit N       過去の文脈取得件数 (デフォルト: 3)
    --recall-limit N       関連知識取得件数 (デフォルト: 3)
    --threshold N          類似度閾値 0.0-1.0 (デフォルト: 0.7)
    -h, --help             このヘルプを表示

環境変数:
    SEMANTIC_MEMORY_API_URL        SemanticMemory APIのURL
    SEMANTIC_MEMORY_RECENT_LIMIT   過去の文脈デフォルト取得件数
    SEMANTIC_MEMORY_RECALL_LIMIT   関連知識デフォルト取得件数
    SEMANTIC_MEMORY_RECALL_THRESHOLD デフォルト類似度閾値

出力形式 (YAML):
    recent_history:       過去の文脈（時系列、最新順）
    related_knowledge:    関連知識（類似度順）

例:
    $(basename "$0") "猫について"
    $(basename "$0") "WiFi" --recent-limit 5 --recall-limit 5
EOF
}

# ヘルプオプションを最初にチェック
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# 引数解析
QUERY="$1"
shift

while [[ $# -gt 0 ]]; do
    case $1 in
        --recent-limit)
            RECENT_LIMIT="$2"
            shift 2
            ;;
        --recall-limit)
            RECALL_LIMIT="$2"
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
  "threshold": $THRESHOLD,
  "limit": $RECALL_LIMIT,
  "recent_limit": $RECENT_LIMIT
}
EOF
)

# APIリクエスト
RESPONSE=$(curl -s -X POST "${API_URL}/retrieve" \
    -H "Content-Type: application/json" \
    -d "$JSON")

# エラーチェック
if echo "$RESPONSE" | jq -e '.error' >/dev/null 2>&1; then
    echo "エラー: $(echo "$RESPONSE" | jq -r '.error')" >&2
    exit 1
fi

# YAML形式で出力（Claudeが理解しやすい形式）
echo "memory_context:"

# 過去の文脈（時系列）
echo "  recent_history: |"
RECENT_COUNT=$(echo "$RESPONSE" | jq -r '.recent | length' 2>/dev/null || echo "0")
if [[ "$RECENT_COUNT" -gt 0 ]]; then
    echo "$RESPONSE" | jq -r '.recent[] | "    - \(.main_text // "")"' 2>/dev/null || echo "    (なし)"
else
    echo "    (なし)"
fi

# 関連知識（類似度順）- semanticはdocumentフィールドを使用
echo "  related_knowledge: |"
SEMANTIC_COUNT=$(echo "$RESPONSE" | jq -r '.semantic | length' 2>/dev/null || echo "0")
if [[ "$SEMANTIC_COUNT" -gt 0 ]]; then
    echo "$RESPONSE" | jq -r '.semantic[] | "    - [\(.score | tonumber | . * 100 | floor // 100)] \(.document // "")"' 2>/dev/null || echo "    (なし)"
else
    echo "    (なし)"
fi

# デバッグ用にstderrに件数を出力
echo "${RECENT_COUNT}件の過去の文脈、${SEMANTIC_COUNT}件の関連知識を見つけました" >&2
