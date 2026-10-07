#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLOUD_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET="$CLOUD_DIR/.env"
EXAMPLE="$CLOUD_DIR/.env.example"

command -v openssl >/dev/null 2>&1 || { echo "错误：缺少 openssl" >&2; exit 1; }
[ -f "$EXAMPLE" ] || { echo "错误：未找到 $EXAMPLE" >&2; exit 1; }
[ ! -e "$TARGET" ] || { echo "$TARGET 已存在，未覆盖。"; exit 0; }

cp "$EXAMPLE" "$TARGET"
db_password="$(openssl rand -hex 24)"
secret_key="$(openssl rand -hex 32)"
jwt_secret="$(openssl rand -hex 32)"
bootstrap_token="$(openssl rand -hex 16)"

sed -i "s/CHANGE_ME_POSTGRES_PASSWORD/$db_password/" "$TARGET"
sed -i "s/CHANGE_ME_SECRET_KEY/$secret_key/" "$TARGET"
sed -i "s/CHANGE_ME_JWT_SECRET_KEY/$jwt_secret/" "$TARGET"
sed -i "s/CHANGE_ME_BOOTSTRAP_TOKEN/$bootstrap_token/" "$TARGET"
chmod 600 "$TARGET"

echo "已生成随机数据库密码和应用密钥：$TARGET"
echo "现在请编辑其中的 API_DOMAIN 和 ACME_EMAIL，然后运行 first-deploy.sh。"
