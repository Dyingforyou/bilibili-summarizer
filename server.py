"""多平台视频总结助手 - FastAPI 后端服务"""
import os
import sys
import uuid
import asyncio
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

# 确保能导入本地模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import DATA_DIR
from db import init_db, create_task, update_task, get_task, list_tasks, delete_task
from video import (extract_bvid, extract_page_number, get_video_info, get_subtitles, download_audio,
                   split_audio, cleanup_audio, detect_platform,
                   get_wechat_video_info, download_wechat_audio)
from asr import transcribe_chunks
from llm import summarize_text


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="视频总结助手", lifespan=lifespan)

# ────────────── 请求模型 ──────────────

class SubmitRequest(BaseModel):
    url: str

class SubmitBatchRequest(BaseModel):
    urls: list[str]

# ────────────── 后台任务 ──────────────

def process_video_task(task_id: str, url: str):
    """后台处理视频的完整流程（在线程中运行）"""
    try:
        platform = detect_platform(url)
        if not platform:
            raise RuntimeError("不支持的视频链接")
        # 1. 获取视频信息
        update_task(task_id, status="fetching_info")
        info = get_video_info(url) if platform == "bilibili" else get_wechat_video_info(url)
        # 分离内部字段和数据库字段
        db_info = {k: v for k, v in info.items() if not k.startswith("_")}
        update_task(task_id, **db_info)

        # 2. B站优先字幕；视频号分享页通常不提供字幕，直接走 ASR。
        update_task(task_id, status="fetching_subtitles")
        transcript = (get_subtitles(info["bvid"], info["_cid"], info["_aid"])
                      if platform == "bilibili" else None)

        if transcript:
            # 有字幕，跳过音频下载和ASR
            update_task(task_id, transcript=transcript, transcript_source="subtitle")
            print(f"[{task_id}] 使用字幕，跳过ASR")
        else:
            # 无字幕，走原有ASR流程
            print(f"[{task_id}] 无字幕，使用ASR")
            update_task(task_id, status="downloading")
            audio_path = (download_audio(url, task_id) if platform == "bilibili"
                          else download_wechat_audio(url, task_id))

            update_task(task_id, status="splitting")
            chunks = split_audio(audio_path, chunk_minutes=10)

            update_task(task_id, status="transcribing")
            transcript = transcribe_chunks(chunks)
            update_task(task_id, transcript=transcript, transcript_source="asr")

        # 3. LLM 总结
        update_task(task_id, status="summarizing")
        summary, summary_provenance = summarize_text(transcript, title=info.get("title", ""))
        update_task(task_id, summary=summary, summary_provenance=summary_provenance)

        # 4. 完成
        update_task(task_id, status="completed")

        # 5. 清理音频文件
        cleanup_audio(task_id)

    except Exception as e:
        traceback.print_exc()
        update_task(task_id, status="failed", error_message=str(e))
        # 清理
        try:
            cleanup_audio(task_id)
        except Exception:
            pass


def regenerate_summary_task(task_id: str):
    """使用已有转录稿重新生成带溯源的总结。"""
    try:
        task = get_task(task_id)
        if not task or not task.get("transcript"):
            raise RuntimeError("该任务没有可用的转录原文")
        update_task(task_id, status="summarizing", error_message="")
        summary, summary_provenance = summarize_text(
            task["transcript"], title=task.get("title", "")
        )
        update_task(
            task_id,
            summary=summary,
            summary_provenance=summary_provenance,
            status="completed",
        )
    except Exception as exc:
        traceback.print_exc()
        # 保留旧总结和转录，只报告本次重新生成失败。
        update_task(task_id, status="completed", error_message=f"生成溯源失败: {exc}")

# ────────────── API 路由 ──────────────

@app.post("/api/submit")
async def submit_video(req: SubmitRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "URL 不能为空")

    platform = detect_platform(url)
    if not platform:
        raise HTTPException(400, "请输入B站或微信视频号分享链接")

    task_id = uuid.uuid4().hex[:12]
    create_task(task_id, url, platform)

    # 在后台线程中执行（避免阻塞事件循环）
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, process_video_task, task_id, url)

    return {"task_id": task_id, "status": "pending"}


@app.get("/api/status/batch")
async def get_batch_status(ids: str):
    """批量查询任务状态，ids 为逗号分隔的 task_id 列表"""
    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        raise HTTPException(400, "请提供 task_id 列表")

    from db import get_db
    conn = get_db()
    placeholders = ",".join("?" for _ in id_list)
    rows = conn.execute(
        f"SELECT * FROM summaries WHERE task_id IN ({placeholders})",
        id_list
    ).fetchall()
    conn.close()

    result_map = {row["task_id"]: dict(row) for row in rows}
    # 保持请求顺序
    return [result_map.get(tid, {"task_id": tid, "status": "not_found"}) for tid in id_list]


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@app.get("/api/list")
async def get_list():
    return list_tasks()


@app.post("/api/provenance/{task_id}")
async def regenerate_provenance(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if not task.get("transcript"):
        raise HTTPException(400, "该任务没有可用的转录原文")
    if task.get("status") == "summarizing":
        return {"task_id": task_id, "status": "summarizing"}
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, regenerate_summary_task, task_id)
    return {"task_id": task_id, "status": "summarizing"}


@app.delete("/api/delete/{task_id}")
async def del_task(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    delete_task(task_id)
    try:
        cleanup_audio(task_id)
    except Exception:
        pass
    return {"ok": True}


@app.post("/api/submit_batch")
async def submit_batch(req: SubmitBatchRequest):
    """批量提交多个视频链接，每个独立处理"""
    if not req.urls:
        raise HTTPException(400, "请提供至少一个视频链接")

    results = []
    loop = asyncio.get_event_loop()

    for raw_url in req.urls:
        url = raw_url.strip()
        if not url:
            continue

        platform = detect_platform(url)
        if not platform:
            results.append({"url": raw_url, "error": "仅支持B站或微信视频号链接"})
            continue

        # 去重：检查是否已存在相同 bvid 的任务
        try:
            if platform != "bilibili":
                raise ValueError("视频号使用 URL 去重")
            bvid = extract_bvid(url)
            page_number = extract_page_number(url)
            existing = _find_task_by_bvid_and_page(bvid, page_number)
            if existing:
                results.append({
                    "task_id": existing["task_id"],
                    "url": url,
                    "status": existing["status"],
                    "dedup": True,
                })
                continue
        except Exception:
            pass  # 无法提取 bvid，继续创建新任务

        task_id = uuid.uuid4().hex[:12]
        create_task(task_id, url, platform)
        loop.run_in_executor(None, process_video_task, task_id, url)
        results.append({"task_id": task_id, "url": url, "status": "pending"})

    return {"tasks": results}


def _find_task_by_bvid_and_page(bvid: str, page_number: int) -> dict | None:
    """根据 bvid + 分P查找已有任务（P1/P2 不互相去重）。"""
    # 空 bvid 是视频号任务的正常值，不能用于 B 站任务去重；否则短链
    # 解析失败时会错误复用任意一个视频号任务。
    if not bvid:
        return None
    from db import get_db
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM summaries WHERE bvid = ? ORDER BY created_at DESC",
        (bvid,)
    ).fetchall()
    conn.close()
    for row in rows:
        try:
            existing_page = extract_page_number(row["video_url"])
        except Exception:
            existing_page = 1
        if existing_page == page_number:
            return dict(row)
    return None


# ────────────── 静态文件 ──────────────

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8002)
