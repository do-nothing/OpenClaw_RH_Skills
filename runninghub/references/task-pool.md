# Task Pool (batch / async workflows)

For **batch submission** or **long-running workflows**, use the task pool instead of
blocking on a single script call. It submits many jobs, runs them within a
concurrency budget, and downloads results.

The pool code is host-agnostic. **The enqueue flag selects the runner — you do
not choose a mode in prose:**

| Host | enqueue flag | Runner | Completion |
|------|--------------|--------|------------|
| **openclaw** | `--openclawSessionKey <session>` | polling automation (zero LLM) + immediate first tick | session is **woken by CLI** when the batch drains |
| **any other host** (Trae, DeepSeek harness, unknown shells) | *(no flag)* | detached background **watcher**, auto-started by enqueue | process exits at drain; **no wake-up** — reconcile when the user returns |

Script: `python3 {baseDir}/scripts/rh_pool/pool.py`

## Batches (internal)

Batches need no flag and are invisible in the enqueue interface: while any job
is still outstanding (PENDING/DISPATCHED), every new enqueue **joins the open
batch**; after the pool drains, the next enqueue opens a new one. So one batch
= "everything submitted while the pool was busy". Batch state is derived from
task rows (no open/close to break), survives crashes, and scopes the
drain-time wake-up: only the drained batch's sessions are woken/cleared.

- enqueue response and `status` report `batchId` / `currentBatchId`
- `status` per task also shows `rh_status` — RunningHub's live remote status
  (QUEUED → RUNNING → SUCCESS/FAILED), written on every poll

## When to use

**Any workflow task goes here — a single one counts.** Do not look for a
standard-API endpoint for 语音克隆 / 数字人 / 文生图 workflows.

- User asks for a **workflow type** (语音克隆 / 数字人 / 文生图, any single job)
- User wants **several generations** at once ("跑 3 个", "批量", "都生成一遍")
- A task is **slow** and the user keeps chatting (video / digital human / 3D / music)
- User asks for **progress** on submitted work

The standard-API single-task flow in `SKILL.md` is only for endpoints that are
not pool workflow types.

## Task types

Named types live in `config/task-types.json` (shipped with the skill). Each
type maps friendly params to a workflow's node inputs.

```bash
# what is available / validate against archived workflow exports
python3 {baseDir}/scripts/rh_pool/pool.py workflow list
python3 {baseDir}/scripts/rh_pool/pool.py workflow validate
```

A type's file params accept **a local path** (uploaded automatically, cached),
an `api/...` id, or a URL.

## Output locations and names

- **Default:** inside the skill's pool home,
  `data/pool/output/batch-<batchId>/<poolId>_<nodeId>_<idx>.<ext>` —
  persistent on every host (does not depend on system temp cleanup), grouped
  per batch. Missing parent dirs are created automatically.
- **Real projects:** give each job its own `outputDir` (no batch subdir is
  added) and optional `outputName` (basename **without extension**; the real
  extension comes from the result). Multiple results get `_0`, `_1` suffixes;
  rerunning a job overwrites. Jobs in one batch may use different dirs/names:

```json
[
  {"type": "image-edit-banana2", "params": {"prompt": "beat 1 wide"},
   "outputDir": "D:/film/keyframes", "outputName": "kf_1a"},
  {"type": "digital-human",
   "params": {"image": "D:/film/keyframes/kf_1a.png", "audio": "D:/film/a.m4a", "text": "..."},
   "outputDir": "D:/film/clips", "outputName": "clip_1a"}
]
```

CLI equivalents: `--output-dir DIR` (default for every job in `--from-file`,
overridable per job) and `--output-name NAME` (single-job enqueue).

## Submit — Mode A: openclaw

Take the session key verbatim from the **`session=` field of your runtime
context** and pass it as a plaintext flag (there is no environment variable):

```bash
# one type
python3 {baseDir}/scripts/rh_pool/pool.py enqueue \
  --openclawSessionKey "agent:main:xxxx" \
  --type music-minimax --param prompt="lo-fi chill beats, soft piano"

# a batch from a file (list of jobs)
python3 {baseDir}/scripts/rh_pool/pool.py enqueue \
  --openclawSessionKey "agent:main:xxxx" --from-file jobs.json
```

`jobs.json`:
```json
[
  {"type": "music-minimax", "params": {"prompt": "..."}},
  {"type": "voice-clone-emo", "params": {"text": "...", "referenceAudio": "/path/ref.m4a"}},
  {"type": "digital-human", "params": {"image": "/path/p.jpg", "audio": "/path/a.m4a", "text": "..."}}
]
```

What enqueue does for you: creates (or reuses) one global polling automation,
then fires one immediate tick so the batch starts within ~1s instead of waiting
for the first 30s boundary. The JSON response contains `"mode": "openclaw"`,
`"automation"` and `"kick"`.

- **Your turn ends after submit.** Tell the user work started, then stop — do
  NOT poll `status`, sleep, or wait in-loop.
- When the batch drains, the automation wakes exactly the session whose key
  you passed, then removes itself (one wake-up per batch). When you are woken:
  run `pool.py outputs --batch-id <batchId>` using the **batchId from the
  enqueue response** (prefer it over `--latest` — a newer batch may already be
  running). It prints the `BATCH:` header with per-state counts, every
  `OUTPUT_FILE:`, aggregated `COINS:`/`COST:`/`THIRD_PARTY:`, max `DURATION:`,
  and one `ERROR:<poolId>: …` per failure. Then deliver exactly per
  `references/output-delivery.md` — on openclaw that means the `message` tool
  and the cost-reporting rules there. One task's detail:
  `status --pool-id <id> --lines`.
- **Errors are reported, never auto-degraded.** If the response shows
  `automation.action == "error"` or `kick.action == "failed"` (the command
  exits non-zero), tell the user what went wrong verbatim — do NOT retry as
  Mode B or start a watcher yourself. The jobs are still safely queued.

## Submit — Mode B: generic hosts (no openclaw)

Enqueue with **no mode flag** — the detached watcher is started automatically,
so there is no second command to run:

```bash
# one type
python3 {baseDir}/scripts/rh_pool/pool.py enqueue \
  --type image-gen-qwen --param prompt="江南水乡，水彩风格"

# a batch from a file (list of jobs)
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --from-file jobs.json
```

The JSON response contains `"mode": "watch"` and `"watcher": {"action":
"issued"}`. The watcher ticks immediately, then every `pollIntervalSeconds`,
and exits when the pool is fully drained (exit code 0). If a new batch is
opened in the drain window, it keeps ticking instead of exiting — appended
work is never stranded. If the watcher fails to start (`"action": "failed"`,
non-zero exit), report the error to the user verbatim — do not improvise
another polling scheme.

**Empirical limitation — do NOT promise auto wake-up.** On non-openclaw hosts
the watcher's process-exit event does NOT start a new agent turn for
minute-scale jobs; it is injected into the conversation only along with the
user's next message. Therefore:

1. After enqueue, tell the user honestly, e.g. "开始生成啦，完成后你回来发任意
   一句话，我立刻查收并交付～", then end your turn. Never poll or sleep yourself.
2. Whenever the user returns (a completion event may be attached to their
   message), your **first** action is `pool.py status`. Deliver only when
   `currentBatchId` is null (drained); if jobs remain, report progress and
   end the turn.
3. Once drained, run `pool.py outputs --batch-id <batchId>` (the batchId from
   the enqueue response; use `--latest` only if you do not have it) and
   deliver the `OUTPUT_FILE:` paths as **clickable absolute file links**
   (generic-host column of `references/output-delivery.md`), reporting the
   aggregated non-zero `COINS:` / `COST:` / `THIRD_PARTY:` lines per the cost
   rules. Never paste RunningHub internal URLs. One task's detail:
   `status --pool-id <id> --lines`.
4. If the host/IDE was restarted while jobs were in flight, first run
   `pool.py reconcile` (resync states + download finished outputs); if anything
   is still outstanding, restart a watcher in the background with
   `python3 {baseDir}/scripts/rh_pool/notify.py watch`.

## Manual enqueue (testing / debugging)

`--manual` queues jobs and starts **nothing** — no automation, no watcher:

```bash
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --manual --type image-gen-qwen --param prompt="..."
```

Advance the pool yourself with `pool.py tick` (one step). Never use `--manual`
in normal user-facing operation.

## Check progress

```bash
python3 {baseDir}/scripts/rh_pool/pool.py status              # currentBatchId + counts + recent tasks
python3 {baseDir}/scripts/rh_pool/pool.py status --pool-id 7  # one task, incl. rh_status/downloads
python3 {baseDir}/scripts/rh_pool/pool.py outputs --latest    # one batch: all files + aggregated fees
python3 {baseDir}/scripts/rh_pool/pool.py reconcile           # resync + download after a restart (no dispatch)
```

Statuses: `PENDING` → `DISPATCHED` → `SUCCESS` / `FAILED` / `SUBMIT_FAILED`.
`outstanding` is how much is still running; `currentBatchId` is null once the
pool has drained.

Downloaded files land under `data/pool/output/batch-<id>/...` by default; their
paths are in the task's `downloads_json`.

## Configuration

`config/skill-config.json` (shipped with the skill) — every key is optional:

| Key | Meaning |
|-----|---------|
| `concurrency` | Max jobs in flight at once (default 3) |
| `pollIntervalSeconds` | Polling cadence — automation tick (Mode A) / watcher tick (Mode B), default 30 |

The pool home (`data/pool`, ledger + default outputs) is hardcoded inside the
skill — no configuration needed on any host.

## Requirements

- Both modes: `python3` and `curl` on `PATH`.
- Mode A additionally needs the `openclaw` CLI on `PATH` (or `OPENCLAW_BIN`).
- Mode B needs nothing else.
