"""Run one web-submitted server-side video task in its own user service."""

import sys

from server import process_local_video_task


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: run_local_task.py TASK_ID ABSOLUTE_VIDEO_PATH")
    process_local_video_task(sys.argv[1], sys.argv[2])
