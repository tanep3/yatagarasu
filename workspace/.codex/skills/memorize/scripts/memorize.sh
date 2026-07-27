#!/bin/bash
# memorize - SemanticMemoryに記憶を保存するスクリプト

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
            if [[ -z "${!key:-}" ]]; then
                export "${key}=${value}"
            fi
        done < "${env_file}"
    fi
}

load_env_file

# デフォルト設定
API_URL="${SEMANTIC_MEMORY_API_URL:-http://localhost:6001/api}"
MAIN_TEXT=""
SUB_TEXT=""
SUMMARIZE="true"

# ヘルプメッセージ
show_help() {
    cat << EOF
使用法: $(basename "$0") "メインテキスト" [オプション]

オプション:
    --sub TEXT           サブテキスト（追加情報）
    --no-summarize       要約をスキップ
    -h, --help           このヘルプを表示

環境変数:
    SEMANTIC_MEMORY_API_URL    SemanticMemory APIのURL (デフォルト: http://localhost:6001/api)

例:
    $(basename "$0") "ユーザーは猫を飼っている"
    $(basename "$0") "WiFiパスワードはhogehoge" --sub "自宅のWiFi"
    $(basename "$0") "単純なメモ" --no-summarize
EOF
}

# ヘルプオプションを最初にチェック
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# 引数解析
MAIN_TEXT="$1"
shift

while [[ $# -gt 0 ]]; do
    case $1 in
        --sub)
            SUB_TEXT="$2"
            shift 2
            ;;
        --no-summarize)
            SUMMARIZE="false"
            shift
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

# メインテキストチェック
if [[ -z "$MAIN_TEXT" ]]; then
    echo "エラー: メインテキストが指定されていません" >&2
    show_help
    exit 1
fi

# JSONペイロード構築
if [[ -n "$SUB_TEXT" ]]; then
    JSON=$(cat <<EOF
{
  "main_text": $(printf '%s' "$MAIN_TEXT" | jq -Rs .),
  "sub_text": $(printf '%s' "$SUB_TEXT" | jq -Rs .),
  "summarize": $SUMMARIZE
}
EOF
)
else
    JSON=$(cat <<EOF
{
  "main_text": $(printf '%s' "$MAIN_TEXT" | jq -Rs .),
  "summarize": $SUMMARIZE
}
EOF
)
fi

# 同一の副作用要求を短時間に再実行しても、最初の保存IDへ収束させる。
DEDUP_WINDOW_SEC="${YATAGARASU_MEMORIZE_DEDUP_WINDOW_SEC:-60}"
if [[ ! "$DEDUP_WINDOW_SEC" =~ ^[0-9]+$ ]]; then
    echo "エラー: YATAGARASU_MEMORIZE_DEDUP_WINDOW_SEC must be a non-negative integer" >&2
    exit 1
fi
STATE_ROOT="${YATAGARASU_MEMORIZE_STATE_DIR:-${TMPDIR:-/tmp}/yatagarasu-memorize}"
umask 077
mkdir -p "$STATE_ROOT"
REQUEST_KEY=$(printf '%s\0%s' "$API_URL" "$JSON" | sha256sum | awk '{print $1}')
LOCK_FILE="$STATE_ROOT/${REQUEST_KEY}.lock"
CACHE_FILE="$STATE_ROOT/${REQUEST_KEY}.saved"
exec 9>"$LOCK_FILE"
flock 9

NOW=$(date +%s)
if [[ -f "$CACHE_FILE" ]]; then
    read -r SAVED_AT CACHED_ID < "$CACHE_FILE" || true
    if [[ "$SAVED_AT" =~ ^[0-9]+$ && "$CACHED_ID" =~ ^[0-9]+$ ]] \
        && (( NOW >= SAVED_AT && NOW - SAVED_AT <= DEDUP_WINDOW_SEC )); then
        RESPONSE=$(printf '{"id":%s,"status":"saved"}' "$CACHED_ID")
        echo "記憶は既に保存済みです (ID: $CACHED_ID)" >&2
        echo "$RESPONSE"
        exit 0
    fi
fi

# APIリクエスト
if ! RESPONSE=$(curl --silent --show-error --fail-with-body \
    --max-time "${SEMANTIC_MEMORY_TIMEOUT_SEC:-30}" \
    -X POST "${API_URL}/save" \
    -H "Content-Type: application/json" \
    -d "$JSON"); then
    echo "エラー: SemanticMemory API request failed" >&2
    exit 1
fi

# エラーチェック
if echo "$RESPONSE" | jq -e '.status == "saved"' >/dev/null 2>&1; then
    ID=$(echo "$RESPONSE" | jq -r '.id')
    if [[ ! "$ID" =~ ^[0-9]+$ ]]; then
        echo "エラー: SemanticMemory API returned an invalid saved ID" >&2
        exit 1
    fi
    CACHE_TMP=$(mktemp "${CACHE_FILE}.XXXXXX")
    printf '%s %s\n' "$NOW" "$ID" > "$CACHE_TMP"
    mv "$CACHE_TMP" "$CACHE_FILE"
    echo "記憶を保存しました (ID: $ID)" >&2
    echo "$RESPONSE"
elif echo "$RESPONSE" | jq -e '.error' >/dev/null 2>&1; then
    echo "エラー: $(echo "$RESPONSE" | jq -r '.error')" >&2
    exit 1
else
    echo "エラー:不明なレスポンス" >&2
    echo "$RESPONSE" >&2
    exit 1
fi
