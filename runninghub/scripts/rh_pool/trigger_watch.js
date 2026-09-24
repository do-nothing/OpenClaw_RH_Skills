// Headless condition watcher for the RunningHub task pool.
//
// Attached to an `every` automation as the trigger script. On each evaluation
// it runs one non-blocking `pool.py tick` and fires when the pool has drained
// and that drain has not yet been reported. No LLM is involved.
//
// Contract: return json({ fire, message?, state? }).
//   - trigger.state persists across evaluations (16 KB cap).
//   - fire:true runs the job payload (systemEvent -> main session + wake).
//   - If the payload run fails, state is NOT persisted, so it can fire again.
//   - Each evaluation has a 30s wall-clock budget; keep this script cheap.
//
// The drain signal itself is PERSISTENT in the pool DB (tick reports
// drained=true until a new batch is enqueued). This script does not rely on a
// one-shot latch, so a failed evaluation self-heals on the next one instead of
// silently losing the notification.

// Paths are injected at job-creation time as FORWARD-SLASH absolute paths.
// Do not wrap them in quotes: the exec shell on Windows is PowerShell, and the
// inner quotes break parsing. Both PowerShell and Python accept forward slashes.
const POOL = "<POOL_PY>";      // e.g. C:/Users/.../rh_pool/pool.py
const PYTHON = "<PYTHON>";     // e.g. C:/Users/.../python.exe

async function runTick() {
  // --no-watch: the trigger must not create/remove the watch job itself.
  // Removing the job during its own condition evaluation would cancel the
  // fired payload before it runs. Watch lifecycle is managed by enqueue/manual
  // ticks plus --trigger-once self-disabling.
  const res = await exec({ command: `${PYTHON} ${POOL} tick --no-watch` });
  const out = String(res?.aggregated ?? res?.stdout ?? "");
  try {
    const parsed = JSON.parse(out.slice(out.indexOf("{")));
    return { ok: true, drained: parsed.drained === true, counts: parsed.counts || {} };
  } catch (err) {
    return { ok: false, error: String(err), exitCode: res?.exitCode,
             raw: out.slice(0, 400) };
  }
}

const tick = await runTick();
const drained = tick.ok && tick.drained === true;
const alreadyReported = trigger.state?.reported === true;

// Fire when the pool has drained and this drain has not been reported yet.
const fire = drained && !alreadyReported;

// Track whether the current drain was reported. Reset as soon as the pool has
// live work again, so the next drain notifies too. On a tick error keep the
// previous state (a transient failure must not cause a missed notification),
// and surface the error so failures are observable rather than silent.
const nextState = tick.ok
  ? { drained, reported: drained, counts: tick.counts }
  : { ...(trigger.state || {}), lastTickError: tick.error,
      lastTickExit: tick.exitCode, lastTickRaw: tick.raw };

json({
  fire,
  message: fire
    ? "RunningHub 任务池已排空：所有任务都到达终态。请读取台账并处理产物/通知。"
    : undefined,
  state: nextState,
});
