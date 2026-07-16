#!/bin/bash
# Tapo TC70 カメラ PTZ 制御ラッパースクリプト
# uv経由でPythonスクリプトを実行します

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/../../../../.." && pwd)"
PYTHON_DIR="${WORKSPACE_DIR}"

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
        # 親ディレクトリへ移動
        current_dir="$(dirname "$current_dir")"
        # ルートディレクトリに到達したら終了
        if [[ "$current_dir" == "/" ]]; then
            break
        fi
    done

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
uv run "${SCRIPT_DIR}/ptz_control" "$@"
