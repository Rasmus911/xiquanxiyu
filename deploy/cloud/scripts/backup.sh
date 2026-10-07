#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_command docker
load_env
validate_settings

BACKUP_DIR="${BACKUP_DIR:-/opt/xiquan-backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
case "$BACKUP_DIR" in
  ""|/|/bin|/boot|/etc|/home|/opt|/root|/usr|/var)
    fail "BACKUP_DIR 过于宽泛，请指定专用目录"
    ;;
esac
[[ "$BACKUP_RETENTION_DAYS" =~ ^[0-9]+$ ]] || fail "BACKUP_RETENTION_DAYS 必须是非负整数"

mkdir -p "$BACKUP_DIR"
timestamp="$(date '+%Y%m%d-%H%M%S')"
final_file="$BACKUP_DIR/xiquan-${timestamp}.dump"
temp_file="$BACKUP_DIR/.xiquan-${timestamp}.tmp"

compose up -d postgres >/dev/null
echo "正在备份 PostgreSQL 到 $final_file ..."
if ! compose exec -T postgres pg_dump \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --format=custom \
  --no-owner > "$temp_file"; then
  rm -f -- "$temp_file"
  fail "数据库备份失败"
fi

if ! compose exec -T postgres pg_restore --list < "$temp_file" >/dev/null; then
  rm -f -- "$temp_file"
  fail "备份文件校验失败"
fi

mv -- "$temp_file" "$final_file"
sha256sum "$final_file" > "${final_file}.sha256"

if [ "$BACKUP_RETENTION_DAYS" -gt 0 ]; then
  find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'xiquan-*.dump' -o -name 'xiquan-*.dump.sha256' \) \
    -mtime "+$BACKUP_RETENTION_DAYS" -delete
fi

echo "备份完成：$final_file"

