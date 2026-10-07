#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_command docker
require_command curl
load_env
validate_settings

echo "[1/6] 更新前备份数据库..."
bash "$SCRIPT_DIR/backup.sh"

echo "[2/6] 拉取生产基础镜像..."
compose pull postgres nginx

echo "[3/6] 构建新版 API；构建失败不会替换正在运行的旧容器..."
compose build --pull api

echo "[4/6] 重新生成 HTTPS/Nginx 配置..."
render_nginx https

echo "[5/6] 应用新版容器和数据库迁移..."
compose up -d --remove-orphans postgres api nginx

echo "[6/6] 检查线上 API..."
if ! wait_for_api "https://$API_DOMAIN/api/health" "" 48; then
  compose ps
  compose logs --tail=180 api nginx postgres
  fail "更新后健康检查失败，请根据上方日志排查"
fi

compose ps
echo "更新完成： https://$API_DOMAIN/api/health"
