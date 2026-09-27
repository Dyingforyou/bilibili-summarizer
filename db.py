"""B站总结助手 - 数据库操作"""
import sqlite3
import json
from datetime import datetime
from config import DB_PATH


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE NOT NULL,
            video_url TEXT NOT NULL,
            bvid TEXT,
            platform TEXT DEFAULT 'bilibili',
            video_id TEXT DEFAULT '',
            title TEXT,
            cover_url TEXT,
            author TEXT,
            duration INTEGER DEFAULT 0,
            transcript TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            error_message TEXT DEFAULT '',
            transcript_source TEXT DEFAULT '',
            summary_provenance TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)
    # 兼容旧数据库：如果列不存在则添加
    try:
        conn.execute("ALTER TABLE summaries ADD COLUMN transcript_source TEXT DEFAULT ''")
    except Exception:
        pass  # 列已存在
    for sql in (
        "ALTER TABLE summaries ADD COLUMN platform TEXT DEFAULT 'bilibili'",
        "ALTER TABLE summaries ADD COLUMN video_id TEXT DEFAULT ''",
        "ALTER TABLE summaries ADD COLUMN summary_provenance TEXT DEFAULT ''",
    ):
        try:
            conn.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()


def create_task(task_id: str, video_url: str, platform: str = "bilibili") -> str:
    conn = get_db()
    conn.execute(
        "INSERT INTO summaries (task_id, video_url, platform) VALUES (?, ?, ?)",
        (task_id, video_url, platform)
    )
    conn.commit()
    conn.close()
    return task_id


def update_task(task_id: str, **kwargs):
    kwargs["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [task_id]
    conn = get_db()
    conn.execute(f"UPDATE summaries SET {sets} WHERE task_id = ?", vals)
    conn.commit()
    conn.close()


def get_task(task_id: str) -> dict:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM summaries WHERE task_id = ?", (task_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_tasks(limit=50) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM summaries ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_task(task_id: str):
    conn = get_db()
    conn.execute("DELETE FROM summaries WHERE task_id = ?", (task_id,))
    conn.commit()
    conn.close()
