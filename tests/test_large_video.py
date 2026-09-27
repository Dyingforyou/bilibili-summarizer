"""Regression checks for local large-file extraction and full-length summaries."""
import os
import re
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import db
import llm
import import_local
import asr
import server
import video
from provenance import build_source_chunks


class LargeVideoTests(unittest.TestCase):
    def test_web_local_path_creates_history_task_without_storing_absolute_path(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large video.flv"
            source.write_bytes(b"test fixture")

            with patch.object(db, "DB_PATH", str(Path(directory) / "summaries.db")), patch.object(
                server, "LOCAL_FILE_IMPORT_ENABLED", True
            ), patch.object(server.subprocess, "run") as start_job:
                db.init_db()
                result = asyncio.run(server.submit_local_video(server.SubmitLocalRequest(path=str(source))))
                saved = db.get_task(result["task_id"])
                self.assertEqual(saved["platform"], "local")
                self.assertEqual(saved["status"], "pending")
                self.assertEqual(saved["title"], source.name)
                self.assertEqual(saved["video_url"], f"local:{result['task_id']}")
                self.assertNotIn(str(source), str(saved))
                command = start_job.call_args.args[0]
                self.assertIn("StartTransientUnit", command)
                self.assertIn(f"bilibili-local-{result['task_id']}.service", command)
                self.assertIn(source.as_posix(), command)

    def test_web_local_path_rejects_windows_paths_and_disabled_deployment(self):
        with self.assertRaises(HTTPException) as wrong_path:
            server.validate_local_video_path(r"C:\Users\Administrator\video.mp4")
        self.assertEqual(wrong_path.exception.status_code, 400)

        with patch.object(server, "LOCAL_FILE_IMPORT_ENABLED", False):
            with self.assertRaises(HTTPException) as disabled:
                asyncio.run(server.submit_local_video(server.SubmitLocalRequest(path="/tmp/video.mp4")))
        self.assertEqual(disabled.exception.status_code, 403)

    def test_asr_retries_transient_error_for_a_chunk(self):
        with tempfile.TemporaryDirectory() as directory:
            audio = Path(directory) / "chunk.mp3"
            audio.write_bytes(b"audio")
            retry = type("Response", (), {"status_code": 429, "text": "rate limit"})()
            success = type("Response", (), {"status_code": 200,
                                              "json": lambda self: {"text": "转录成功"}})()
            with patch.object(asr, "ASR_API_KEY", "test-key"), patch.object(
                asr.requests, "post", side_effect=[retry, success]
            ) as post, patch.object(asr.time, "sleep"):
                self.assertEqual(asr.transcribe_audio(str(audio)), "转录成功")
            self.assertEqual(post.call_count, 2)

    def test_local_import_keeps_result_out_of_public_history_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "private.mp4"
            source.write_bytes(b"placeholder")

            def fake_process(task_id, video_path):
                import db
                db.update_task(task_id, title=source.name, transcript="私人转录",
                               summary="私人总结", status="completed")

            with patch.object(import_local, "DATA_DIR", directory), patch.object(
                import_local.db, "DB_PATH", str(Path(directory) / "public_summaries.db")
            ), patch.object(
                import_local.shutil, "which", return_value="/usr/bin/tool"
            ), patch.object(import_local, "process_local_video_task", side_effect=fake_process), patch(
                "sys.argv", ["import_local.py", str(source)]
            ):
                self.assertEqual(import_local.main(), 0)

            private_db = Path(directory) / "local_summaries.db"
            result_files = list((Path(directory) / "local_results").glob("*"))
            self.assertTrue(private_db.exists())
            self.assertEqual(private_db.stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(result_files), 2)
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in result_files))

    def test_local_video_is_segmented_without_copying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "large video.mp4"
            source.write_bytes(b"video placeholder")
            audio_dir = Path(directory) / "audio"
            audio_dir.mkdir()
            commands = []

            def fake_run(command, **kwargs):
                commands.append(command)
                output = Path(command[-1])
                output.parent.mkdir(parents=True, exist_ok=True)
                (output.parent / "chunk_0000.mp3").write_bytes(b"first")
                (output.parent / "chunk_0001.mp3").write_bytes(b"second")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(video, "AUDIO_DIR", str(audio_dir)), patch.object(
                video.subprocess, "run", side_effect=fake_run
            ):
                chunks = video.split_local_video(str(source), "task123")

            self.assertEqual(len(chunks), 2)
            self.assertEqual(source.read_bytes(), b"video placeholder")
            self.assertIn("-map", commands[0])
            self.assertIn("0:a:0", commands[0])
            self.assertIn("-segment_time", commands[0])
            self.assertEqual(commands[0][commands[0].index("-segment_time") + 1], "600")

    def test_downloaded_long_audio_is_segmented_in_one_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "task123.mp3"
            source.write_bytes(b"audio placeholder")
            commands = []

            def fake_run(command, **kwargs):
                commands.append(command)
                output = Path(command[-1])
                output.parent.mkdir(parents=True, exist_ok=True)
                (output.parent / "chunk_0000.mp3").write_bytes(b"audio")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch.object(video, "AUDIO_DIR", directory), patch.object(
                video, "get_audio_duration", return_value=3600
            ), patch.object(video.subprocess, "run", side_effect=fake_run):
                chunks = video.split_audio(str(source))
            self.assertEqual(len(commands), 1)
            self.assertEqual(len(chunks), 1)

    def test_long_transcript_includes_last_section_and_provenance(self):
        transcript = ("长视频内容" * 60 + "。\n") * 100
        last_id = build_source_chunks(transcript)[-1]["id"]
        calls = []

        def fake_chat(messages, max_tokens, temperature=0.2):
            calls.append(messages)
            source = messages[-1]["content"]
            if messages[0]["content"] == llm.LONG_MAP_PROMPT:
                source_ids = re.findall(r"\[(S\d{4,})\]", source)
                return f"本段保留结尾事实【原文:{source_ids[-1]}】"
            self.assertIn(last_id, source)
            return f"末尾事实【原文:{last_id}】"

        with patch.object(llm, "_chat", side_effect=fake_chat):
            summary, provenance = llm.summarize_text(transcript, "长视频")

        self.assertGreater(len(calls), 2)
        self.assertIn(last_id, summary)
        self.assertIn(last_id, provenance)


if __name__ == "__main__":
    unittest.main()
