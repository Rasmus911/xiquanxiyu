#!/usr/bin/env bash
set -Eeuo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "请使用 sudo bash scripts/bootstrap-ubuntu.sh 运行。" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y unzip curl openssl ca-certificates cron

if ! docker compose version >/dev/null 2>&1; then
  # Follow Docker's official Ubuntu apt-repository installation method.
  # This branch is intended for a new ECS; existing working Docker is left untouched above.
  source /etc/os-release
  if [ "${ID:-}" != "ubuntu" ]; then
    echo "此脚本仅支持 Ubuntu；当前系统为 ${ID:-unknown}。" >&2
    exit 1
  fi

  apt-get remove -y docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc || true
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  ubuntu_codename="${UBUNTU_CODENAME:-$VERSION_CODENAME}"
  architecture="$(dpkg --print-architecture)"
  cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${ubuntu_codename}
Components: stable
Architectures: ${architecture}
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker
systemctl enable --now cron

login_user="${SUDO_USER:-}"
install -d -m 0750 /opt/xiquan-backups
if [ -n "$login_user" ] && [ "$login_user" != "root" ]; then
  usermod -aG docker "$login_user"
  chown "$login_user:$login_user" /opt/xiquan-backups
  echo "已把 $login_user 加入 docker 用户组；重新登录 SSH 后生效。"
fi

docker --version
docker compose version
echo "基础环境安装完成。阿里云安全组还需要单独放行 TCP 22、80、443。"
