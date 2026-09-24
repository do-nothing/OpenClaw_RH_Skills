// Headless condition watcher for the RunningHub task pool.
//
// Attached to an `every` automation as the trigger script. On each evaluation
// it runs one non-blocking `pool.py tick` and fires only on the rising edge of
// "pool drained" (outstanding tasks reached 0). No LLM is involved.
//
// Contract: return json({ fire, message?, state? }).
//   - trigger.state persists across evaluations (16 KB cap).
//   - fire:true runs the job payload (systemEvent -> main session + wake).
//   - If the payload run fails, state is NOT persisted, so it can fire again.
//
// Dedup: `notified` latches once drained; it resets after a non-drained
// observation, so a later batch drains and notifies again.

const POOL = "<POOL_PY>";      // absolute path, injected when the job is created
const PYTHON = "<PYTHON>";     // absolute python executable

async function runTick() {
  // --no-watch: the trigger must not create/remove the watch job itself.
  // Removing the job during its own condition evaluation would cancel the
  // fired payload before it runs. Watch lifecycle is managed by enqueue/manual
  // ticks plus --trigger-once self-disabling.
  const res = await exec({ command: `"${PYTHON}" "${POOL}" tick --no-watch` });
  // Newer runtimes expose `aggregated`; older ones expose stdout.
  const out = String(res?.aggregated ?? res?.stdout ?? "");
  try {
    const parsed = JSON.parse(out.slice(out.indexOf("{")));
    return { ok: true, drained: parsed.drained === true, counts: parsed.counts || {} };
  } catch (err) {
    return { ok: false, error: String(err), raw: out.slice(0, 400) };
  }
}

const tick = await runTick();
const drained = tick.ok && tick.drained === true;
const wasNotified = trigger.state?.notified === true;

// Fire once per drain: drained now, and we had not already notified for this drain.
const fire = drained && !wasNotified;

// Latch `notified` while drained; clear it as soon as new work appears so the
// next drain can notify again. On a tick error keep the previous latch intact
// (a transient failure must not cause a spurious or missed notification).
const nextState = tick.ok
  ? { drained, notified: drained, counts: tick.counts }
  : { ...(trigger.state || {}) };

json({
  fire,
  message: fire
    ? "RunningHub 任务池已排空：所有任务都到达终态。请读取台账并处理产物/通知。"
    : undefined,
  state: nextState,
});
