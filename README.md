# 视频总结助手

支持 B站和微信视频号分享链接，处理流程统一为：视频信息 → 字幕或音频 → ASR → AI 总结。

## 支持链接

- `https://www.bilibili.com/video/BV...`
- `https://www.bilibili.com/video/BV...?p=2`（支持分P，缺省为P1）
- `https://b23.tv/...`
- `https://weixin.qq.com/sph/...`
- `https://channels.weixin.qq.com/...`

视频号公开链接使用 yt-dlp 通用网页提取。若视频要求登录，请将浏览器导出的 Netscape
Cookie 文件保存为 `data/wechat_cookies.txt`；此文件已被 `.gitignore` 排除。

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
chmod 600 .env
# 编辑 .env，填写 ASR_API_KEY 和 LLM_API_KEY

./start.sh
curl http://127.0.0.1:8002/api/list
```

生产环境使用系统级 `bilibili-summarizer.service`。参考服务文件位于
`deploy/bilibili-summarizer.service`；`.env`、Cookie、数据库、音频和日志均不得提交。

分P视频请保留链接中的 `p` 参数，例如：

```text
https://www.bilibili.com/video/BV1aqh36vEnK/?p=2
```

程序会使用P2对应的 `cid` 获取字幕或下载音频；同一BV号的不同分P会作为不同任务处理。

## 本机大视频文件

先在这台机器上安装并启动本地服务（无需 sudo）：

```bash
cd /home/admin/bilibili-summarizer
bash deploy/setup-local.sh
```

打开 `http://127.0.0.1:8002/`。服务只监听本机回环地址；本机访问不经过云服务器。脚本会创建 `.env`，请在其中填写 `ASR_API_KEY` 和 `LLM_API_KEY`，然后运行 `systemctl --user restart bilibili-summarizer.service`。无须在系统中安装 ffmpeg；本地依赖会提供它。

如果要从自己的其他设备访问，参见 [外部设备 SSH 访问说明](deploy/remote-access.md)。ECS 只充当加密隧道中继，视频、数据库和处理程序仍在本机。

同一 `192.168.1.0/24` 局域网内的 Windows 电脑（目前以太网 `192.168.1.105`，WLAN `192.168.1.108`）可直接访问 `http://192.168.1.107:8002/`。局域网代理只接受这两个 Windows 地址；它把请求转给本机的 `127.0.0.1:8002`，所以原有本机入口和 ECS 隧道继续可用。先启动用户服务：

```bash
install -m 644 deploy/bilibili-summarizer-lan.service ~/.config/systemd/user/bilibili-summarizer-lan.service
systemctl --user daemon-reload
systemctl --user enable --now bilibili-summarizer-lan.service
```

Linux 的 firewalld 还需仅对上述两个 Windows IP 放行端口。在 **Linux 机器的终端**执行 `sudo bash deploy/allow-windows-lan.sh`，自行在终端输入 sudo 密码，不要在聊天里发送密码。之后在 Windows 浏览器打开 `http://192.168.1.107:8002/`。若 Windows 的 DHCP 地址变化，需同步修改代理服务和防火墙白名单。

如果视频已经在这台 Linux 服务器上，直接在网页的“服务器上的视频文件”一栏输入完整路径（例如 `/home/admin/videos/视频.flv`），点击“提交本地视频”。这里填写的是 **服务器路径**，不是 Windows 电脑的 `C:\...` 路径。网页只提交路径文本，处理程序在服务器本地读取视频；任务进度和结果会显示在页面与历史记录中。此入口仅由本机服务配置启用，云端部署默认禁用。

也可继续从命令行导入。要在网页历史记录中查看结果，添加 `--publish-to-history`：

```bash
cd /home/admin/bilibili-summarizer
. venv/bin/activate
python import_local.py "/视频所在目录/视频.mp4"
python import_local.py --publish-to-history "/视频所在目录/视频.mp4"
```

命令行处理长视频可在后台运行，这样关闭终端后任务仍会继续：

```bash
bash deploy/import-local-background.sh "/视频所在目录/视频.mp4"
```

脚本会显示任务名。用 `journalctl --user -u <任务名> -f` 查看日志，完成后在本地页面点击“刷新历史记录”。

程序从原视频直接提取约 10 分钟一个的低码率音频片段，逐段转写后对长转录稿分段总结。源视频不会复制进项目目录，也不会在数据库中保存其绝对路径。如果只想生成本机私有文件，运行第一条前台命令；要在网页历史记录中查看，使用网页提交、第二条前台命令或后台脚本。请只运行一种。网页提交会启动独立的 Linux 用户服务；关闭浏览器或重启网页服务不会中断已经开始的视频任务。处理时间和 ASR 费用主要取决于**视频时长**，而非 3GB 文件大小。原视频仍留在本机，但音频分片会发送给 ASR 服务，转录文字会发送给 LLM 服务。

若视频实际是 B 站链接，先直接提交链接：有字幕时无需下载视频或 ASR；无字幕时会下载音频再转写。微信视频号链接仍走现有链接流程。

## 总结溯源

新生成的总结会在正文段落后显示“原文 Sxxxx”按钮。点击可查看该结论所依据的
真实转录片段，并可继续定位到完整转录稿中的对应位置。后端只保存和展示转录稿中
实际存在的证据片段，不使用 AI 重新生成的引文。旧记录可在“AI 总结”标题栏点击
“生成溯源”，直接使用已有转录稿重新生成，无需重新下载或转录视频。
