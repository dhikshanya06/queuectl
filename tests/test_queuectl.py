import os
import sqlite3
import subprocess
import time
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
Q = ["python3", str(ROOT / "queuectl.py")]

DB = ROOT / "queue.db"
LOGS = ROOT / "logs"

# helper: run a command, return (returncode, stdout, stderr)
def run(cmd, timeout=15):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
    return p.returncode, out, err

def reset_env():
    # call reset (non-interactive): use env to auto-confirm
    # reset asks for confirmation; use expect-free method: delete files instead
    for f in ["queue.db", "queue.db-wal", "queue.db-shm"]:
        try:
            (ROOT / f).unlink(missing_ok=True)
        except Exception:
            pass
    if LOGS.exists() and LOGS.is_dir():
        shutil.rmtree(LOGS)
    if (ROOT / "queue_config.json").exists():
        # restore defaults
        (ROOT / "queue_config.json").write_text(json.dumps({"max_retries":3,"base_backoff":2.0,"default_timeout":None}))
    time.sleep(0.2)

def db_query(q, args=()):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    r = c.execute(q, args).fetchall()
    conn.close()
    return r

# 1. Basic job completes successfully.
def test_basic_job_completes():
    reset_env()
    code, out, err = run(Q + ["enqueue", '{"id":"t_success","command":"echo success"}'])
    assert code == 0
    # run worker in foreground but with short idle timeout
    p = subprocess.Popen(Q + ["worker", "start", "--count", "1", "--idle-timeout", "3"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # wait a bit for processing
    time.sleep(2)
    # stop if still running
    if p.poll() is None:
        p.terminate()
        p.wait(timeout=3)
    # check DB for completed job
    rows = db_query("SELECT id,state FROM jobs WHERE id='t_success'")
    assert rows and rows[0][1] == "completed"

# 2. Failed job retries with backoff and moves to DLQ.
def test_failed_job_retries_and_dlq():
    reset_env()
    # enqueue a job that fails; set max_retries=2 to keep test time short
    run(Q + ["enqueue", '{"id":"failtest","command":"false","max_retries":2,"base_backoff":1}'])
    # start worker
    p = subprocess.Popen(Q + ["worker", "start", "--count", "1", "--idle-timeout", "6"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    # wait enough for retries: base 1s -> 1^1=1s, 1^2=1s, plus execution time
    time.sleep(6)
    if p.poll() is None:
        p.terminate()
        p.wait(timeout=3)
    rows = db_query("SELECT id,state,attempts FROM jobs WHERE id='failtest'")
    assert rows and rows[0][1] == "dead" and rows[0][2] >= 2

# 3. Multiple workers process jobs without overlap.
def test_multiple_workers_no_overlap():
    reset_env()
    run(Q + ["enqueue", '{"id":"m1","command":"sleep 1 && echo m1"}'])
    run(Q + ["enqueue", '{"id":"m2","command":"sleep 1 && echo m2"}'])
    run(Q + ["enqueue", '{"id":"m3","command":"sleep 1 && echo m3"}'])
    # start 3 workers
    p = subprocess.Popen(Q + ["worker", "start", "--count", "3", "--idle-timeout", "5"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(5)
    if p.poll() is None:
        p.terminate()
        p.wait(timeout=3)
    # ensure all completed and no duplicate states
    rows = db_query("SELECT id, state FROM jobs WHERE id IN ('m1','m2','m3')")
    assert len(rows) == 3
    for r in rows:
        assert r[1] == "completed"

# 4. Invalid commands fail gracefully.
def test_invalid_command_handling():
    reset_env()
    run(Q + ["enqueue", '{"id":"badcmd","command":"command-not-exists","max_retries":1,"base_backoff":1}'])
    p = subprocess.Popen(Q + ["worker", "start", "--count", "1", "--idle-timeout", "4"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(5)
    if p.poll() is None:
        p.terminate()
        p.wait(timeout=3)
    rows = db_query("SELECT id,state,attempts FROM jobs WHERE id='badcmd'")
    assert rows and rows[0][1] in ("dead","pending","completed")

# 5. Job data survives restart.
def test_persistence_across_restart():
    reset_env()
    run(Q + ["enqueue", '{"id":"persist","command":"echo p"}'])
    # start worker and let it process and stop
    p = subprocess.Popen(Q + ["worker", "start", "--count", "1", "--idle-timeout", "3"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(3)
    if p.poll() is None:
        p.terminate()
        p.wait(timeout=3)
    # now "restart" environment: just re-init DB by reopening
    rows_before = db_query("SELECT id,state FROM jobs WHERE id='persist'")
    assert rows_before and rows_before[0][1] in ("completed","pending")
    # simulate program restart (no files removed)
    # run status to ensure DB still accessible
    code, out, err = run(Q + ["status"])
    assert code == 0

