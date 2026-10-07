#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$CLOUD_DIR/.env"
COMPOSE_FILE="$CLOUD_DIR/docker-compose.prod.yml"

fail() {
  echo "错误：$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "缺少命令：$1"
}

load_env() {
  [ -f "$ENV_FILE" ] || fail "未找到 $ENV_FILE。请先运行 bash scripts/prepare-env.sh，并填写域名和邮箱。"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
}

require_value() {
  local name="$1"
  local value="${!name:-}"
  [ -n "$value" ] || fail "$name 不能为空"
  [[ "$value" != CHANGE_ME_* ]] || fail "$name 仍是示例值，请修改 $ENV_FILE"
}

validate_settings() {
  require_value API_DOMAIN
  require_value ACME_EMAIL
  require_value POSTGRES_DB
  require_value POSTGRES_USER
  require_value POSTGRES_PASSWORD
  require_value SECRET_KEY
  require_value JWT_SECRET_KEY
  require_value BOOTSTRAP_TOKEN
  [[ "$API_DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || fail "API_DOMAIN 格式不正确"
  [[ "$ACME_EMAIL" == *@*.* ]] || fail "ACME_EMAIL 格式不正确"
  [[ "$POSTGRES_PASSWORD" =~ ^[A-Za-z0-9_-]+$ ]] || fail "POSTGRES_PASSWORD 只能使用字母、数字、下划线和短横线"
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

render_nginx() {
  local mode="$1"
  local template="$CLOUD_DIR/nginx/${mode}.conf.template"
  [ -f "$template" ] || fail "未找到 Nginx 模板：$template"
  sed "s/__API_DOMAIN__/${API_DOMAIN}/g" "$template" > "$CLOUD_DIR/nginx/active.conf"
}

wait_for_api() {
  local url="$1"
  local host_header="${2:-}"
  local attempts="${3:-36}"
  local i
  for ((i = 1; i <= attempts; i++)); do
    if [ -n "$host_header" ]; then
      if curl --silent --show-error --fail --max-time 5 -H "Host: $host_header" "$url" >/dev/null 2>&1; then
        return 0
      fi
    elif curl --silent --show-error --fail --max-time 5 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 5
  done
  return 1
}
