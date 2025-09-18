# app/rq_long_running.py

"""RQ task definitions for long-running operations with cancellation support."""

from __future__ import annotations
import os
import redis
import time
import socketio
import uuid

REDIS_URL = os.getenv("SOCKETIO_MESSAGE_QUEUE", "redis://redis:6379/0")
redis_cancel_client = redis.StrictRedis(host='redis', port=6379, db=3, decode_responses=True)

def long_running_task(sid):
    """
    This is the version of the task designed to be run by an RQ worker.
    """
    worker_socketio = socketio.RedisManager(REDIS_URL, write_only=True)

    # ==================== START _publish TEST ====================
    print("--- TESTING _publish DIRECTLY ---", flush=True)
    test_message = {
        'method': 'emit',
        'event': 'test_event',
        'data': {'status': 'This is a direct publish test'},
        'namespace': '/',
        'room': sid,
        'skip_sid': None,
        'callback': None,
        'host_id': uuid.uuid4().hex
    }
    try:
        # We call the internal _publish method directly
        result = worker_socketio._publish(test_message)
        print(f"[TEST] Successfully called _publish. Result: {result}", flush=True)
    except Exception as e:
        print(f"[TEST] !!! FAILED to call _publish. Error: {e}", flush=True)
        import traceback
        traceback.print_exc() # Print the full error traceback
    print("--- END OF TEST ---", flush=True)
    # ===================== END _publish TEST =====================


    worker_socketio.emit('task_started',
                         {'status': 'Your independent task has been started.'},
                         to=sid)

    print(f"[RQ Worker] Task started for SID: {sid}", flush=True)

    worker_socketio.emit('task_progress', {'percent': 0.0}, to=sid)
    total_iterations = 50

    for i in range(1, total_iterations + 1):
        time.sleep(2)
        percent_complete = int((i / total_iterations) * 100)
        worker_socketio.emit('task_progress', {'percent': percent_complete}, to=sid)
        print(f"  [RQ Worker] ... progress {percent_complete}% for SID: {sid}", flush=True)
