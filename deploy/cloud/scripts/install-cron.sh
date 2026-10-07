#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_command crontab
load_env
validate_settings

[[ "$CLOUD_DIR" != *"'"* ]] || fail "部署路径不能包含单引号"
mkdir -p "$CLOUD_DIR/logs"
temp_cron="$(mktemp)"
trap 'rm -f -- "$temp_cron"' EXIT

crontab -l 2>/dev/null | grep -v '# xiquan-' > "$temp_cron" || true
{
  echo "15 3 * * * /usr/bin/env bash '$SCRIPT_DIR/backup.sh' >> '$CLOUD_DIR/logs/backup.log' 2>&1 # xiquan-backup"
  echo "45 3 * * * /usr/bin/env bash '$SCRIPT_DIR/renew-certificates.sh' >> '$CLOUD_DIR/logs/certbot.log' 2>&1 # xiquan-certbot"
} >> "$temp_cron"
crontab "$temp_cron"

echo "已安装定时任务：每天 03:15 备份数据库，03:45 检查证书续期。"
crontab -l | grep '# xiquan-'

