"""B站总结助手 - 语音识别（硅基流动 TeleSpeechASR）"""
import os
import time

import requests
from config import ASR_API_KEY, ASR_BASE_URL, ASR_MODEL, MAX_FILE_SIZE_MB


def transcribe_audio(audio_path: str) -> str:
    """将单个音频文件转为文字"""
    if not ASR_API_KEY:
        raise RuntimeError("未配置 ASR_API_KEY，请复制 .env.example 为 .env 后填写")
    if os.path.getsize(audio_path) > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise RuntimeError(f"音频分片超过 {MAX_FILE_SIZE_MB}MB，请缩短分片时长")
    url = f"{ASR_BASE_URL}/audio/transcriptions"

    data = {"model": ASR_MODEL, "language": "zh"}
    headers = {"Authorization": f"Bearer {ASR_API_KEY}"}
    for attempt in range(3):
        try:
            with open(audio_path, "rb") as audio_file:
                files = {"file": (os.path.basename(audio_path), audio_file, "audio/mpeg")}
                resp = requests.post(url, headers=headers, files=files, data=data, timeout=300)
            if resp.status_code == 200:
                return resp.json().get("text", "").strip()
            if resp.status_code != 429 and resp.status_code < 500:
                raise RuntimeError(f"ASR 请求失败 [{resp.status_code}]: {resp.text[:300]}")
            error = f"ASR 请求失败 [{resp.status_code}]: {resp.text[:300]}"
        except requests.RequestException as exc:
            error = f"ASR 网络请求失败: {exc}"
        if attempt < 2:
            time.sleep(2 ** attempt)
    raise RuntimeError(error)


def transcribe_chunks(chunk_paths: list) -> str:
    """分片转写并拼接"""
    texts = []
    for i, path in enumerate(chunk_paths):
        text = transcribe_audio(path)
        if text:
            texts.append(text)
    return "\n".join(texts)
