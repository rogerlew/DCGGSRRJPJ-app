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
from flask import Flask
from flask_socketio import SocketIO
import redis

import time
import os
import socketio

# --- Configuration ---
# MUST match the message queue used by your main Flask-SocketIO app
REDIS_URL = os.getenv("SOCKETIO_MESSAGE_QUEUE", "redis://redis:6379/0")

# Connection for the cancellation flag (using a different DB)
redis_cancel_client = redis.StrictRedis(host='redis', port=6379, db=3, decode_responses=True)

# --- Socket.IO Publisher ---
# This is the key component. It connects to Redis to publish messages.
# write_only=True is an optimization, as this worker never needs to receive messages.
worker_socketio = socketio.RedisManager(REDIS_URL, write_only=True)

def long_running_task(sid):
    """
    This is the version of the task designed to be run by an RQ worker.
    It uses socketio.RedisManager to proxy messsage to client
    The core logic is identical to the gevent-based task.
    """
    # Create a temporary app and socketio instance for the worker process.
    # This socketio instance will connect to the Redis message queue as a client
    # and publish messages, which the main server will then pick up and send to the browser.

    worker_socketio.emit('task_started',
                        {'status': 'Your independent task has been started.'},
                        to=sid)

    print(f"[RQ Worker] Task started for SID: {sid}")
    cancel_key = f"cancel_{sid}"

    worker_socketio.emit('task_progress', {'percent': 0.0}, to=sid)

    total_iterations = 50

    for i in range(1, total_iterations + 1):
        
        time.sleep(2)

        
        percent_complete = int((i / total_iterations) * 100)
        worker_socketio.emit('task_progress', {'percent': percent_complete}, to=sid)
        print(f"  [RQ Worker] ... progress {percent_complete}% for SID: {sid}")
