"""B站总结助手 - 语音识别（硅基流动 TeleSpeechASR）"""
import requests
from config import ASR_API_KEY, ASR_BASE_URL, ASR_MODEL


def transcribe_audio(audio_path: str) -> str:
    """将单个音频文件转为文字"""
    if not ASR_API_KEY:
        raise RuntimeError("未配置 ASR_API_KEY，请复制 .env.example 为 .env 后填写")
    url = f"{ASR_BASE_URL}/audio/transcriptions"

    with open(audio_path, "rb") as f:
        files = {"file": (audio_path.split("/")[-1], f, "audio/mpeg")}
        data = {"model": ASR_MODEL, "language": "zh"}
        headers = {"Authorization": f"Bearer {ASR_API_KEY}"}

        resp = requests.post(url, headers=headers, files=files, data=data, timeout=120)

    if resp.status_code != 200:
        raise RuntimeError(f"ASR 请求失败 [{resp.status_code}]: {resp.text[:300]}")

    result = resp.json()
    return result.get("text", "").strip()


def transcribe_chunks(chunk_paths: list) -> str:
    """分片转写并拼接"""
    texts = []
    for i, path in enumerate(chunk_paths):
        text = transcribe_audio(path)
        if text:
            texts.append(text)
    return "\n".join(texts)
