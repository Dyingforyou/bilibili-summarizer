#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

python3 -m venv venv
venv/bin/python -m pip install -r requirements-local.txt
ffmpeg_path="$(venv/bin/python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')"
ln -sfn "$ffmpeg_path" venv/bin/ffmpeg

if [[ ! -e .env ]]; then
    install -m 600 .env.example .env
fi

mkdir -p "$HOME/.config/systemd/user"
install -m 644 deploy/bilibili-summarizer-local.service "$HOME/.config/systemd/user/bilibili-summarizer.service"
systemctl --user daemon-reload
systemctl --user enable --now bilibili-summarizer.service
systemctl --user restart bilibili-summarizer.service
echo "本机地址：http://127.0.0.1:8002/"
