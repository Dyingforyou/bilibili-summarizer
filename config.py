"""B站总结助手 - 配置文件"""
import os

# === 路径 ===
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_local_env(path: str) -> None:
    """Load an ignored local env file without adding a runtime dependency."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_local_env(os.path.join(BASE_DIR, ".env"))

DATA_DIR = os.path.join(BASE_DIR, "data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
DB_PATH = os.path.join(DATA_DIR, "summaries.db")
COOKIE_FILE = os.path.join(DATA_DIR, "bilibili_cookies.txt")
WECHAT_COOKIE_FILE = os.path.join(DATA_DIR, "wechat_cookies.txt")
YUANBAO_COOKIE_FILE = os.path.join(BASE_DIR, "yuanbaocookie.txt")

# 确保目录存在
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# === 硅基流动 ASR ===
ASR_API_KEY = os.getenv("ASR_API_KEY", "").strip()
ASR_BASE_URL = "https://api.siliconflow.cn/v1"
ASR_MODEL = "TeleAI/TeleSpeechASR"

# === 阿里云百炼 LLM ===
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
# 默认使用低成本模型；可用环境变量按需覆盖。
LLM_MODEL = os.getenv("LLM_MODEL", "qwen-flash")

# === 处理参数 ===
AUDIO_CHUNK_MINUTES = 10  # 每个音频分片时长（分钟）
MAX_FILE_SIZE_MB = 45     # 留点余量，API限制50MB
