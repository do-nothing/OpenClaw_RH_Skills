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

**Any workflow task goes here — a single one counts.** The shipped workflow
catalog covers image generation/editing, voice cloning, digital human, music
and MiniMax H3 video (full list and choice guide:
[Task catalog](#task-catalog-and-which-to-choose) below).

- User asks for a **catalog workflow type** (any single job, even one image)
- User wants **several generations** at once ("跑 3 个", "批量", "都生成一遍")
- A task is **slow** and the user keeps chatting (video / digital human / 3D / music)
- User asks for **progress** on submitted work

For ordinary interactive single-shot image/video generation through
RunningHub's standard API, use the menus in `references/image-models.md` /
`references/video-models.md` instead. The boundary is about the delivery
channel (async workflow vs synchronous standard endpoint), not quality.

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

## Task catalog and which to choose

Nine shipped types (run `pool.py workflow list` for live labels/params).
"实测费用" comes from this skill's own task ledger and is an order-of-magnitude
reference only — RunningHub pricing changes; check the `COINS:`/`THIRD_PARTY:`
lines of `outputs` for real charges.

| typeId | 输入 → 输出 | 实测费用参考 |
|---|---|---|
| `image-gen-qwen` | 文字 → 图片（提示词自动扩写） | 约 19 RH 币，**零现金** |
| `image-edit-qwen` | 1 张图 + 指令 → 改好的图 | 约 23 RH 币，**零现金** |
| `image-edit-qwen-multi` | 主图 + 1～5 张参考图 + 指令 → 合成图（换装/姿势/配饰） | 约 25 RH 币，**零现金** |
| `image-edit-banana2` | 0 图文生图 / 1 张改图 / 2～10 张多图融合 | 1 RH 币 **+ 约 ¥0.19/张第三方现金** |
| `i2v-minimax-h3-first-frame` | 1 张首帧图 + 描述 → 有声短视频 | 约 81 RH 币 |
| `i2v-minimax-h3-multi-ref` | 最多 9 图 + 3 视频 + 3 音频 + 六段式提示词 → 有声短视频 | 约 100～350 RH 币（挂视频更贵） |
| `voice-clone-emo` | 文案 + 参考人声（+可选情绪音频）→ 克隆音色语音 | RH 币，零现金 |
| `digital-human` | 人物照 + 参考人声 + 播报文案 → 对口型口播视频 | 约 60 RH 币 |
| `music-minimax` | 风格描述 + 歌词（可空）→ 完整歌曲/纯音乐 | 约 34 RH 币 |

### Overlap rules (recommendations)

1. **生图默认走 Qwen Image 2.1，不走 Nano Banana 2。** Qwen 三个类型只扣
   RH 币；banana2 另收第三方现金（约 ¥0.19/张）。仅在以下情况用 banana2：
   - 需要 **7～10 张图**融合（Qwen 多图编辑上限 6 张）；
   - Qwen 效果不达标，用户接受现金费用。
2. **图片编辑按参考图数量选型**：0 张→`image-gen-qwen`；1 张→`image-edit-qwen`；
   2～6 张→`image-edit-qwen-multi`；7～10 张→`image-edit-banana2`。
3. **H3 视频按复杂度选型**：只想"让这张图动起来"→`h3-first-frame`（便宜）；
   需要多角色一致、动作/运镜迁移、续写、参考音色配音→`h3-multi-ref`。
4. **换主体不要挂源视频**（实测结论）：想把视频 A 里的主角换成 B，挂 A 到
   视频槽时 B 的身份会被 A 锚定（`[video editing]` 和 `weak_reference` 两种
   写法都试过，成片仍是原主角）。正确做法是**只挂 B 的图片**走纯图参考；
   若还要复刻 A 的动作，见下方动作迁移写法，并把场景整体换掉。
5. **配音选型**：只要"用某人的声音念一段文案"→`voice-clone-emo`（出音频）；
   要"照片人物开口口播"→`digital-human`（出视频，内部自带语音合成，音频
   参数是音色参考而非成品配音）；视频需要旁白→用 H3 multi-ref 的音频槽。
6. **标准 API 菜单与工作流的边界**：`references/image-models.md` /
   `video-models.md` 里的标准端点是同步单次调用，适合交互性出图/出片；任务池
   是异步 ComfyUI 工作流，适合批量、长任务和本表的特定高级能力。

## MiniMax H3 multi-ref prompt guide

`i2v-minimax-h3-multi-ref` 的 prompt 不是自由描述，必须按 MiniMax 官方
Ref2VA 指南的**六段式**写（英文写效果最好，台词可用中文）。骨架：

```text
[<mode tags>]

Subject definitions:
- <Subject 1>: <Picture 1> — relationship: fully_preserved/attribute_transfer/...
- <Subject 2>: <Video 1> — relationship: fully_preserved/weak_reference/...
- <Subject 3>: <Audio 1> — relationship: fully_copy/timbre_reference/...

Summary: 一句话说清成片是什么。

Retention analysis: 每个参考素材保留什么、丢弃什么、改了什么。

Detailed description: 分镜头时间线；台词写成独立行  <d>中文台词</d>

Overall soundscape: 环境声/音效；旁白引用 <Audio 1>。

Non-diegetic music: （可选）背景音乐。
```

已实测验证的写法：

- **多图锁定主体/场景**：`[reference generation]`，每张图给 relationship
  （`fully_preserved` = 身份/外观必须保留；`attribute_transfer` = 只借风格
  属性）。不用的槽全部留空，池会清空发布图自带示例。
- **动作/运镜迁移**（视频槽的核心价值）：图片标 `fully_preserved` 定"谁来
  演"；视频写成 *motion reference: weak_reference, do not copy its identity
  or background, only the exact action timeline*，并在 prompt 里把场景整体
  换成新环境（实测：狗图 + 猫视频动作 + 换成秋日庭院 → 金毛在草地上逐拍
  演出猫的动作，无猫元素泄漏）。
- **视频续写**：`[video continuation + keyframe completion]`，图片槽放源片
  **末帧**（本地 ffmpeg 抽取），视频槽放源片并标 `fully_preserved`，新动作
  保持低幅度、无时间跳跃。
- **音频两种用法**：①音色参考——给人声，prompt 里写新的 `<d>` 台词，模型
  用该音色念新词；②整轨复用——`<Audio 1>: fully_copy`，旁白/音效时间轴
  1:1 复刻（4 次实测开口时间误差 ≤6ms），此时 `durationSeconds` 对齐原片。
- m4a / mp4 均可直传，无需先转码。

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
python3 {baseDir}/scripts/rh_pool/pool.py ls                    # latest batch as a human-readable table
python3 {baseDir}/scripts/rh_pool/pool.py ls 10                 # batch 10 (a positive number = absolute id)
python3 {baseDir}/scripts/rh_pool/pool.py ls -1                 # latest-1 (a negative number = offset back)
python3 {baseDir}/scripts/rh_pool/pool.py ls --batch-id 10      # same as `ls 10`
python3 {baseDir}/scripts/rh_pool/pool.py status              # currentBatchId + counts + recent tasks
python3 {baseDir}/scripts/rh_pool/pool.py status --pool-id 7  # one task, incl. rh_status/downloads
python3 {baseDir}/scripts/rh_pool/pool.py outputs --latest    # one batch: all files + aggregated fees
python3 {baseDir}/scripts/rh_pool/pool.py outputs --batch-id 10  # same, for a specific batch
python3 {baseDir}/scripts/rh_pool/pool.py reconcile           # resync + download after a restart (no dispatch)
```

`ls` shows one row per task (id, workflow display name, instance, submit
time, wall duration, `rh_status`, fees); a trailing `…` on the duration marks
tasks still running, and the header reports the outstanding count.

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
