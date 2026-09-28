# Task Pool (batch / async workflows)

For **batch submission** or **long-running workflows**, use the task pool instead of
blocking on a single script call. It submits many jobs, runs them within a
concurrency budget, and downloads results. A background `watch` process exits
when the batch drains; its completion notification returns to this conversation.

Script: `python3 {baseDir}/scripts/rh_pool/pool.py`

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

Named types live in `config/task-types.json` (copy `task-types.json.example` to
start). Each type maps friendly params to a workflow's node inputs.

```bash
# what is available / validate against archived workflow exports
python3 {baseDir}/scripts/rh_pool/pool.py workflow list
python3 {baseDir}/scripts/rh_pool/pool.py workflow validate
```

A type's file params accept **a local path** (uploaded automatically, cached),
an `api/...` id, or a URL.

## Submit

Always pass `--no-notify` in Trae (no external scheduler/session-wake CLI):

```bash
# one type
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --no-notify \
  --type image-gen --param prompt="a cute puppy, 4K cinematic"

# a batch from a file (list of jobs)
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --no-notify --from-file jobs.json
```

`jobs.json`:
```json
[
  {"type": "image-gen", "params": {"prompt": "..."}},
  {"type": "voice-clone", "params": {"text": "...", "referenceAudio": "/path/ref.m4a"}},
  {"type": "digital-human", "params": {"image": "/path/p.jpg", "audio": "/path/a.m4a", "text": "..."}}
]
```

`enqueue` returns `poolIds`. Then immediately launch the watcher **as a
background task** (Shell `run_in_background`; do NOT run it foreground, and do
NOT poll/sleep yourself):

```bash
python3 {baseDir}/scripts/rh_pool/pool.py watch
```

It ticks once immediately, then every `pollIntervalSeconds`, until the pool
reaches zero outstanding jobs and exits. Process exit is the completion signal:
the agent host posts the background-task notification into THIS conversation.
After launching it, tell the user work has started and end your turn — never
poll or sleep yourself. When the notification arrives, run `status` and deliver
the files (see below). No session key is involved.

## Check progress

```bash
python3 {baseDir}/scripts/rh_pool/pool.py status              # counts + recent tasks
python3 {baseDir}/scripts/rh_pool/pool.py status --pool-id 7  # one task, incl. downloads
```

Statuses: `PENDING` → `DISPATCHED` → `SUCCESS` / `FAILED` / `SUBMIT_FAILED`.
`outstanding` is how much is still running.

Downloaded files land under `data/pool/output/<poolId>/...`; their paths are in
the task's `downloads_json`. **Deliver them as clickable absolute file links**
(the `message` tool does not exist in Trae).

## Background watcher

The watcher (`pool.py watch`, one per pool) runs ticks with zero LLM cost and
exits when the batch drains — its process-exit notification is the only
completion signal. You do not poll by hand.

Recovery: a background watcher is bound to this IDE session; if the IDE was
closed while jobs were in flight, run `pool.py reconcile` once in the next
session to resync states and download finished outputs, then start `watch`
again if anything is still outstanding.

Tune it in `config/skill-config.json` (copy the `.example`):

| Key | Meaning |
|-----|---------|
| `concurrency` | Max jobs in flight at once (default 3) |
| `pollIntervalSeconds` | Watcher poll cadence (default 30) |
| `dataDir` | Ledger + outputs location |

## Requirements

`python3` and `curl` on `PATH`. No `openclaw` CLI or scheduler is needed in the
Trae flow (`--no-notify` on every enqueue; `notify.py` stays unused).
