#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

require_command docker
load_env
validate_settings

compose run --rm certbot renew --webroot --webroot-path /var/www/certbot --quiet
compose exec nginx nginx -s reload
echo "证书续期检查完成。"

