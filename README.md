# queuectl - CLI-Based Background Job Queue System

<h2>1. Setup Instructions</h2>  
<h3>Requirements</h3>
<ul>
  <li>Python 3.9+</li>
  <li>pip package manager</li>
  <li>WSL / Linux / macOS (for concurrency and SQLite support)</li>
</ul>

<h3>Install dependencies</h3>

```bash
git clone https://github.com/dhikshanya06/queuectl.git

cd queuectl

python3 -m venv venv        #create virtual environment

source venv/bin/activate    #on Windows: venv\Scripts\activate
 
pip install -r requirements.txt
```

<h3>Run Locally or Install Globally</h3>

You can run the CLI tool directly using Python:
```bash
python3 queuectl.py status
```
Or, make it accessible system-wide (so you can just type queuectl from anywhere):
```bash
chmod +x queuectl.py

sudo ln -s "$(pwd)/queuectl.py" /usr/local/bin/queuectl

queuectl status
```

<h2>2. Usage Examples</h2>  
<h3>Enqueue</h3>
Add a new job to the queue (JSON string; command required; other fields optional).

```bash
queuectl enqueue '{"id":"job1","command":"sleep 2"}'
```
Output:<br>
<p align="center">
  <img width="1870" height="89" alt="image" src="https://github.com/user-attachments/assets/de673f45-bca6-442e-9a46-49b489239490" />
</p>

You can also override retry/backoff/priority or schedule:
```bash
queuectl enqueue '{"id":"job2","command":"echo hello","max_retries":5,"base_backoff":2.0,"priority":10,"run_at":"2025-11-07T18:00:00Z"}'
```
Output:<br>
<p align="center">
  <img width="1876" height="89" alt="image" src="https://github.com/user-attachments/assets/6c7c3c1d-c562-4ec0-af4f-06cfe774bb43" />
</p>

<h3>Start workers</h3>
Start N worker processes in the foreground. Workers will automatically exit after --idle-timeout seconds if there are no pending jobs.

```bash
queuectl worker start --count 3 --idle-timeout 3
```
Output:<br>
<p align="center">
  <img width="1873" height="261" alt="image" src="https://github.com/user-attachments/assets/a8d1d1c1-2069-4f63-b666-33b64356194d" />
</p>
What it does:
<ul>
  <li>It spawns 3 worker processes that handle jobs at the same time.</li>
  <li>Each worker completes its current job when it receives <code>SIGINT</code> or <code>SIGTERM</code> for a graceful shutdown.</li>
  <li>If the queue remains idle for the specified <code>idle-timeout</code> seconds, the workers exit automatically.</li>
</ul>

<h3>Stop workers</h3>
If you started workers in the foreground, press Ctrl+C to request a graceful shutdown.
If you started workers in the background (nohup or systemd), stop them externally.

```bash
# Foreground stop (same terminal)
Ctrl + C

# Background stop (best-effort)
pkill -f "queuectl worker start"
```

<h3>Status/Reset</h3>
Status - show queue summary <br>
Show a summary count of jobs by state. Include a note about active workers:

```bash
queuectl status
```
Output:<br>
Non-empty queue example<br>
<p align="center">
  <img width="1872" height="192" alt="image" src="https://github.com/user-attachments/assets/2cb3952a-2ca3-40b6-b8b3-67a056da1b7a" />
</p>
<ul>
  <li>Print counts for <strong>pending</strong>, <strong>processing</strong>, <strong>completed</strong>, and <strong>dead</strong> jobs.</li>
  <li>Print a brief note about <strong>active workers</strong>, focusing on <strong>foreground workers only</strong>.</li>
</ul>

Reset — reinitialize database (safe, with backup) <br>
Safely resets the queue by backing up the database and logs, removing the database files and logs, and recreating an empty database. Confirmation is required.
```bash
queuectl reset
```
Empty queue example
<p align="center">
  <img width="1874" height="360" alt="image" src="https://github.com/user-attachments/assets/94693803-43b7-4b9f-a987-1e5fc9bd469d" />
</p>
<ul>
  <li>Attempts to stop background workers.</li>
  <li>Backs up <code>queue.db</code> and <code>logs/</code> to a <code>backup_&lt;timestamp&gt;/</code> folder.</li>
  <li>Deletes <code>queue.db</code>, journal files (<code>queue.db-wal</code>, <code>queue.db-shm</code>), and <code>logs/</code>.</li>
  <li>Recreates an empty database.</li>
  <li>After the reset, run <code>queuectl status</code> to check the empty state.</li>
</ul>

<h3>List jobs</h3>
List jobs, which you can filter by state: pending, processing, completed, dead:
If you just ran queuectl reset, the queue will be empty. You can add a few sample jobs first to see the output:

```bash
queuectl enqueue '{"id":"job1","command":"echo Hello"}'
queuectl enqueue '{"id":"job2","command":"sleep 2"}'
```
Then list jobs:
```bash
queuectl list
```
<ul>
  <li>You can also view all jobs, no matter the state.</li>
</ul>
Output:<br>
<p align="center">
  <img width="1876" height="107" alt="Screenshot 2025-11-08 162715" src="https://github.com/user-attachments/assets/4f5b29d3-271b-40d7-9dd7-3dbe2715d437" />
</p>
  
```bash
queuectl list --state pending
```
Output:<br>
<p align="center">
  <img width="1876" height="114" alt="image" src="https://github.com/user-attachments/assets/298d4afb-c0a2-4d54-8832-61380068fc77" />
</p>

<h3>Dead Letter Queue (DLQ)</h3>
The Dead Letter Queue (DLQ) holds jobs that have permanently failed. This includes commands that did not succeed, even after all retry attempts.
<ul>
  <li>Move a job to <strong>DLQ</strong> (simulate a failure).</li>
  <li>You can enqueue a job that will fail intentionally. For example, use a fake command name:</li>
</ul>

```bash
queuectl enqueue '{"id":"failjob","command":"no_such_command","max_retries":2,"base_backoff":2}'
```
Start a worker to process jobs:
```bash
queuectl worker start --count 1
```
Output:<br>
<p align="center">
  <img width="1873" height="313" alt="image" src="https://github.com/user-attachments/assets/c7570667-94b4-48fe-8344-a3a7afa4b1a0" />
</p>
View jobs in DLQ:
Output:<br>
<p align="center">
  <img width="1873" height="99" alt="image" src="https://github.com/user-attachments/assets/a4c4987e-2bb7-419c-8c99-92b89834c32a" />
</p>

<h3>Retry a DLQ job</h3>
To retry a failed job, move it back to pending and reset the attempts to 0.

```bash
queuectl dlq retry failjob
```
Output:<br>
<p align="center">
  <img width="1873" height="83" alt="image" src="https://github.com/user-attachments/assets/3876d060-ab3c-4e07-b748-f64ef980cd63" />
</p>
You can verify:

```bash
queuectl list --state pending
```
Output:<br>
<p align="center">
  <img width="1868" height="91" alt="image" src="https://github.com/user-attachments/assets/b80c363f-4faf-45c0-ab62-68a05683d7e0" />
</p>
<ul>
  <li><strong>DLQ</strong> jobs move there after all retries fail, based on <code>max_retries</code>.</li>
  <li>Retried jobs go back to <strong>pending</strong>. They will be reprocessed automatically when a worker is running.</li>
  <li>To prevent endless loops, always check the job's <code>command</code> before retrying.</li>
</ul>

<h3>Logs (per-job)</h3>
Show the captured stdout and stderr for a job. Here are the last N lines:

```bash
queuectl logs job1 --tail 50
```
Output:<br>
<p align="center">
  <img width="1875" height="195" alt="image" src="https://github.com/user-attachments/assets/eaccc4b9-6544-495c-90b5-c741f6bcb935" />
</p>

<h3>Config (global defaults)</h3>
Set global defaults (persisted in queue_config.json):

```bash
python3 queuectl.py config set max_retries 5
python3 queuectl.py config set base_backoff 3.0
```
Output:<br>
<p align="center">
  <img width="1876" height="168" alt="image" src="https://github.com/user-attachments/assets/d872d58c-80fe-46a9-8b5a-be1318f06553" />
</p>
<ul>
  <li>These values apply to new jobs unless changed for specific jobs.</li>
</ul>

<h3>Metrics</h3>
Show basic metrics and execution stats.

```bash
queuectl metrics
```
Output:<br>
<p align="center">
  <img width="1874" height="181" alt="image" src="https://github.com/user-attachments/assets/91fbc297-f014-47ad-a2b4-eb6959d894d4" />
</p>

<h2>Architecture Overview</h2>
<h3>Job Lifecycle</h3>
Each job moves through these states: <br>
<pre>
  pending → processing → completed
              ↓
            retry (with backoff)
              ↓
             dead (DLQ)
</pre>
<ul>
  <li><strong>pending</strong> — job is waiting for a worker.</li>
  <li><strong>processing</strong> — currently being executed.</li>
  <li><strong>completed</strong> — command succeeded (<code>exit code 0</code>).</li>
  <li><strong>dead (DLQ)</strong> — failed after all retries.</li>
</ul>

<h3>Retry & Exponential Backoff</h3>
If a job fails, it retries automatically after a delay:
<pre>delay = base_backoff ^ attempts</pre>
Example: If base_backoff = 2, retries happen after 2s, 4s, 8s, etc. <br>
After exceeding max_retries, the job moves to the Dead Letter Queue (DLQ).

<h3>Data Persistence</h3>
<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr>
      <th>Component</th>
      <th>File</th>
      <th>Description</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Database</strong></td>
      <td><code>queue.db</code></td>
      <td>Stores all jobs, their states, timestamps, and logs path.</td>
    </tr>
    <tr>
      <td><strong>Config</strong></td>
      <td><code>queue_config.json</code></td>
      <td>Global settings (retries, backoff, timeout).</td>
    </tr>
    <tr>
      <td><strong>Logs</strong></td>
      <td><code>logs/job_&lt;id&gt;.log</code></td>
      <td>Individual job logs (stdout + stderr).</td>
    </tr>
    <tr>
      <td><strong>Backup</strong></td>
      <td><code>backup_&lt;timestamp&gt;/</code></td>
      <td>Created automatically during <code>queuectl reset</code>.</td>
    </tr>
  </tbody>
</table>
Data in queue.db is persistent — it survives restarts.

<h3>Worker Logic</h3>
<h4>Each worker process:</h4>
<ul>
  <li>Claims a pending job (<code>BEGIN IMMEDIATE + UPDATE state='processing'</code>).</li>
  <li>Executes the job’s command (<code>subprocess.run()</code>).</li>
  <li>Writes output to its log file.</li>
  <li>Updates the job state:
    <ul>
      <li>Success leads to <strong>completed</strong></li>
      <li>Failure leads to <strong>retry</strong> (pending again) or <strong>DLQ</strong></li>
    </ul>
  </li>
</ul>
Multiple workers can run simultaneously:

```bash
queuectl worker start --count 3
```
SQLite’s locking makes sure that only one worker takes each job. There are no duplicates.

<h3>Graceful Shutdown</h3>
<ul>
  <li>If a worker receives <code>Ctrl+C</code> or a system signal, it finishes the current job before exiting.</li>
  <li>This prevents partial processing or duplicate retries.</li>
  <li>Workers also stop automatically after an idle timeout if no jobs remain.</li>
</ul>

<h3>Scheduling, Priority & Timeout</h3>
<ul>
  <li><code>run_at</code> → schedule job for a specific time.</li>
  <li><code>priority</code> → higher value = processed first.</li>
  <li><code>timeout_seconds</code> → abort long-running jobs automatically.</li>
</ul>

<h3>CLI → Architecture Mapping</h3>
<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr>
      <th>Command</th>
      <th>Action</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>queuectl enqueue</code></td>
      <td>Inserts new job into DB.</td>
    </tr>
    <tr>
      <td><code>queuectl worker start</code></td>
      <td>Starts N worker processes.</td>
    </tr>
    <tr>
      <td><code>queuectl status</code></td>
      <td>Summarizes job states.</td>
    </tr>
    <tr>
      <td><code>queuectl list --state pending</code></td>
      <td>Lists jobs by state.</td>
    </tr>
    <tr>
      <td><code>queuectl dlq list</code></td>
      <td>View failed (dead) jobs.</td>
    </tr>
    <tr>
      <td><code>queuectl dlq retry &lt;id&gt;</code></td>
      <td>Retry DLQ job.</td>
    </tr>
    <tr>
      <td><code>queuectl logs &lt;id&gt;</code></td>
      <td>View job log output.</td>
    </tr>
    <tr>
      <td><code>queuectl reset</code></td>
      <td>Backup + reset the entire queue.</td>
    </tr>
  </tbody>
</table>

<h2>Assumptions & Trade-offs</h2>
<h3>Assumptions</h3>
<ul>
  <li>The system runs locally on a single machine and uses <code>SQLite</code> as the job store.</li>
  <li>Each job is independent and executes a valid shell command, such as <code>echo</code> or <code>sleep</code>.</li>
  <li>Job success or failure is determined only by the process exit code.</li>
  <li>The CLI operates in a trusted local environment with no user authentication.</li>
  <li>Workers process jobs one at a time for each process, and multiple processes run at the same time.</li>
  <li>The configuration file, <code>queue_config.json</code>, is edited or updated manually through the CLI, not dynamically.</li>
</ul>

<h3>Design Decisions</h3>
<table border="1" cellspacing="0" cellpadding="6">
  <thead>
    <tr>
      <th>Component</th>
      <th>Choice</th>
      <th>Rationale</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><strong>Storage</strong></td>
      <td>SQLite database (<code>queue.db</code>)</td>
      <td>Lightweight, persistent, portable.</td>
    </tr>
    <tr>
      <td><strong>Parallelism</strong></td>
      <td>Multiprocessing workers</td>
      <td>True concurrency, avoids GIL limitation.</td>
    </tr>
    <tr>
      <td><strong>Logging</strong></td>
      <td>Per-job log files in <code>logs/</code></td>
      <td>Simple debugging and audit trail.</td>
    </tr>
    <tr>
      <td><strong>Retry Logic</strong></td>
      <td>Exponential backoff (<code>base_backoff ^ attempts</code>)</td>
      <td>Smooth retry delays under failures.</td>
    </tr>
    <tr>
      <td><strong>Queue Reset</strong></td>
      <td>Backup + reinitialization</td>
      <td>Safe way to clear all data for testing.</td>
    </tr>
    <tr>
      <td><strong>Graceful Shutdown</strong></td>
      <td>Finish current job before exit</td>
      <td>Prevents data loss or duplicate execution.</td>
    </tr>
  </tbody>
</table>

<h3>Trade-offs & Simplifications</h3>
<ul>
  <li><strong>SQLite Limitations</strong> — concurrency is suitable only for small workloads.</li>
  <li><strong>No distributed capability</strong> — all workers must share the same local filesystem.</li>
  <li><strong>Manual worker control</strong> — workers are started and stopped via CLI (<code>Ctrl+C</code> or <code>pkill</code>).</li>
  <li><strong>No job dependencies or workflows</strong> — each job runs independently.</li>
  <li><strong>Metrics via CLI only</strong> — there is no live dashboard or monitoring UI.</li>
  <li><strong>Static configuration</strong> — any config change takes effect on the next run.</li>
</ul>

<h2>Testing Instructions</h2>
<h3>Initialize Environment</h3>

```bash
queuectl reset
queuectl status
```
<ul>
  <li>Ensures a clean database with all counters set to 0.</li>
</ul>

<h3>Enqueue Sample Jobs</h3>

```bash
queuectl enqueue '{"id":"job-ok","command":"echo Hello"}'
queuectl enqueue '{"id":"job-fail","command":"no_such_cmd","max_retries":2}'
```
<ul>
  <li>Adds one successful and one intentionally failing job.</li>
</ul>

<h3>Start Worker</h3>

```bash
queuectl worker start --count 1
```
<ul>
  <li>Processes jobs one after the other.</li>
  <li>Displays progress: completed, retried, or moved to <strong>DLQ</strong>.</li>
  <li>Shows <code>"Press Ctrl+C to stop"</code> message for manual shutdown.</li>
</ul>

<h3>Check Job States</h3>

```bash
queuectl status
```
```bash
queuectl list --state completed
```
```bash
queuectl list --state dead
```
<ul>
  <li>Confirms completed and failed (DLQ) jobs are tracked correctly.</li>
</ul>

<h3>Retry from DLQ</h3>

```bash
queuectl dlq list
```
```bash
queuectl dlq retry job-fail
```
<ul>
  <li>Moves failed job back to pending state for reprocessing.</li>
</ul>

<h3>View Job Logs</h3>

```bash
queuectl logs job-ok
```
<ul>
  <li>Displays per-job output stored under logs/.</li>
</ul>

<h3>Verify Persistence</h3>
Restart the program and check if jobs persist:

```bash
queuectl status
```
<ul>
  <li>Ensures data remains intact even after script restart.</li>
</ul>

<h2>Run Automated Tests</h2>

```bash
pytest -v
```
<ul><li>Executes predefined test cases validating enqueue, retry, DLQ, and metrics logic.</li></ul>
Output:<br>
<p align="center">
  <img width="1888" height="393" alt="image" src="https://github.com/user-attachments/assets/170c4a8a-49f7-4a7e-91db-56b32459c9b6" />
</p>
<ul>
  <li>All tests passing and correct job state transitions confirm a fully functional queue system.</li>
</ul>
