#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit_file="$project_dir/deploy/bilibili-summarizer-tunnel.service"
target_dir="$HOME/.config/systemd/user"

if [[ ! -r /home/admin/.ssh/id_ed25519_aliyun ]]; then
    echo '缺少现有 ECS SSH 密钥，无法建立本机到 ECS 的隧道' >&2
    exit 1
fi

mkdir -p "$target_dir"
install -m 644 "$unit_file" "$target_dir/bilibili-summarizer-tunnel.service"
systemctl --user daemon-reload
systemctl --user enable --now bilibili-summarizer-tunnel.service
systemctl --user restart bilibili-summarizer-tunnel.service
systemctl --user is-active bilibili-summarizer-tunnel.service
