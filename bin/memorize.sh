#!/bin/bash
# Keep automatic conversation memory on the same implementation as the AgentSkill.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../workspace/.codex/skills/memorize/scripts/memorize.sh" "$@"
