<h2>Overview</h2>
<p>
  QueueCTL is a lightweight, CLI-first job queue built in Python. It focuses on reliability and clarity, making it suitable for demos rather than handling large-scale operations. Jobs consist of shell commands stored in SQLite. Worker processes take on and execute these jobs, manage retries with increasing delays, and move permanently failed jobs to a Dead Letter Queue (DLQ). The system focuses on predictable behavior, easy testing, and straightforward monitoring.
</p>

<h3>Key Components</h3>
<ul>
  <li>
    <strong>CLI (queuectl.py):</strong>
    This is the user interface, built with Click, for adding jobs, starting and stopping workers, checking the queue, managing DLQ operations, configuring settings, tracking metrics, and resetting the system.
  </li>
  <li>
    <strong>Persistence (SQLite):</strong>
    The queue is stored in a single file, <code>queue.db</code>, with Write-Ahead Logging (WAL) mode recommended. The main table holds jobs, while an optional table can store worker heartbeats.
  </li>
  <li>
    <strong>Worker processes:</strong>
    These are independent processes using multiprocessing to claim jobs, execute commands, record logs, update job statuses, and manage retries with backoff.
  </li>
  <li>
    <strong>Per-job logs:</strong>
    Each job records its standard output and errors, along with lifecycle markers, in <code>logs/job_&lt;id&gt;.log</code>.
  </li>
  <li>
    <strong>Demo &amp; Tests:</strong>
    There is an automated demo script (<code>demo/demo.sh</code>) and a pytest suite that checks core functions such as success, retry moving to DLQ, priority, and scheduling.
  </li>
</ul>

<h3>Job Record (core fields)</h3>
<p>Each job record contains the fields:</p>
<pre>
{
  "id": "unique-job-id",
  "command": "echo 'Hello World'",
  "state": "pending",
  "attempts": 0,
  "max_retries": 3,
  "base_backoff": 2.0,
  "priority": 0,
  "timeout_seconds": null,
  "created_at": "2025-11-04T10:30:00Z",
  "updated_at": "2025-11-04T10:30:00Z",
  "available_at": "2025-11-04T10:30:00Z",
  "stdout_log": "logs/job_unique-job-id.log"
}
</pre>
<p>Store timestamps in ISO 8601 UTC (...Z) and keep available_at for scheduled/delayed jobs.</p>

<h3>Job lifecycle (step-by-step)</h3>
<ul>
  <li><strong>Enqueue</strong> — insert job with:
    <ul>
      <li>state = <code>pending</code></li>
      <li><code>available_at = now</code> (or <code>run_at</code> if scheduled)</li>
      <li><code>attempts = 0</code></li>
    </ul>
  </li>
  <li><strong>Claim</strong> — a worker:
    <ul>
      <li>starts a transaction</li>
      <li>selects one eligible pending job (<code>available_at <= now</code>)</li>
      <li>orders by <code>priority DESC</code>, then <code>created_at</code></li>
      <li>updates job state to <code>processing</code> to prevent duplicates</li>
    </ul>
  </li>
  <li><strong>Execute</strong> — run the command in a shell:
    <ul>
      <li>capture <code>stdout</code>/<code>stderr</code> into the job log file</li>
      <li>enforce <code>timeout_seconds</code> if provided</li>
    </ul>
  </li>
  <li><strong>Complete / Fail</strong>
    <ul>
      <li><strong>Success (rc == 0):</strong> set state to <code>completed</code> and update <code>finished_at</code>.</li>
      <li><strong>Failure (rc != 0 or timeout):</strong>
        <ul>
          <li>increment <code>attempts</code></li>
          <li>if <code>attempts >= max_retries</code>, set state to <strong>dead (DLQ)</strong></li>
          <li>otherwise:
            <ul>
              <li>compute <code>delay = base_backoff ^ attempts</code></li>
              <li>set <code>available_at = now + delay</code></li>
              <li>set state to <code>pending</code> (retry later)</li>
            </ul>
          </li>
        </ul>
      </li>
    </ul>
  </li>
  <li><strong>DLQ</strong> — dead jobs are shown via CLI and may be retried using:
    <ul>
      <li><code>queuectl dlq retry &lt;id&gt;</code></li>
      <li>This resets <code>attempts</code>, <code>available_at</code>, and <code>state = pending</code>.</li>
    </ul>
  </li>
</ul>
<p align="center">
  <img width="300" height="450" alt="design" src="https://github.com/user-attachments/assets/9a3a7710-36dc-437c-82ca-03477cf85074" />
</p>

<h3>Concurrency &amp; Safety</h3>
<ul>
  <li><strong>Atomic job claim:</strong> uses a DB transaction (<code>BEGIN IMMEDIATE</code>) and 
      <code>UPDATE ... WHERE state='pending'</code> to ensure only one worker claims a job.</li>
  <li><strong>SQLite WAL:</strong> enable <code>PRAGMA journal_mode=WAL</code> to improve concurrency 
      for multiple readers and writers.</li>
  <li><strong>Graceful shutdown:</strong> workers catch <code>SIGINT</code> and <code>SIGTERM</code>, 
      finish their current job, and exit cleanly, preventing partial executions.</li>
  <li><strong>File-safe logging:</strong> workers append to per-job log files. The DB stores each log path, 
      and log writes are sequential per worker.</li>
</ul>

<h3>Retry &amp; Exponential Backoff</h3>
<ul>
  <li><strong>Formula:</strong> <code>delay_seconds = base_backoff ** attempts</code><br>
      Example: base = 2 → attempts 1 → 2s, attempts 2 → 4s.</li>
  <li><strong>max_retries:</strong> can be per job or a global default. Jobs move to the DLQ only after retries are exhausted.</li>
</ul>

<h3>Scheduling &amp; Priority</h3>
<ul>
  <li><strong>Scheduled jobs:</strong> set <code>run_at</code> (ISO8601 UTC) during enqueue and store it as <code>available_at</code>.  
      Workers select only jobs where <code>available_at &lt;= now</code>.</li>
  <li><strong>Priority:</strong> integer value; workers use  
      <code>ORDER BY priority DESC, created_at</code>  
      so higher priority jobs run first.</li>
</ul>

<h3>Observability &amp; Metrics</h3>
<ul>
  <li><strong>Per-job logs:</strong> logs include markers such as  
      <code>--- START TIMESTAMP ---</code> and  
      <code>--- END TIMESTAMP rc=X ---</code>,  
      plus timeout and exception entries.</li>
  <li><strong>Metrics command:</strong> <code>queuectl metrics</code> aggregates:
    <ul>
      <li>total jobs,</li>
      <li>completed jobs,</li>
      <li>dead jobs,</li>
      <li>average attempts,</li>
      <li>average job duration (started_at → finished_at).</li>
    </ul>
  </li>
</ul>

<h3>Testing &amp; Demo</h3>
<ul>
  <li><strong>Automated tests (pytest):</strong> <code>pytest -v</code> covers:
    <ul>
      <li>successful job execution,</li>
      <li>failing job → retries → DLQ,</li>
      <li>priority ordering,</li>
      <li>scheduled job behavior,</li>
      <li>persistence across restarts.</li>
    </ul>
  </li>

  <li><strong>Demo script:</strong> <code>demo/demo.sh</code> runs a reproducible scenario that enqueues success and failing jobs, 
      starts the worker, and captures outputs.</li>
</ul>
