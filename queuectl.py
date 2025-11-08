#!/usr/bin/env python3
"""
queuectl.py - CLI job queue with retries, exponential backoff, DLQ, SQLite persistence,
per-job logging, job timeout, scheduled jobs (run_at), priority, metrics,
and a safe `reset` command to reinitialize the database and logs.
"""

import sqlite3
import json
import uuid
import subprocess
import signal
import sys
import time
import datetime
from multiprocessing import Process, Value
from pathlib import Path
import os
import shutil

import click

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "queue.db"
CONFIG_PATH = ROOT / "queue_config.json"
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Helper: ISO UTC timestamp (timezone-aware)
def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")


# Init or migrate DB: create table and try to add missing columns if old DB present
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    c = conn.cursor()
    # create base table (if not exists) with additional columns for extras
    c.execute(
        """
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY,
      command TEXT NOT NULL,
      state TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,
      max_retries INTEGER NOT NULL DEFAULT 3,
      base_backoff REAL NOT NULL DEFAULT 2.0,
      priority INTEGER NOT NULL DEFAULT 0,
      timeout_seconds INTEGER NULL,
      stdout_log TEXT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      available_at TEXT NOT NULL,
      started_at TEXT NULL,
      finished_at TEXT NULL
    )"""
    )
    # index helpful columns
    c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_state_available ON jobs(state, available_at)")
    conn.commit()

    # attempt to add columns if older schema missing them (safe: ignore errors)
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN timeout_seconds INTEGER NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN stdout_log TEXT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN started_at TEXT NULL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE jobs ADD COLUMN finished_at TEXT NULL")
    except Exception:
        pass
    conn.commit()
    return conn


# Config load/save
def load_config():
    default = {"max_retries": 3, "base_backoff": 2.0, "default_timeout": None}
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(default))
        return default
    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        # ensure keys
        for k, v in default.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return default


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))


# CLI group
@click.group()
def cli():
    init_db()
    load_config()


# ENQUEUE
@cli.command()
@click.argument("job_json")
def enqueue(job_json):
    """
    Enqueue a job with JSON:
    '{"id":"job1","command":"sleep 2","max_retries":3,"base_backoff":2,"priority":1,"run_at":"2025-11-07T12:00:00Z","timeout_seconds":10"}'
    Fields are optional except command.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    data = json.loads(job_json)
    job_id = data.get("id", str(uuid.uuid4()))
    if "command" not in data or not data["command"].strip():
        raise click.BadParameter("job_json must include a non-empty 'command' field")
    command = data["command"]
    max_retries = int(data.get("max_retries", load_config().get("max_retries", 3)))
    base = float(data.get("base_backoff", load_config().get("base_backoff", 2.0)))
    priority = int(data.get("priority", 0))
    timeout_seconds = data.get("timeout_seconds", None)
    # run_at -> available_at (scheduled jobs)
    run_at = data.get("run_at", None)
    if run_at:
        available_at = run_at
    else:
        available_at = now_iso()
    now = now_iso()
    stdout_log = str(LOG_DIR / f"job_{job_id}.log")
    c.execute(
        "INSERT OR REPLACE INTO jobs (id,command,state,attempts,max_retries,base_backoff,priority,timeout_seconds,stdout_log,created_at,updated_at,available_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, command, "pending", 0, max_retries, base, priority, timeout_seconds, stdout_log, now, now, available_at),
    )
    conn.commit()
    click.echo(f"Enqueued job {job_id} (available_at={available_at})")


# STATUS
@cli.command()
def status():
    """Display summary of job counts by state and worker status."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # ensure counts for all known states
    states = ["pending", "processing", "completed", "dead"]
    counts = {}
    total = 0
    for s in states:
        r = c.execute("SELECT COUNT(*) FROM jobs WHERE state=?", (s,)).fetchone()
        cnt = int(r[0]) if r else 0
        counts[s] = cnt
        total += cnt
    if total == 0:
        click.echo("No jobs found.")
        click.echo("All counters: pending=0, processing=0, completed=0, dead=0")
    else:
        for s in states:
            click.echo(f"{s}: {counts[s]}")
    click.echo("Active workers: see worker processes (if running in foreground).")


# LIST
@cli.command(name="list")
@click.option("--state", "state_filter", default=None, help="Filter by state (pending, processing, completed, dead).")
def list_jobs(state_filter):
    """List jobs in the queue, optionally filtered by state."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if state_filter:
        rows = c.execute(
            "SELECT id,command,attempts,max_retries,available_at FROM jobs WHERE state=? ORDER BY created_at",
            (state_filter,),
        ).fetchall()
        if not rows:
            click.echo(f"No jobs in state '{state_filter}'.")
            return
    else:
        rows = c.execute("SELECT id,command,state,attempts,max_retries FROM jobs ORDER BY created_at").fetchall()
        if not rows:
            click.echo("No jobs found.")
            return
    for r in rows:
        click.echo(" | ".join(map(str, r)))


# LOGS
@cli.command("logs")
@click.argument("job_id")
@click.option("--tail", default=30, help="Tail last N lines")
def job_logs(job_id, tail):
    """View logs for a specific job."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    row = c.execute("SELECT stdout_log FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        click.echo("Job not found")
        return
    logpath = row[0]
    click.echo(f"Log path: {logpath}")
    if not logpath or not Path(logpath).exists():
        click.echo("No log file yet.")
        return
    # print last N lines
    with open(logpath, "rb") as f:
        lines = f.read().splitlines()[-tail:]
        for L in lines:
            try:
                click.echo(L.decode(errors="replace"))
            except Exception:
                click.echo(str(L))


# DLQ group
@cli.group()
def dlq():
    """Dead Letter Queue commands"""


@dlq.command("list")
def dlq_list():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    rows = c.execute("SELECT id,command,attempts,max_retries,updated_at FROM jobs WHERE state='dead'").fetchall()
    if not rows:
        click.echo("DLQ is empty.")
        return
    for r in rows:
        click.echo(" | ".join(map(str, r)))


@dlq.command("retry")
@click.argument("job_id")
def dlq_retry(job_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = now_iso()
    c.execute("UPDATE jobs SET state='pending', attempts=0, updated_at=?, available_at=? WHERE id=? AND state='dead'", (now, now, job_id))
    conn.commit()
    click.echo(f"DLQ retry requested for {job_id}")


# CONFIG
@cli.group()
def config():
    """Configuration commands"""


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key, value):
    cfg = load_config()
    try:
        val = int(value)
    except:
        try:
            val = float(value)
        except:
            val = value
    cfg[key] = val
    save_config(cfg)
    click.echo("Config updated")


# METRICS
@cli.command("metrics")
def metrics():
    """Show basic metrics and execution stats"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    total = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    completed = c.execute("SELECT COUNT(*) FROM jobs WHERE state='completed'").fetchone()[0]
    dead = c.execute("SELECT COUNT(*) FROM jobs WHERE state='dead'").fetchone()[0]
    avg_attempts_row = c.execute("SELECT AVG(attempts) FROM jobs WHERE attempts>0").fetchone()
    avg_attempts = float(avg_attempts_row[0]) if avg_attempts_row and avg_attempts_row[0] is not None else 0.0
    durations = c.execute("SELECT started_at, finished_at FROM jobs WHERE started_at IS NOT NULL AND finished_at IS NOT NULL").fetchall()
    total_dur = 0.0
    count_dur = 0
    for s, f in durations:
        try:
            dt_s = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
            dt_f = datetime.datetime.fromisoformat(f.replace("Z", "+00:00"))
            total_dur += (dt_f - dt_s).total_seconds()
            count_dur += 1
        except Exception:
            continue
    avg_duration = (total_dur / count_dur) if count_dur else 0.0
    click.echo(f"Total jobs: {total}")
    click.echo(f"Completed: {completed}")
    click.echo(f"Dead: {dead}")
    click.echo(f"Avg attempts (jobs with attempts): {avg_attempts:.2f}")
    click.echo(f"Avg duration (secs, for completed): {avg_duration:.2f}")


# Worker run control flag
RUN_FLAG = Value("b", True)


def graceful_stop(signum, frame):
    # Called inside worker process
    print("Worker received stop signal; will finish current job then exit.")
    RUN_FLAG.value = False


def start_worker_loop(worker_id, poll_interval=1, idle_timeout=10):
    # This runs in each worker process
    signal.signal(signal.SIGTERM, graceful_stop)
    signal.signal(signal.SIGINT, graceful_stop)
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()

    idle_cycles = 0
    max_idle_cycles = max(1, int(idle_timeout / max(1, poll_interval)))

    while RUN_FLAG.value:
        now = now_iso()
        try:
            # Begin transaction to claim a job atomically
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT id,command,attempts,max_retries,base_backoff,priority,timeout_seconds,stdout_log FROM jobs WHERE state='pending' AND available_at<=? ORDER BY priority DESC, created_at LIMIT 1",
                (now,),
            ).fetchone()
            if not row:
                c.execute("COMMIT")
                idle_cycles += 1
                if idle_cycles >= max_idle_cycles:
                    print(f"[worker {worker_id}] No jobs left — shutting down (idle {idle_timeout}s).")
                    break
                time.sleep(poll_interval)
                continue
            idle_cycles = 0

            job_id, command, attempts, max_retries, base_backoff, priority, timeout_seconds, stdout_log = row
            # Mark as processing (claim)
            claimed = c.execute("UPDATE jobs SET state='processing', updated_at=? WHERE id=? AND state='pending'", (now, job_id)).rowcount
            c.execute("COMMIT")
            if claimed == 0:
                # someone else claimed it
                time.sleep(0.05)
                continue
        except Exception:
            try:
                c.execute("ROLLBACK")
            except Exception:
                pass
            time.sleep(0.1)
            continue

        print(f"[worker {worker_id}] processing {job_id}: {command}")
        # Prepare log file
        logpath = stdout_log or str(LOG_DIR / f"job_{job_id}.log")
        Path(logpath).parent.mkdir(parents=True, exist_ok=True)

        # record started_at
        started = now_iso()
        c.execute("UPDATE jobs SET started_at=?, updated_at=? WHERE id=?", (started, started, job_id))
        conn.commit()

        # Execute command, capture output to file, handle timeout
        rc = 1
        try:
            with open(logpath, "ab") as out_f:
                out_f.write(f"--- START {now_iso()} ---\n".encode())
                out_f.flush()
                # ensure timeout_seconds is an int or None
                tsec = None
                try:
                    if timeout_seconds is not None:
                        tsec = int(timeout_seconds)
                except Exception:
                    tsec = None

                # run
                res = subprocess.run(command, shell=True, stdout=out_f, stderr=out_f, timeout=tsec)
                rc = res.returncode
                out_f.write(f"\n--- END {now_iso()} rc={rc} ---\n".encode())
        except subprocess.TimeoutExpired:
            # treat as failure attempt
            rc = 1
            with open(logpath, "ab") as out_f:
                out_f.write(f"\n--- TIMEOUT {now_iso()} after {timeout_seconds}s ---\n".encode())
        except Exception as e:
            rc = 1
            with open(logpath, "ab") as out_f:
                out_f.write(f"\n--- EXCEPTION {now_iso()} {repr(e)} ---\n".encode())

        # record finished_at
        finished = now_iso()
        c.execute("UPDATE jobs SET finished_at=?, updated_at=? WHERE id=?", (finished, finished, job_id))

        now2 = now_iso()
        if rc == 0:
            c.execute("UPDATE jobs SET state='completed', updated_at=? WHERE id=?", (now2, job_id))
            print(f"[worker {worker_id}] completed {job_id}")
        else:
            attempts = attempts + 1
            if attempts >= max_retries:
                c.execute("UPDATE jobs SET state='dead', attempts=?, updated_at=? WHERE id=?", (attempts, now2, job_id))
                print(f"[worker {worker_id}] job {job_id} moved to DLQ after {attempts} attempts")
            else:
                delay = (base_backoff ** attempts)
                next_avail_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delay)
                next_avail = next_avail_dt.isoformat().replace("+00:00", "Z")
                c.execute("UPDATE jobs SET state='pending', attempts=?, updated_at=?, available_at=? WHERE id=?", (attempts, now2, next_avail, job_id))
                print(f"[worker {worker_id}] job {job_id} failed; will retry after {delay}s (attempt {attempts})")

        # tiny sleep to avoid tight loop
        time.sleep(0.1)


# Worker group
@cli.group()
def worker():
    """Worker management commands"""


_worker_processes = []


@worker.command("start")
@click.option("--count", default=1, help="Number of worker processes to start (runs in foreground).")
@click.option("--idle-timeout", default=3, help="Seconds of idle time with no pending jobs after which workers exit.")
def worker_start(count, idle_timeout):
    """
    Start N worker processes in the foreground.
    Note: this command blocks. Use Ctrl+C to stop and it will attempt a graceful shutdown.
    """
    global _worker_processes
    init_db()
    click.echo(f"Starting {count} worker(s) in foreground... (idle-timeout={idle_timeout}s)")
    for i in range(count):
        p = Process(target=start_worker_loop, args=(i + 1, 1, idle_timeout))
        p.start()
        _worker_processes.append(p)

    try:
        while True:
            alive = [p.is_alive() for p in _worker_processes]
            if not any(alive):
                break
            time.sleep(1)
    except KeyboardInterrupt:
        click.echo("Stopping workers (main received KeyboardInterrupt). Sending terminate.")
        for p in _worker_processes:
            p.terminate()
        for p in _worker_processes:
            p.join()


@worker.command("stop")
def worker_stop():
    """
    This simple CLI spawns workers in foreground. If you ran workers in background (nohup),
    stop them externally, e.g., `pkill -f "python queuectl.py worker start"`.
    """
    click.echo("If workers are running in background, stop them externally (e.g., pkill).")


# RESET command - safely stop workers, backup DB, remove DB/journals and reinitialize
@cli.command("reset")
@click.confirmation_option(prompt="Are you sure you want to delete all jobs and reset the queue?")
def reset_queue():
    """Delete all jobs and reset queue database (use carefully)."""
    click.echo("Attempting to stop background workers (if any)...")
    # best-effort stop background workers that were run via nohup
    try:
        subprocess.run(["pkill", "-f", "queuectl.py worker start"], check=False)
    except Exception:
        pass
    time.sleep(0.5)

    # backup current DB & logs
    backup_dir = ROOT / f"backup_{int(time.time())}"
    backup_dir.mkdir(exist_ok=True)
    if DB_PATH.exists():
        try:
            shutil.copy2(DB_PATH, backup_dir / "queue.db.bak")
            click.echo(f"Backed up queue.db -> {backup_dir}")
        except Exception:
            click.echo("Failed to backup queue.db; proceeding anyway.")
    # backup logs
    logs_dir = ROOT / "logs"
    if logs_dir.exists():
        try:
            shutil.copytree(logs_dir, backup_dir / "logs", dirs_exist_ok=True)
            click.echo(f"Backed up logs -> {backup_dir}")
        except Exception:
            pass

    # remove DB and journals
    for f in ["queue.db", "queue.db-wal", "queue.db-shm"]:
        try:
            (ROOT / f).unlink(missing_ok=True)
        except Exception:
            pass
    # remove logs and demo worker output
    try:
        if logs_dir.exists():
            shutil.rmtree(logs_dir)
    except Exception:
        pass
    try:
        (ROOT / "demo" / "worker.out").unlink(missing_ok=True)
    except Exception:
        pass

    click.echo("Reset complete. Reinitializing database...")
    init_db()
    click.echo("Database recreated. Run 'python3 queuectl.py status' to verify.")


if __name__ == "__main__":
    cli()

