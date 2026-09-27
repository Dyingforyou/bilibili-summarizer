"""B站总结助手 - 视频处理（B站原生API + yt-dlp备选）"""
import os
import re
import json
import time
import hashlib
import subprocess
import shutil
import secrets
import requests
from urllib.parse import parse_qs, urlencode, urlparse
from config import AUDIO_DIR, COOKIE_FILE, WECHAT_COOKIE_FILE, YUANBAO_COOKIE_FILE

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
YTDLP_BIN = shutil.which("yt-dlp") or "/home/admin/.local/bin/yt-dlp"

WECHAT_HOSTS = ("weixin.qq.com", "channels.weixin.qq.com", "weixin110.qq.com")
_wechat_cache = {}

def _load_yuanbao_cookie() -> str:
    if not os.path.exists(YUANBAO_COOKIE_FILE):
        return ""
    return open(YUANBAO_COOKIE_FILE, encoding="utf-8").read().strip()

def _parse_wechat_via_yuanbao(url: str) -> dict:
    """Resolve a Channels share URL through Tencent Yuanbao and WeChat APIs."""
    if url in _wechat_cache and time.time() - _wechat_cache[url][0] < 1800:
        return _wechat_cache[url][1]
    cookie = _load_yuanbao_cookie()
    if not cookie:
        raise RuntimeError("缺少 yuanbaocookie.txt，请先登录腾讯元宝并导出 Cookie")
    yheaders = {
        "accept": "application/json, text/plain, */*", "content-type": "application/json",
        "origin": "https://yuanbao.tencent.com", "referer": "https://yuanbao.tencent.com/",
        "user-agent": UA, "cookie": cookie, "x-requested-with": "XMLHttpRequest", "x-source": "web",
    }
    parsed = requests.post(
        "https://yuanbao.tencent.com/api/weixin/get_parse_result", headers=yheaders,
        json={"type": "video_channel_url", "url": url, "scene": 1}, timeout=30)
    parsed.raise_for_status()
    pdata = (parsed.json().get("data") or {})
    if not pdata.get("wx_export_id"):
        raise RuntimeError("腾讯元宝无法解析该视频号链接，请更新 yuanbaocookie.txt")
    playable = urlparse(pdata.get("playable_url", ""))
    params = __import__("urllib.parse", fromlist=["parse_qs"]).parse_qs(playable.query)
    export_id = params.get("eid", [pdata["wx_export_id"]])[0]
    token = params.get("token", [""])[0]
    rid = f"{int(time.time()):x}-{secrets.token_hex(4)}"
    api = ("https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"
           f"?_rid={rid}&_pageUrl=https:%2F%2Fchannels.weixin.qq.com%2Ffinder-preview%2Fpages%2Ffeed")
    referer = ("https://channels.weixin.qq.com/finder-preview/pages/feed?token="
               + __import__("urllib.parse", fromlist=["quote"]).quote(token)
               + "&eid=" + __import__("urllib.parse", fromlist=["quote"]).quote(export_id))
    response = requests.post(api, headers={"User-Agent": UA, "Content-Type": "application/json",
        "Referer": referer, "Origin": "https://channels.weixin.qq.com"},
        json={"baseReq": {"generalToken": token}, "exportId": export_id}, timeout=30)
    response.raise_for_status()
    api_data = response.json()
    if api_data.get("errCode") != 0:
        raise RuntimeError("微信视频号接口错误: " + str(api_data.get("errMsg", "未知错误")))
    data = api_data.get("data") or {}
    feed = data.get("feedInfo") or {}
    author = data.get("authorInfo") or {}
    video_url = (feed.get("videoUrl") or (feed.get("h264VideoInfo") or {}).get("videoUrl")
                 or (feed.get("h265VideoInfo") or {}).get("videoUrl"))
    if not video_url:
        raise RuntimeError("微信接口未返回可下载的视频流")
    result = {"video_url": video_url, "feed": feed, "author": author,
              "export_id": export_id, "yuanbao": pdata}
    _wechat_cache[url] = (time.time(), result)
    return result

def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "b23.tv" or host.endswith("bilibili.com"):
        return "bilibili"
    if any(host == h or host.endswith("." + h) for h in WECHAT_HOSTS):
        return "wechat_channels"
    return ""

def _ytdlp_json(url: str, cookie_file: str | None = None) -> dict:
    cmd = [YTDLP_BIN, "--dump-single-json", "--no-playlist", "--no-check-certificates", "--user-agent", UA]
    if cookie_file and os.path.exists(cookie_file):
        cmd += ["--cookies", cookie_file]
    cmd.append(url)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        hint = "；如该视频需登录，请导出 Netscape Cookie 到 data/wechat_cookies.txt"
        raise RuntimeError(f"无法解析微信视频号分享链接: {result.stderr[-500:]}{hint}")
    return json.loads(result.stdout)

def get_wechat_video_info(url: str) -> dict:
    data = _parse_wechat_via_yuanbao(url)
    feed, author, yuanbao = data["feed"], data["author"], data["yuanbao"]
    video_id = data["export_id"]
    return {
        "bvid": "", "video_id": video_id,
        "title": feed.get("description") or yuanbao.get("desc") or "微信视频号视频",
        "cover_url": feed.get("coverUrl") or yuanbao.get("cover_url") or "",
        "author": author.get("nickname") or yuanbao.get("author") or "视频号作者",
        "duration": int((feed.get("h264VideoInfo") or {}).get("duration") or 0),
    }

def download_wechat_audio(url: str, task_id: str) -> str:
    output_path = os.path.join(AUDIO_DIR, f"{task_id}.mp3")
    raw_path = output_path + ".raw.mp4"
    data = _parse_wechat_via_yuanbao(url)
    try:
        with requests.get(data["video_url"], headers={"User-Agent": UA, "Referer": "https://channels.weixin.qq.com/"}, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(raw_path, "wb") as f:
                for chunk in r.iter_content(1024 * 256):
                    if chunk: f.write(chunk)
        result = subprocess.run(["ffmpeg", "-y", "-i", raw_path, "-vn", "-acodec", "libmp3lame", "-b:a", "64k", output_path], capture_output=True, timeout=900)
        if result.returncode != 0 or not os.path.exists(output_path):
            raise RuntimeError("视频号音频转码失败: " + result.stderr.decode(errors="ignore")[-500:])
    finally:
        if os.path.exists(raw_path): os.remove(raw_path)
    return output_path

# ────────────── WBI 签名 ──────────────
# B站 wbi 混表（固定顺序）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

_wbi_cache = {"keys": None, "ts": 0}


def _get_mixin_key(raw_key: str) -> str:
    """根据混表对 raw_key (img_key+sub_key) 进行混排，取前 32 位"""
    return "".join(raw_key[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def _get_wbi_keys(session: requests.Session) -> tuple:
    """从 nav 接口获取 img_key 和 sub_key，带 30 分钟缓存"""
    now = time.time()
    if _wbi_cache["keys"] and now - _wbi_cache["ts"] < 1800:
        return _wbi_cache["keys"]

    r = session.get("https://api.bilibili.com/x/web-interface/nav", timeout=10)
    data = r.json().get("data", {})
    wbi_img = data.get("wbi_img", {})
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")

    # 从 URL 中提取 key（去掉路径和扩展名）
    img_key = img_url.rsplit("/", 1)[-1].split(".")[0] if img_url else ""
    sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0] if sub_url else ""

    keys = (img_key, sub_key)
    _wbi_cache["keys"] = keys
    _wbi_cache["ts"] = now
    return keys


def _sign_wbi(params: dict, session: requests.Session) -> dict:
    """对请求参数进行 wbi 签名，返回带 w_rid 和 wts 的新参数"""
    img_key, sub_key = _get_wbi_keys(session)
    if not img_key or not sub_key:
        return params  # 无法获取 key，返回原始参数

    mixin_key = _get_mixin_key(img_key + sub_key)
    curr_time = round(time.time())
    params["wts"] = curr_time

    # 按 key 排序，过滤非法字符
    params = dict(sorted(params.items()))
    params = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in params.items()
    }
    query = urlencode(params)
    wbi_sign = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = wbi_sign
    return params


def _load_fixed_cookies(session: requests.Session) -> bool:
    """从固定cookie文件加载B站登录态。成功返回True"""
    if not os.path.exists(COOKIE_FILE):
        return False
    try:
        with open(COOKIE_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _flag, path, _secure, _exp, name, value = parts[:7]
                session.cookies.set(name, value, domain=domain, path=path)
        print(f"[cookie] 已加载固定cookie: {COOKIE_FILE}")
        return True
    except Exception as e:
        print(f"[cookie] 加载固定cookie失败: {e}")
        return False


def _make_session():
    """创建带B站cookie的session，优先使用固定cookie文件"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
    })
    # 优先加载固定cookie文件（浏览器导出的登录态）
    if _load_fixed_cookies(s):
        return s
    # 回退：现获取匿名cookie
    s.get("https://www.bilibili.com/", timeout=10)
    try:
        r = s.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=10)
        spi = r.json().get("data", {})
        if spi.get("b_3"):
            s.cookies.set("buvid3", spi["b_3"], domain=".bilibili.com")
        if spi.get("b_4"):
            s.cookies.set("buvid4", spi["b_4"], domain=".bilibili.com")
    except Exception:
        pass
    return s


def extract_bvid(url: str) -> str:
    """从B站URL提取BV号，b23.tv 短链会先解析重定向。"""
    if (urlparse(url).hostname or "").lower() == "b23.tv":
        url = _resolve_short_url(url)
    m = re.search(r'/(BV[\w]+)', url)
    return m.group(1) if m else ""


def extract_page_number(url: str) -> int:
    """Extract the one-based Bilibili part number from a URL (defaults to P1)."""
    url = _resolve_short_url(url)
    raw_page = parse_qs(urlparse(url).query).get("p", ["1"])[0]
    try:
        page = int(raw_page)
    except (TypeError, ValueError):
        raise RuntimeError(f"无效的分P参数: p={raw_page}")
    if page < 1:
        raise RuntimeError(f"无效的分P参数: p={raw_page}")
    return page


def _select_video_page(vdata: dict, page_number: int) -> dict:
    """Select a page entry from the view API response."""
    pages = vdata.get("pages") or []
    if not pages:
        if page_number != 1:
            raise RuntimeError("该视频没有指定的分P")
        return {
            "page": 1,
            "cid": vdata.get("cid", 0),
            "part": vdata.get("title", ""),
            "duration": vdata.get("duration", 0),
        }

    # Normally page numbers are contiguous, but prefer the explicit page field.
    selected = next((item for item in pages if item.get("page") == page_number), None)
    if selected is None and page_number <= len(pages):
        selected = pages[page_number - 1]
    if selected is None:
        raise RuntimeError(f"该视频只有 {len(pages)} P，无法选择 P{page_number}")
    return selected


def _resolve_short_url(url: str) -> str:
    """解析b23.tv短链接"""
    if "b23.tv" in url:
        try:
            r = requests.head(url, allow_redirects=True, timeout=10,
                              headers={"User-Agent": UA})
            return r.url
        except Exception:
            pass
    return url


def get_video_info(url: str) -> dict:
    """通过B站API获取视频元信息"""
    url = _resolve_short_url(url)
    bvid = extract_bvid(url)
    if not bvid:
        raise RuntimeError(f"无法从URL中提取BV号: {url}")

    session = _make_session()

    # 获取视频基本信息
    api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    r = session.get(api_url, timeout=15)
    data = r.json()

    if data.get("code") != 0:
        raise RuntimeError(f"B站API错误: {data.get('message', '未知错误')}")

    vdata = data["data"]
    page_number = extract_page_number(url)
    selected_page = _select_video_page(vdata, page_number)
    base_title = vdata.get("title", "未知标题")
    part_title = selected_page.get("part", "")
    title = base_title
    if len(vdata.get("pages") or []) > 1:
        title = f"{base_title} [P{page_number}]"
        if part_title and part_title != base_title:
            title += f" {part_title}"
    return {
        "bvid": bvid,
        "title": title,
        "cover_url": vdata.get("pic", ""),
        "author": vdata.get("owner", {}).get("name", "未知作者"),
        "duration": int(selected_page.get("duration", 0) or 0),
        "_cid": selected_page.get("cid", 0),  # 当前分P的 cid
        "_aid": vdata.get("aid", 0),
        "_page": page_number,
    }


def get_subtitles(bvid: str, cid: int, aid: int) -> str | None:
    """尝试获取B站视频字幕，成功返回纯文本，无字幕返回None"""
    try:
        session = _make_session()
        # 通过弹幕视图API获取字幕列表（无需登录）
        dm_url = f"https://api.bilibili.com/x/v2/dm/view?type=1&oid={cid}&pid={aid}"
        r = session.get(dm_url, timeout=10)
        data = r.json()
        if data.get("code") != 0:
            return None

        subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subtitles:
            return None

        # 语言优先级：zh-CN > zh-Hans > zh-* > 其他
        def lang_priority(lan: str) -> int:
            if lan == "zh-CN": return 0
            if lan == "zh-Hans": return 1
            if lan.startswith("zh"): return 2
            return 10

        subtitles.sort(key=lambda s: lang_priority(s.get("lan", "")))
        chosen = subtitles[0]
        sub_url = chosen.get("subtitle_url", "")
        if not sub_url:
            return None

        # 修复协议
        if sub_url.startswith("http://"):
            sub_url = "https://" + sub_url[7:]

        # 下载字幕JSON
        r2 = session.get(sub_url, timeout=15)
        sub_json = r2.json()
        body = sub_json.get("body", [])
        if not body:
            return None

        # 提取文本
        text = "\n".join(item.get("content", "") for item in body if item.get("content"))
        return text if text.strip() else None

    except Exception as e:
        print(f"获取字幕失败: {e}")
        return None


def download_audio(url: str, task_id: str) -> str:
    """下载视频音频为MP3"""
    output_path = os.path.join(AUDIO_DIR, f"{task_id}.mp3")
    url = _resolve_short_url(url)

    # 先尝试用B站API直接下载
    try:
        return _download_via_api(url, task_id, output_path)
    except Exception as e:
        print(f"API下载失败，尝试yt-dlp: {e}")

    # 备选：yt-dlp
    return _download_via_ytdlp(url, task_id, output_path)


def _download_via_api(url: str, task_id: str, output_path: str) -> str:
    """通过B站API下载音频流"""
    bvid = extract_bvid(url)
    if not bvid:
        raise RuntimeError("无法提取BV号")

    session = _make_session()

    # 获取当前分P的 cid
    r = session.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", timeout=15)
    vdata = r.json().get("data", {})
    page_number = extract_page_number(url)
    selected_page = _select_video_page(vdata, page_number)
    cid = selected_page.get("cid")
    aid = vdata.get("aid")
    if not cid:
        raise RuntimeError("获取cid失败")

    # 获取播放地址 — 带 wbi 签名
    # 先尝试 DASH (fnval=16)，失败回退 FLV (fnval=0)
    audio_url = None
    raw_ext = ".m4a"
    for fnval in (16, 0):
        play_params = {
            "bvid": bvid,
            "cid": cid,
            "qn": 64,
            "fnval": fnval,
            "fourk": 1,
        }
        signed_params = _sign_wbi(play_params, session)
        play_url = f"https://api.bilibili.com/x/player/playurl?{urlencode(signed_params)}"
        r = session.get(play_url, timeout=15)
        pdata = r.json()

        if pdata.get("code") != 0:
            continue

        data = pdata.get("data", {})

        # 优先 DASH 音频轨（体积小，纯音频）
        dash = data.get("dash") or {}
        audios = dash.get("audio", [])
        if audios:
            best_audio = max(audios, key=lambda a: a.get("bandwidth", 0))
            audio_url = best_audio.get("baseUrl") or best_audio.get("base_url")
            raw_ext = ".m4a"
            print(f"[API] 使用 DASH 音频轨 (bandwidth={best_audio.get('bandwidth')})")
            break

        # 回退 FLV (durl) — 包含音视频，需要 ffmpeg 抽音
        durls = data.get("durl", [])
        if durls:
            audio_url = durls[0].get("url")
            raw_ext = ".flv"
            print(f"[API] DASH 无音频轨，回退到 FLV (size={durls[0].get('size')})")
            break

    if not audio_url:
        raise RuntimeError("未找到可用的音频源（DASH/FLV 均无数据）")

    # 先保存为原始格式
    raw_path = output_path + ".raw" + raw_ext
    try:
        # 下载（FLV 体积大，超时设长）
        dl_timeout = 600 if raw_ext == ".flv" else 120
        r = session.get(audio_url, stream=True, timeout=dl_timeout,
                        headers={"Referer": "https://www.bilibili.com"})
        if r.status_code != 200:
            raise RuntimeError(f"音频下载失败: HTTP {r.status_code}")

        with open(raw_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

        # 根据源文件时长动态计算 ffmpeg 超时：至少 300s，或时长的 2 倍
        raw_duration = get_audio_duration(raw_path)
        ffmpeg_timeout = max(300, int(raw_duration * 2)) if raw_duration > 0 else 600
        print(f"[ffmpeg] raw_duration={raw_duration:.0f}s, timeout={ffmpeg_timeout}s, src={raw_ext}")

        # 用ffmpeg转为mp3
        # FLV 源需要 -vn 跳过视频流；M4A 直接转码
        cmd = [
            "ffmpeg", "-y", "-i", raw_path,
            "-vn",  # 丢弃视频流（FLV 才有视频，M4A 无影响）
            "-acodec", "libmp3lame", "-b:a", "64k",
            output_path
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=ffmpeg_timeout)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"ffmpeg转码超时（{ffmpeg_timeout}s，音频时长{raw_duration:.0f}s）"
            )

        if not os.path.exists(output_path):
            raise RuntimeError("MP3转换失败")
    finally:
        # 无论成功失败都清理原始文件
        if os.path.exists(raw_path):
            os.remove(raw_path)

    return output_path


def _download_via_ytdlp(url: str, task_id: str, output_path: str) -> str:
    """yt-dlp备选方案"""
    # 优先使用固定cookie文件（登录态），否则现刷新匿名cookie
    if os.path.exists(COOKIE_FILE):
        cookie_path = COOKIE_FILE
    else:
        cookie_path = "/tmp/bilibili_cookies.txt"
        _refresh_cookies(cookie_path)

    cmd = [
        YTDLP_BIN,
        "-x", "--audio-format", "mp3", "--audio-quality", "5",
        "-o", output_path,
        "--no-playlist", "--no-check-certificates",
        "--cookies", cookie_path,
        "--user-agent", UA,
        "--referer", "https://www.bilibili.com",
        "--add-header", "Accept:text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp下载失败: {result.stderr[:500]}")
    if not os.path.exists(output_path):
        raise RuntimeError("音频文件未找到")
    return output_path


def _refresh_cookies(path: str):
    """刷新B站cookie文件"""
    session = _make_session()
    with open(path, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in session.cookies:
            d = c.domain or ".bilibili.com"
            f.write(f"{d}\tTRUE\t/\tFALSE\t{c.expires or 0}\t{c.name}\t{c.value}\n")


def get_audio_duration(audio_path: str) -> float:
    """用ffprobe获取音频时长（秒）"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def split_audio(audio_path: str, chunk_minutes: int = 10) -> list:
    """将长音频切分为多个分片"""
    duration = get_audio_duration(audio_path)
    chunk_seconds = chunk_minutes * 60

    if duration <= chunk_seconds:
        return [audio_path]

    chunks = []
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    chunk_dir = os.path.join(AUDIO_DIR, f"{base_name}_chunks")
    os.makedirs(chunk_dir, exist_ok=True)

    i = 0
    start = 0
    while start < duration:
        chunk_path = os.path.join(chunk_dir, f"chunk_{i:03d}.mp3")
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-ss", str(start),
            "-t", str(chunk_seconds),
            "-acodec", "libmp3lame", "-b:a", "64k",
            chunk_path
        ]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if os.path.exists(chunk_path):
            chunks.append(chunk_path)
        start += chunk_seconds
        i += 1

    return chunks


def cleanup_audio(task_id: str):
    """清理音频文件"""
    audio_path = os.path.join(AUDIO_DIR, f"{task_id}.mp3")
    chunk_dir = os.path.join(AUDIO_DIR, f"{task_id}_chunks")

    for f in [audio_path]:
        if os.path.exists(f):
            os.remove(f)

    if os.path.exists(chunk_dir):
        import shutil
        shutil.rmtree(chunk_dir, ignore_errors=True)
