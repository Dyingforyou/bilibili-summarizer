#!/bin/bash
# 视频总结助手 - 启动脚本
set -euo pipefail

sudo systemctl daemon-reload
sudo systemctl enable --now bilibili-summarizer.service
sudo systemctl restart bilibili-summarizer.service
echo "视频总结助手服务状态: $(systemctl is-active bilibili-summarizer.service)"
