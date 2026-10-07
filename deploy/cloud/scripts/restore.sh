#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_command docker
load_env
validate_settings

[ "$#" -eq 1 ] || fail "用法：bash scripts/restore.sh /完整路径/xiquan-日期.dump"
RESTORE_FILE="$1"
[ -f "$RESTORE_FILE" ] || fail "备份文件不存在：$RESTORE_FILE"

if [ -f "${RESTORE_FILE}.sha256" ]; then
  (cd "$(dirname "$RESTORE_FILE")" && sha256sum --check "$(basename "${RESTORE_FILE}.sha256")")
fi

echo "警告：这会用以下备份覆盖当前营业数据库："
echo "  $RESTORE_FILE"
read -r -p "请输入 RESTORE 继续：" confirmation
[ "$confirmation" = "RESTORE" ] || fail "已取消恢复"

echo "先为当前数据库创建一份保护性备份..."
bash "$SCRIPT_DIR/backup.sh"

api_was_stopped=0
cleanup() {
  if [ "$api_was_stopped" -eq 1 ]; then
    compose start api >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

echo "暂停 API 写入并恢复数据库..."
compose stop api
api_was_stopped=1
compose exec -T postgres dropdb \
  --username "$POSTGRES_USER" \
  --maintenance-db postgres \
  --force "$POSTGRES_DB"
compose exec -T postgres createdb \
  --username "$POSTGRES_USER" \
  --maintenance-db postgres \
  --owner "$POSTGRES_USER" "$POSTGRES_DB"
compose exec -T postgres pg_restore \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --no-owner --exit-on-error < "$RESTORE_FILE"

compose start api
api_was_stopped=0
if ! wait_for_api "https://$API_DOMAIN/api/health" "" 48; then
  compose logs --tail=160 api
  fail "数据库已恢复，但 API 健康检查失败"
fi

trap - EXIT
echo "数据库恢复完成，API 已重新启动。"

