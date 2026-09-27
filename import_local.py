"""Import a video already on this machine, without uploading it through the web server."""
import argparse
import os
import shutil
import sys
import uuid

import db
from config import DATA_DIR
from server import process_local_video_task


def main() -> int:
    parser = argparse.ArgumentParser(description="总结本机视频文件（支持大文件）")
    parser.add_argument("video", help="本机视频文件路径")
    parser.add_argument("--publish-to-history", action="store_true",
                        help="将转录和总结写入现有网页数据库（可被网页访问者看到）")
    args = parser.parse_args()
    video_path = os.path.abspath(os.path.expanduser(args.video))
    if not os.path.isfile(video_path):
        parser.error(f"文件不存在: {video_path}")
    if not shutil.which("ffmpeg"):
        parser.error("需要先安装 ffmpeg")

    if not args.publish_to_history:
        db.DB_PATH = os.path.join(DATA_DIR, "local_summaries.db")
    db.init_db()
    if not args.publish_to_history:
        os.chmod(db.DB_PATH, 0o600)
    task_id = uuid.uuid4().hex[:12]
    # 不把本地绝对路径写入数据库，避免页面泄露目录结构。
    db.create_task(task_id, f"local:{task_id}", platform="local")
    print(f"任务 {task_id}：{os.path.basename(video_path)}", flush=True)
    process_local_video_task(task_id, video_path)
    task = db.get_task(task_id)
    if task["status"] != "completed":
        print(f"失败：{task['error_message']}", file=sys.stderr)
        return 1
    if args.publish_to_history:
        print(f"完成。可在网页历史记录中查看；任务 ID：{task_id}")
    else:
        result_dir = os.path.join(DATA_DIR, "local_results")
        os.makedirs(result_dir, mode=0o700, exist_ok=True)
        os.chmod(result_dir, 0o700)
        for suffix, content in (("summary.md", task["summary"]),
                                ("transcript.txt", task["transcript"])):
            output_path = os.path.join(result_dir, f"{task_id}.{suffix}")
            fd = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(content)
            print(f"已保存：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
