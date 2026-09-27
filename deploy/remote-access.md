# 从自己的设备安全访问本机视频总结助手

项目运行在 `/home/admin/bilibili-summarizer`，只监听 `127.0.0.1:8002`。本机用户服务把该端口通过 SSH 反向转发到 ECS 的 `127.0.0.1:28002`；此端口本身不面向公网。

本机隧道可用 `bash deploy/setup-remote-tunnel.sh` 安装或恢复，用 `systemctl --user status bilibili-summarizer-tunnel.service` 查看状态。

已在 ECS 创建只允许转发到该端口的 `video-viewer` SSH 身份，不提供普通命令行。配套私钥仅保存在本机：

```text
/home/admin/.config/bilibili-summarizer/viewer_ed25519
```

将此私钥通过安全方式复制到你自己的外部设备，并限制文件权限。该文件不能提交到 Git，也不要发在聊天或公开渠道。在外部设备运行：

```bash
chmod 600 ./viewer_ed25519
ssh -i ./viewer_ed25519 -o IdentitiesOnly=yes -o ExitOnForwardFailure=yes \
  -N -L 127.0.0.1:18002:127.0.0.1:28002 \
  video-viewer@47.103.65.182
```

保持 SSH 命令运行，在**同一外部设备**的浏览器打开 `http://127.0.0.1:18002/`。页面虽显示本机 HTTP 地址，设备到 ECS 及 ECS 到本机的两段公网链路都走 SSH 加密。关闭 SSH 命令后外部设备入口随即关闭。本机视频文件仍由本机导入，网页入口不会传输整个原视频。
