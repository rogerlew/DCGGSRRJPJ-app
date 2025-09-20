"""RQ task definitions for long-running operations with cancellation support."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, List, Union

from redis import Redis
import gevent
import gevent.subprocess as subprocess



REDIS_URL = os.getenv("RQ_REDIS_URL") or os.getenv("REDIS_URL") or "redis://redis:6379/0"
redis_connection = Redis.from_url(REDIS_URL)

CancelResult = Union[str, int]

def _run_subprocess_with_cancel_check(sid, command):
    """
    Runs a command in a gevent-friendly subprocess and polls for a Redis 
    cancellation key. This function is designed to be run within a gevent Greenlet.

    Args:
        sid (str): The Socket.IO session ID, used to check for a cancellation flag.
        command (list): The command and its arguments to execute.

    Returns:
        str: 'cancelled' if the task was cancelled, otherwise the process's exit code.
    """

    from app import redis_cancel_client, socketio

    cancel_key = f"cancel_{sid}"
    proc = None
    try:
        # Use gevent's Popen for non-blocking subprocess management.
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        while proc.poll() is None:
            # Check for the cancellation signal in Redis.
            if redis_cancel_client.get(cancel_key):
                print(f"  [!] Subprocess monitor for SID {sid} found cancel signal. Terminating PID {proc.pid}.")
                proc.terminate()  # Send SIGTERM to the process.
                gevent.sleep(0.5) # Give it a moment to terminate gracefully.
                if proc.poll() is None:
                    print(f"  [!] Process {proc.pid} did not terminate, sending SIGKILL.")
                    proc.kill() # Force kill if it's still running.

                # The first greenlet to see the cancel signal handles the notification and cleanup.
                socketio.emit('task_cancelled', {'status': 'Task was cancelled by user.'}, to=sid)
                redis_cancel_client.delete(cancel_key)
                return 'cancelled'
            
            # Cooperatively yield control to the gevent event loop. This is critical.
            gevent.sleep(0.2)
        
        # Process finished on its own.
        return proc.returncode

    except Exception as e:
        print(f"  [!!!] Error running subprocess for SID {sid} with command '{' '.join(command)}': {e}")
        if proc and proc.poll() is None:
            proc.kill() # Ensure the process is killed on an unexpected error.
        return f'error: {e}'


def long_running_task(sid, total_iterations):
    """
    A non-trivial long-running task that spawns concurrent CPU-bound and
    Disk I/O-bound subprocesses in a loop, with cancellation support.
    """

    from app import redis_cancel_client, socketio

    if total_iterations < 1:
        raise ValueError("total_iterations must be at least 1")

    print(f"Task started for SID: {sid}")
    cancel_key = f"cancel_{sid}"
    # Create a temporary directory for this task's output files.
    temp_dir = tempfile.mkdtemp(prefix="gevent-task-")
    print(f"  Created temp dir for SID {sid}: {temp_dir}")

    socketio.emit('task_progress', {'percent': 0.0}, to=sid)
    
    try:
        for i in range(1, total_iterations + 1):
            # --- 1. Pre-iteration Cancellation Check ---
            if redis_cancel_client.get(cancel_key):
                print(f"  [!] Cancellation signal received for SID: {sid} before iteration {i}. Stopping.")
                socketio.emit('task_cancelled', {'status': 'Task was cancelled by user.'}, to=sid)
                redis_cancel_client.delete(cancel_key)
                return

            print(f"  Starting iteration {i}/{total_iterations} for SID: {sid}")

            # --- 2. Define Subprocess Commands ---
            cpu_command = [
                "openssl", "speed", "-evp", "aes-256-cbc", 
                "-multi", "10", # Use 10 cores for this process
            ]

            disk_output_file = os.path.join(temp_dir, f"temp_disk_file_iter_{i}.bin")
            disk_command = [
                "dd", "if=/dev/zero", f"of={disk_output_file}",
                "bs=1M", "count=1024", # Write 1024MB per iteration
                "oflag=direct", # Bypass OS cache for more realistic disk I/O
            ]

            # --- 3. Spawn Concurrent Subprocesses using gevent ---
            cpu_greenlet = gevent.spawn(_run_subprocess_with_cancel_check, sid, cpu_command)
            disk_greenlet = gevent.spawn(_run_subprocess_with_cancel_check, sid, disk_command)

            # --- 4. Wait for Both to Complete ---
            # gevent.joinall waits for both greenlets to finish their execution.
            gevent.joinall([cpu_greenlet, disk_greenlet])

            # --- 5. Check Results for Cancellation ---
            if cpu_greenlet.value == 'cancelled' or disk_greenlet.value == 'cancelled':
                print(f"  Confirmed cancellation during iteration {i} for SID: {sid}. Exiting loop.")
                break # Exit the for loop; the helper already sent the notification.

            print(f"  Finished iteration {i}. CPU task exit code: {cpu_greenlet.value}, Disk task exit code: {disk_greenlet.value}")
            
            # --- 6. Clean Up This Iteration's File ---
            try:
                os.remove(disk_output_file)
            except OSError as e:
                print(f"  Warning: Could not remove temp file {disk_output_file}: {e}")

            # --- 7. Report Progress ---
            percent_complete = int((i / total_iterations) * 100)
            socketio.emit('task_progress', {'percent': percent_complete}, to=sid)
            print(f"  ... progress {percent_complete}% for SID: {sid}")

        # If the loop finished without being cancelled, send the final 'finished' event.
        if not redis_cancel_client.get(cancel_key):
            socketio.emit('task_finished', {'status': f'Task completed all {total_iterations} iterations.'}, to=sid)
            print(f"Task finished normally for SID: {sid}")

    finally:
        # --- Final Cleanup ---
        # This block ensures the temporary directory is removed regardless of how the task exits.
        print(f"  Cleaning up temp dir: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        redis_cancel_client.delete(cancel_key) # Final cleanup of the cancellation key.

