#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_command docker
require_command curl
require_command sed
load_env
validate_settings
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 不可用"

echo "[1/7] 生成首次 HTTP 配置..."
render_nginx http

echo "[2/7] 拉取基础镜像..."
compose pull postgres nginx certbot

echo "[3/7] 构建溪泉 API 镜像..."
compose build --pull api

echo "[4/7] 启动 PostgreSQL、API 和临时 HTTP 服务..."
compose up -d postgres api nginx
if ! wait_for_api "http://127.0.0.1/api/health" "$API_DOMAIN" 48; then
  compose ps
  compose logs --tail=120 api nginx postgres
  fail "HTTP 健康检查失败"
fi

echo "[5/7] 为 $API_DOMAIN 申请 Let's Encrypt HTTPS 证书..."
compose run --rm certbot certonly \
  --webroot --webroot-path /var/www/certbot \
  --email "$ACME_EMAIL" --agree-tos --no-eff-email \
  --non-interactive --keep-until-expiring \
  -d "$API_DOMAIN"

echo "[6/7] 切换到 HTTPS 配置..."
render_nginx https
compose up -d --force-recreate nginx
if ! wait_for_api "https://$API_DOMAIN/api/health" "" 36; then
  compose ps
  compose logs --tail=120 nginx api
  fail "HTTPS 健康检查失败；请检查域名解析、安全组 80/443 和证书日志"
fi

echo "[7/7] 创建首份数据库备份..."
bash "$SCRIPT_DIR/backup.sh"

compose ps
echo
echo "首次部署完成。客户端 API 地址： https://$API_DOMAIN/api"
echo "建议继续运行：bash scripts/install-cron.sh"

