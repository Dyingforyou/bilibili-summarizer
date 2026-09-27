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

## 总结溯源

新生成的总结会在正文段落后显示“原文 Sxxxx”按钮。点击可查看该结论所依据的
真实转录片段，并可继续定位到完整转录稿中的对应位置。后端只保存和展示转录稿中
实际存在的证据片段，不使用 AI 重新生成的引文。旧记录可在“AI 总结”标题栏点击
“生成溯源”，直接使用已有转录稿重新生成，无需重新下载或转录视频。
