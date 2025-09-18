import os
import shutil
import subprocess
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import redis
import socketio

# --- Configuration (from your existing file) ---
REDIS_URL = os.getenv("SOCKETIO_MESSAGE_QUEUE", "redis://redis:6379/0")
redis_cancel_client = redis.StrictRedis(host='redis', port=6379, db=3, decode_responses=True)


def _run_subprocess(command):
    """A helper function to run a command in a separate thread."""
    # Use the standard library subprocess.run which blocks until the command is complete.
    # capture_output=True prevents subprocess output from cluttering the worker logs.
    result = subprocess.run(command, capture_output=True, check=False)
    return result.returncode


def long_running_task(sid):
    """
    An RQ task that runs concurrent CPU and Disk I/O bound subprocesses,
    emits progress via RedisManager, and supports cancellation between iterations.
    """
    worker_socketio = socketio.RedisManager(
        REDIS_URL, write_only=True,
        channel='flask-socketio'
    )

    worker_socketio.emit('task_started',
                         {'status': 'Your concurrent subprocess task has been started.'},
                         to=sid)
    print(f"[RQ Worker] Task started for SID: {sid}", flush=True)

    cancel_key = f"cancel_{sid}"
    temp_dir = tempfile.mkdtemp(prefix="rq-task-")
    print(f"  [RQ Worker] Created temp dir for SID {sid}: {temp_dir}", flush=True)

    worker_socketio.emit('task_progress', {'percent': 0.0}, to=sid)

    total_iterations = 50

    try:
        for i in range(1, total_iterations + 1):
            # --- 1. Pre-iteration Cancellation Check ---
            if redis_cancel_client.get(cancel_key):
                print(f"  [!] Cancellation signal received for SID: {sid}. Stopping.", flush=True)
                worker_socketio.emit('task_cancelled', {'status': 'Task was cancelled by user.'}, to=sid)
                return  # Exit the task cleanly

            print(f"  [RQ Worker] Starting iteration {i}/{total_iterations} for SID: {sid}", flush=True)

            # --- 2. Define Subprocess Commands ---
            cpu_command = ["openssl", "speed", "-evp", "aes-256-cbc", "-multi", "10"]
            disk_output_file = os.path.join(temp_dir, f"temp_disk_iter_{i}.bin")
            disk_command = ["dd", "if=/dev/zero", f"of={disk_output_file}", "bs=1M", "count=1024", "oflag=direct"]

            # --- 3. Run Concurrent Subprocesses using ThreadPoolExecutor ---
            with ThreadPoolExecutor(max_workers=2) as executor:
                # Submit both commands to the thread pool to run concurrently
                future_cpu = executor.submit(_run_subprocess, cpu_command)
                future_disk = executor.submit(_run_subprocess, disk_command)

                # .result() blocks until the future is complete, effectively waiting for both
                cpu_exit_code = future_cpu.result()
                disk_exit_code = future_disk.result()

            print(f"  [RQ Worker] Finished iteration {i}. CPU exit: {cpu_exit_code}, Disk exit: {disk_exit_code}", flush=True)

            # --- 4. Clean Up This Iteration's File ---
            try:
                os.remove(disk_output_file)
            except OSError as e:
                print(f"  [RQ Worker] Warning: Could not remove temp file {disk_output_file}: {e}", flush=True)

            # --- 5. Report Progress ---
            percent_complete = int((i / total_iterations) * 100)
            worker_socketio.emit('task_progress', {'percent': percent_complete}, to=sid)
            print(f"  [RQ Worker] ... progress {percent_complete}% for SID: {sid}", flush=True)

        # --- 6. Report Task Finished ---
        # If the loop finished without being cancelled, send the final 'finished' event.
        if not redis_cancel_client.get(cancel_key):
            worker_socketio.emit('task_finished', {'status': f'Task completed all {total_iterations} iterations.'}, to=sid)
            print(f"[RQ Worker] Task finished normally for SID: {sid}", flush=True)

    finally:
        # --- Final Cleanup ---
        print(f"  [RQ Worker] Cleaning up temp dir: {temp_dir}", flush=True)
        shutil.rmtree(temp_dir, ignore_errors=True)
        redis_cancel_client.delete(cancel_key) # Ensure the cancellation key is always removed