#!/bin/bash
# Tapo TC70 カメラ PTZ 制御ラッパースクリプト
# uv経由でPythonスクリプトを実行します

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_DIR="/home/tane/dev/AI/yatagarasu/python"

# .envファイルから環境変数を読み込む
load_env_file() {
    local env_file="$(dirname "${BASH_SOURCE[0]}")/../../../../.env"
    if [[ -f "${env_file}" ]]; then
        while IFS='=' read -r key value; do
            # コメント行と空行をスキップ
            [[ "${key}" =~ ^#.*$ ]] && continue
            [[ -z "${key}" ]] && continue
            # 値から引用符を削除
            value=$(echo "${value}" | sed 's/^[[:space:]]*"//;s/"[[:space:]]*$//;s/^[[:space:]]*'"'"'//;s/[[:space:]]*'"'"'$//')
            # 環境変数をエクスポート
            export "${key}=${value}"
        done < "${env_file}"
    fi
}

# .envファイルを読み込む
load_env_file

# 環境変数のデフォルト設定（.envで設定されていない場合のみ）
export TAPO_HOST="${TAPO_HOST:-192.168.0.132}"
export TAPO_USER="${TAPO_USER:-admin}"

# uv経由でPythonスクリプトを実行
cd "${PYTHON_DIR}" && uv run python "${SCRIPT_DIR}/ptz_control" "$@"
