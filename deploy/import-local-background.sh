#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || ! -f "$1" ]]; then
    echo '用法：bash deploy/import-local-background.sh "/视频完整路径/视频.flv"' >&2
    exit 2
fi

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
video_path="$(realpath -- "$1")"
unit_name="bilibili-import-$(date +%Y%m%d%H%M%S)-$$"
cd "$project_dir"

if ! "$project_dir/venv/bin/python" -c 'from config import ASR_API_KEY, LLM_API_KEY; raise SystemExit(0 if ASR_API_KEY and LLM_API_KEY else 1)' 2>/dev/null; then
    echo '请先在项目 .env 填写 ASR_API_KEY 和 LLM_API_KEY' >&2
    exit 1
fi

systemd-run --user --collect --unit="$unit_name" \
    --property="WorkingDirectory=$project_dir" \
    --property="UMask=0077" \
    --setenv="PATH=$project_dir/venv/bin:/usr/local/bin:/usr/bin" \
    "$project_dir/venv/bin/python" "$project_dir/import_local.py" \
    --publish-to-history "$video_path"

echo "后台任务：$unit_name"
echo "查看进度：journalctl --user -u $unit_name -f"
