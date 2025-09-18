from gevent import monkey
monkey.patch_all()

# ================================================================================
# app.py - Comparing Methods for Long-Running Tasks (with Cancellation)
# ================================================================================
from flask import Flask, render_template, request, session, jsonify
from flask_socketio import SocketIO, emit
from flask_session import Session
from datetime import timedelta
import os
import redis
import time
import tempfile
import shutil
import gevent
import gevent.subprocess as subprocess # Crucial for non-blocking subprocesses
from rq import Queue

# --- App Initialization ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('DCGGSRRJPJ_APP_SECRET_KEY') or 'dev-secret-key-change-in-production'

# --- Redis & Session Configuration ---
redis_host = os.getenv('REDIS_HOST', 'redis')
# Session Redis client (DB 1)
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_REDIS'] = redis.StrictRedis(host=redis_host, port=6379, db=1)
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=72)
Session(app)

# Cancellation Redis client (DB 3)
# decode_responses=True makes it easier to work with keys and values as strings
redis_cancel_client = redis.StrictRedis(host=redis_host, port=6379, db=3, decode_responses=True)
CANCELATION_TOKEN_LIFETIME = 600  # seconds

# --- Socket.IO Initialization ---
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="gevent",
    channel='flask-socketio',
    message_queue=os.getenv("SOCKETIO_MESSAGE_QUEUE", "redis://redis:6379/2"),
    logger=True,
    engineio_logger=True
)

# --- RQ Queue Configuration ---
rq_redis_url = os.getenv('RQ_REDIS_URL') or os.getenv('REDIS_URL') or f'redis://{redis_host}:6379/0'
task_queue = Queue('default', connection=redis.Redis.from_url(rq_redis_url), default_timeout=3600)


# ================================================================================
# Health check route for Proxy
# ================================================================================
@app.route('/health')
def health():
    return jsonify({'Status': 'Ok'})

# ================================================================================
# Routes and Socket.IO Events
# ================================================================================
@app.route('/')
def index():
    """Serves the updated HTML page with task controls."""
    return render_template('index.j2')

# --- Method 1: Start task via Socket.IO event (Recommended) ---
@socketio.on('start_task')
def handle_start_task():
    """Starts the task for the requesting client."""
    from gevent_long_running import long_running_task
    sid = request.sid
    print(f"Received 'start_task' event from SID: {sid}")
    redis_cancel_client.delete(f"cancel_{sid}") # Clear any old cancellation flags
    emit('task_started', {'status': 'Your background task has been initiated.'})
    socketio.start_background_task(long_running_task, sid)

# --- Method 2: Start task via non-blocking HTTP request ---
@app.route('/start-task2')
def start_long_task2():
    """Starts the task by getting the SID from the request args."""
    from gevent_long_running import long_running_task
    sid = request.args.get('sid')
    if not sid:
        return jsonify({"message": "Error: SID is required."}), 400
    
    print(f"Received HTTP request for /start-task2 for SID: {sid}")
    redis_cancel_client.delete(f"cancel_{sid}") # Clear any old cancellation flags
    socketio.emit('task_started', {'status': 'Your background task has been initiated.'}, to=sid)
    socketio.start_background_task(long_running_task, sid)
    return jsonify({"message": "Your long-running task has been started via HTTP."})


# --- Method 3: A cooperative but blocking task with cancellation ---
@app.route('/start-task3')
def start_long_task3():
    """
    Starts a long-running, INTENTIONALLY BLOCKING task directly within the HTTP
    request-response cycle. 
    
    This demonstrates why this approach is detrimental in a production server, 
    as it will make the server worker that handles this request completely 
    unresponsive to any other requests until the entire task is finished.
    """
    import subprocess # Use the standard blocking subprocess module
    import tempfile
    import shutil

    sid = request.args.get('sid')
    if not sid:
        return jsonify({"message": "Error: SID is required for this test."}), 400

    print(f"🛑 Starting INTENTIONALLY BLOCKING task for SID: {sid}")
    print("   This server worker will be UNRESPONSIVE to other HTTP requests until this completes.")

    # While the worker is blocked, emitting a message may still work if you are
    # using a message queue like Redis, as it just hands the message off.
    # However, the worker itself cannot do any other processing.
    socketio.emit('task_started', {'status': 'Your blocking task has started.'}, to=sid)

    temp_dir = tempfile.mkdtemp(prefix="blocking-task-")
    total_iterations = 20

    try:
        for i in range(1, total_iterations + 1):
            print(f"  [Blocking] Iteration {i}/{total_iterations} for SID: {sid}")

            # Define the commands for the current iteration
            cpu_command = [
                "openssl", "speed", "-evp", "aes-256-cbc", 
                "-multi", "10", # Use 10 cores for this process
            ]
            disk_output_file = os.path.join(temp_dir, f"temp_disk_iter_{i}.bin")
            disk_command = [
                "dd", "if=/dev/zero", f"of={disk_output_file}",
                "bs=1M", "count=1024",
                "oflag=direct",
            ]

            # --- THE BLOCKING CALLS ---
            # Each subprocess.run() call halts all execution in this worker
            # until the external command finishes. They run one after the other.
            print(f"    -> Running BLOCKING CPU task...")
            subprocess.run(cpu_command, capture_output=True, check=False)
            
            print(f"    -> Running BLOCKING Disk task...")
            subprocess.run(disk_command, capture_output=True, check=False)
            
            # Clean up the file for this iteration
            os.remove(disk_output_file)

            # NOTE: Cancellation checks are pointless here. Because this worker is
            # completely blocked, it could never process an incoming HTTP
            # request to the `/cancel-task` route in the first place.

            percent_complete = int((i / total_iterations) * 100)
            socketio.emit('task_progress', {'percent': percent_complete}, to=sid)
            print(f"  [Blocking] Progress: {percent_complete}%")

    except Exception as e:
        print(f"  [!!!] Error in blocking task for SID {sid}: {e}")
        return jsonify({"message": f"An error occurred in the blocking task: {e}"}), 500
    finally:
        # Cleanup is still important and will run after the loop completes or fails.
        print(f"  [Blocking] Cleaning up temp dir: {temp_dir}")
        shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"✅ Blocking task finished for SID: {sid}. Sending final HTTP response.")
    return jsonify({"message": f"The blocking task is finally complete after {total_iterations} iterations."})


# --- Method 4: Start task via RQ enqueue ---
@app.route('/start-task4')
def start_long_task4():
    """Enqueues the long-running task onto the RQ worker."""

    sid = request.args.get('sid')
    if not sid:
        return jsonify({"message": "Error: SID is required."}), 400

    print(f"Received HTTP request for /start-task4 for SID: {sid}")
    redis_cancel_client.delete(f"cancel_{sid}")
    socketio.emit('task_started', {'status': 'Your background task has been queued.'}, to=sid)
    job = task_queue.enqueue('rq_long_running.long_running_task', sid, job_timeout=3600)
    return jsonify({"message": "Your long-running task has been queued via RQ.", "job_id": job.id})


# --- CANCELLATION HANDLERS ---
@socketio.on('cancel_task')
def handle_cancel_task():
    """Sets a cancellation flag in Redis for the requesting client."""
    global CANCELATION_TOKEN_LIFETIME
    sid = request.sid
    print(f"Received 'cancel_task' event from SID: {sid}. Setting flag in Redis.")
    # Set the flag with a timeout (e.g., 10 minutes) to auto-clean if something goes wrong
    redis_cancel_client.set(f"cancel_{sid}", "1", ex=CANCELATION_TOKEN_LIFETIME)


@app.route('/cancel-task')
def cancel_task_http():
    """Sets a cancellation flag in Redis via an HTTP request."""
    global CANCELATION_TOKEN_LIFETIME
    sid = request.args.get('sid')
    if not sid:
        return jsonify({"message": "Error: SID is required."}), 400
    
    print(f"Received HTTP request to /cancel-task for SID: {sid}. Setting flag in Redis.")
    redis_cancel_client.set(f"cancel_{sid}", "1", ex=CANCELATION_TOKEN_LIFETIME)
    return jsonify({"message": "Cancellation signal sent."})


# --- STANDARD CONNECTION HANDLERS ---
@socketio.on('connect')
def handle_connect():
    """Handles a new client connection."""
    session['socket_sid'] = request.sid
    print(f"✅ Client connected: {request.sid}. Stored in Flask session.")
    emit('server_welcome', {'message': f'Welcome! Your SID {request.sid} has been stored.'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handles a client disconnection."""
    print(f"❌ Client disconnected: {request.sid}")