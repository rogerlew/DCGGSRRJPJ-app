"""RQ task definitions for long-running operations with cancellation support."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List

from redis import Redis
from rq import get_current_job
from rq.decorators import job


REDIS_URL = os.getenv("RQ_REDIS_URL") or os.getenv("REDIS_URL") or "redis://redis:6379/0"
redis_connection = Redis.from_url(REDIS_URL)

def _run_subprocess(command: Iterable[str]) -> int:
    """Run a subprocess and return its exit code."""
    completed = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )

    if completed.stdout:
        print(f"    [stdout] {' '.join(command)} -> {completed.stdout.strip()[:200]}")
    if completed.stderr:
        print(f"    [stderr] {' '.join(command)} -> {completed.stderr.strip()[:200]}")

    return completed.returncode


@job('default', connection=redis_connection, timeout=3600)
def long_running_task(sid: str) -> None:
    """Execute the long-running workload inside an application context."""

    from app import app, redis_cancel_client, socketio

    with app.app_context():
        job = get_current_job()
        if job:
            job.meta.update({'sid': sid, 'progress': 0, 'status': 'running'})
            job.save_meta()

        cancel_key = f"cancel_{sid}"
        temp_dir = tempfile.mkdtemp(prefix="thread-task-")
        total_iterations = 50

        print(f"Task started for SID: {sid}")
        print(f"  Created temp dir for SID {sid}: {temp_dir}")

        socketio.emit('task_progress', {'percent': 0.0}, to=sid)
        # hang

        with ThreadPoolExecutor(max_workers=2) as executor:
            for iteration in range(1, total_iterations + 1):
                if redis_cancel_client.get(cancel_key):
                    print(
                        f"  [!] Cancellation signal received for SID: {sid} before iteration {iteration}. Stopping."
                    )
                    socketio.emit('task_cancelled', {'status': 'Task was cancelled by user.'}, to=sid)
                    redis_cancel_client.delete(cancel_key)
                    break

                print(f"  Starting iteration {iteration}/{total_iterations} for SID: {sid}")

                cpu_command: List[str] = [
                    "openssl",
                    "speed",
                    "-evp",
                    "aes-256-cbc",
                    "-multi",
                    "10",
                ]

                disk_output_file = os.path.join(temp_dir, f"temp_disk_file_iter_{iteration}.bin")
                disk_command: List[str] = [
                    "dd",
                    "if=/dev/zero",
                    f"of={disk_output_file}",
                    "bs=1M",
                    "count=1024",
                    "oflag=direct",
                ]

                cpu_future = executor.submit(_run_subprocess, cpu_command)
                disk_future = executor.submit(_run_subprocess, disk_command)

                cpu_result = cpu_future.result()
                disk_result = disk_future.result()

                print(
                    "  Finished iteration {iter_idx}. CPU task exit code: {cpu_exit}, Disk task exit code: {disk_exit}".format(
                        iter_idx=iteration,
                        cpu_exit=cpu_result,
                        disk_exit=disk_result,
                    )
                )

                try:
                    os.remove(disk_output_file)
                except OSError as exc:
                    print(f"  Warning: Could not remove temp file {disk_output_file}: {exc}")

                percent_complete = int((iteration / total_iterations) * 100)
                socketio.emit('task_progress', {'percent': percent_complete}, to=sid)
                print(f"  ... progress {percent_complete}% for SID: {sid}")

                if job:
                    job.meta.update({'progress': percent_complete})
                    job.save_meta()

            else:
                socketio.emit(
                    'task_finished',
                    {'status': f'Task completed all {total_iterations} iterations.'},
                    to=sid,
                )
                print(f"Task finished normally for SID: {sid}")

                if job:
                    job.meta.update({'progress': 100, 'status': 'finished'})
                    job.save_meta()