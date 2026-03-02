#!/usr/bin/env python3
import os
import time
import sqlite3
import threading
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Flask, request, redirect, url_for, render_template_string, abort
from werkzeug.utils import secure_filename

BASE_DIR = "/home/alshaya/POS_Visa_Automation"
UPLOAD_DIR = os.path.join(BASE_DIR, "incoming/new")
LOG_DIR = os.path.join(BASE_DIR, "logs/uploads")
DB_PATH = os.path.join(BASE_DIR, "gui_upload", "uploads.db")

ALLOWED_EXT = {".xml"}   # strict
MAX_MB = 10

# OPTIONAL Basic Auth (enable by exporting env vars)
# export UPLOAD_USER="posops"
# export UPLOAD_PASS="StrongPassword"
UPLOAD_USER = os.environ.get("UPLOAD_USER")
UPLOAD_PASS = os.environ.get("UPLOAD_PASS")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>POS XML Uploader</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 980px; margin: 30px auto; }
    .box { border: 2px dashed #999; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
    .muted { color: #666; }
    .ok { color: #0a7; font-weight: bold; }
    .err { color: #c00; font-weight: bold; }
    .badge { padding: 3px 10px; border-radius: 20px; font-size: 12px; display: inline-block; }
    .queued { background:#eee; }
    .running { background:#cfe8ff; }
    .success { background:#d4f7d4; }
    .failed  { background:#ffd4d4; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #ddd; padding: 10px; text-align: left; }
    th { background: #f7f7f7; }
    .small { font-size: 12px; }
    a { text-decoration: none; }

    footer {
      margin-top: 24px;
      padding-top: 12px;
      border-top: 1px solid #e6e6e6;
      color: #666;
      font-size: 12px;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    footer .right { color: #888; }
  </style>
</head>
<body>
  <h2>POS XML Uploader</h2>
  <p class="muted">Accepted: <b>.xml</b> | Max size: <b>{{max_mb}} MB</b></p>

  {% if msg %}
    <p class="{{ 'ok' if ok else 'err' }}">{{ msg }}</p>
  {% endif %}

  <div class="box">
    <form action="/upload" method="post" enctype="multipart/form-data">
      <p><input type="file" name="file" accept=".xml" required /></p>
      <p><button type="submit">Upload</button></p>
      <p class="muted small">After upload, the system will stage &amp; deploy automatically. History below updates on refresh.</p>
    </form>
  </div>

  <h3>History (last 20)</h3>
  <table>
    <thead>
      <tr>
        <th>Time</th>
        <th>Uploaded file</th>
        <th>Saved as</th>
        <th>Status</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for row in rows %}
      <tr>
        <td class="small">{{ row["uploaded_at"] }}</td>
        <td>{{ row["orig_name"] }}</td>
        <td class="small">{{ row["saved_name"] }}</td>
        <td>
          {% set s = row["status"] %}
          <span class="badge {{ s|lower }}">{{ s }}</span>
          {% if row["stage_rc"] is not none %}
            <span class="small muted">stage_rc={{ row["stage_rc"] }}</span>
          {% endif %}
          {% if row["ansible_rc"] is not none %}
            <span class="small muted">ansible_rc={{ row["ansible_rc"] }}</span>
          {% endif %}
        </td>
        <td class="small">
          <a href="/log/{{ row['id'] }}">View log</a>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>

  <p class="muted small">Tip: refresh to update statuses.</p>

  <footer>
    <div>© {{ year }} • Developed &amp; maintained by <b>Ashraf Hassan</b> — Systems Support Engineer</div>
    <div class="right">POS XML Uploader • Internal Tool</div>
  </footer>
</body>
</html>
"""

LOG_HTML = r"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Upload Log</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 980px; margin: 30px auto; }
    pre { background: #111; color: #eee; padding: 15px; border-radius: 10px; overflow:auto; }
    a { text-decoration: none; }

    footer {
      margin-top: 24px;
      padding-top: 12px;
      border-top: 1px solid #e6e6e6;
      color: #666;
      font-size: 12px;
      display: flex;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    footer .right { color: #888; }
  </style>
</head>
<body>
  <p><a href="/">← Back</a></p>
  <h3>Log for upload #{{id}}</h3>
  <p class="muted">{{meta}}</p>
  <pre>{{content}}</pre>

  <footer>
    <div>© {{ year }} • Developed &amp; maintained by <b>Ashraf Hassan</b></div>
    <div class="right">POS XML Uploader • Logs</div>
  </footer>
</body>
</html>
"""

# ---- DB helpers ----
def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orig_name TEXT NOT NULL,
            saved_name TEXT NOT NULL,
            saved_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            status TEXT NOT NULL,
            stage_rc INTEGER,
            ansible_rc INTEGER,
            log_path TEXT NOT NULL
        )
        """)
        conn.commit()

# ---- Basic auth (optional) ----
def check_auth():
    if not (UPLOAD_USER and UPLOAD_PASS):
        return True
    auth = request.authorization
    return auth and auth.username == UPLOAD_USER and auth.password == UPLOAD_PASS

@app.before_request
def auth_gate():
    if request.path in ("/", "/upload") or request.path.startswith("/log/"):
        if not check_auth():
            return abort(401)

# ---- Job worker (single queue) ----
worker_lock = threading.Lock()
worker_running = False

def start_worker_if_needed():
    global worker_running
    with worker_lock:
        if worker_running:
            return
        worker_running = True
        t = threading.Thread(target=worker_loop, daemon=True)
        t.start()

def worker_loop():
    global worker_running
    try:
        while True:
            with db() as conn:
                row = conn.execute(
                    "SELECT * FROM uploads WHERE status='QUEUED' ORDER BY id ASC LIMIT 1"
                ).fetchone()

                if row is None:
                    break

                conn.execute("UPDATE uploads SET status='RUNNING' WHERE id=?", (row["id"],))
                conn.commit()

            run_pipeline_for_job(row["id"], row["log_path"])
    finally:
        with worker_lock:
            worker_running = False

def run_pipeline_for_job(job_id: int, log_path: str):
    os.makedirs(LOG_DIR, exist_ok=True)

    def log(line: str):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().strftime('%F %T')} {line}\n")

    stage_rc = None
    ansible_rc = None
    status = "FAILED"

    # Use your pyenv shims (as per your environment)
    stage_cmd = [
        "/home/alshaya/.pyenv/shims/python3",
        f"{BASE_DIR}/scripts/stage_pos_xmls.py",
        "--source",
        UPLOAD_DIR
    ]
    ansible_cmd = [
        "/home/alshaya/.pyenv/shims/ansible-playbook",
        "-i",
        f"{BASE_DIR}/inventory/hosts.yml",
        f"{BASE_DIR}/ansible/site.yml"
    ]

    try:
        log(f"Job #{job_id}: starting stage")
        with open(log_path, "a") as lf:
            stage_rc = subprocess.call(stage_cmd, stdout=lf, stderr=subprocess.STDOUT)
        log(f"Stage finished rc={stage_rc}")

        if stage_rc != 0:
            raise RuntimeError(f"stage_pos_xmls.py failed rc={stage_rc}")

        log(f"Job #{job_id}: starting ansible")
        with open(log_path, "a") as lf:
            ansible_rc = subprocess.call(ansible_cmd, stdout=lf, stderr=subprocess.STDOUT)
        log(f"Ansible finished rc={ansible_rc}")

        if ansible_rc != 0:
            raise RuntimeError(f"ansible-playbook failed rc={ansible_rc}")

        status = "SUCCESS"
    except Exception as e:
        log(f"ERROR: {e}")
    finally:
        with db() as conn:
            conn.execute(
                "UPDATE uploads SET status=?, stage_rc=?, ansible_rc=? WHERE id=?",
                (status, stage_rc, ansible_rc, job_id)
            )
            conn.commit()

# ---- Routes ----
@app.route("/", methods=["GET"])
def index():
    init_db()
    with db() as conn:
        rows = conn.execute(
            "SELECT id, orig_name, saved_name, uploaded_at, status, stage_rc, ansible_rc "
            "FROM uploads ORDER BY id DESC LIMIT 20"
        ).fetchall()
    return render_template_string(
        HTML, msg=None, ok=True, max_mb=MAX_MB, rows=rows, year=datetime.now().year
    )

@app.route("/upload", methods=["POST"])
def upload():
    init_db()

    if "file" not in request.files:
        return render_template_string(HTML, msg="No file part.", ok=False, max_mb=MAX_MB, rows=[], year=datetime.now().year), 400

    f = request.files["file"]
    if not f.filename:
        return render_template_string(HTML, msg="No selected file.", ok=False, max_mb=MAX_MB, rows=[], year=datetime.now().year), 400

    filename = secure_filename(f.filename)

    # Normalize extension: allow .XML/.xml but always save as lowercase .xml
    p = Path(filename)
    ext = p.suffix.lower()
    if ext not in ALLOWED_EXT:
        return render_template_string(HTML, msg="Only .xml files are allowed.", ok=False, max_mb=MAX_MB, rows=[], year=datetime.now().year), 400
    filename = f"{p.stem}.xml"  # force lowercase extension so staging script always finds it

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    # Ensure unique filename if exists
    dest = os.path.join(UPLOAD_DIR, filename)
    if os.path.exists(dest):
        stamp = time.strftime("%Y%m%d%H%M%S")
        dest = os.path.join(UPLOAD_DIR, f"{Path(filename).stem}-{stamp}.xml")

    f.save(dest)

    uploaded_at = datetime.now().strftime("%F %T")
    saved_name = os.path.basename(dest)
    log_path = os.path.join(LOG_DIR, f"upload-{int(time.time())}-{saved_name}.log")

    # Insert queued job
    with db() as conn:
        conn.execute("""
            INSERT INTO uploads (orig_name, saved_name, saved_path, uploaded_at, status, stage_rc, ansible_rc, log_path)
            VALUES (?, ?, ?, ?, 'QUEUED', NULL, NULL, ?)
        """, (f.filename, saved_name, dest, uploaded_at, log_path))
        conn.commit()

    # Start worker
    start_worker_if_needed()

    return redirect(url_for("index"))

@app.route("/log/<int:job_id>", methods=["GET"])
def view_log(job_id: int):
    init_db()
    with db() as conn:
        row = conn.execute("SELECT * FROM uploads WHERE id=?", (job_id,)).fetchone()
    if row is None:
        abort(404)

    log_path = row["log_path"]
    meta = f"{row['uploaded_at']} | {row['orig_name']} → {row['saved_name']} | status={row['status']}"

    content = "(log file not found yet)"
    if os.path.exists(log_path):
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[-400:]
        content = "".join(lines)

    return render_template_string(
        LOG_HTML, id=job_id, meta=meta, content=content, year=datetime.now().year
    )

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=7070)
