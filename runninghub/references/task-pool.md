# Task Pool (workflow batch / async runner)

Runs shipped RunningHub workflow types asynchronously: submit jobs, they queue
within a concurrency budget, run in the background, and download automatically.
A single job goes through the pool too.

Script: `python3 {baseDir}/scripts/rh_pool/pool.py`

The enqueue flag selects the runner — do not choose a mode in prose:

| Host | enqueue flag | Runner | Completion |
|------|--------------|--------|------------|
| **openclaw** | `--openclawSessionKey <session>` | polling automation (zero LLM) + immediate first tick | session is **woken by CLI** when the batch drains |
| **any other host** (Trae, DeepSeek harness, unknown shells) | *(no flag)* | detached background **watcher**, auto-started by enqueue | process exits at drain; **no wake-up** — reconcile when the user returns |

## Quick reference

```bash
# types and their params (always check before composing a job)
python3 {baseDir}/scripts/rh_pool/pool.py workflow list
python3 {baseDir}/scripts/rh_pool/pool.py workflow validate

# submit (single job / batch file); runner chosen by flag — see Submit sections
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --type <typeId> --param key=value [--param file=/path/x.png]
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --from-file jobs.json

# inspect
python3 {baseDir}/scripts/rh_pool/pool.py ls                 # latest batch, human table
python3 {baseDir}/scripts/rh_pool/pool.py ls 10              # batch 10; ls -1 = one batch back
python3 {baseDir}/scripts/rh_pool/pool.py status             # current batch + counts + 10 recent tasks
python3 {baseDir}/scripts/rh_pool/pool.py status --pool-id 7 # one task (add --lines for protocol lines)
python3 {baseDir}/scripts/rh_pool/pool.py outputs --batch-id 10   # batch files + aggregated fees
python3 {baseDir}/scripts/rh_pool/pool.py reconcile          # resync + download after a restart
```

## Task types and params

Named types live in `config/task-types.json`; `workflow list` prints live
labels, params, required flags and accepted file extensions. File params accept
**a local path** (uploaded automatically, cached), an `api/...` id, or a URL;
unused optional slots must simply be omitted (the pool clears them).

Batch file (`jobs.json`) — a list of jobs, each `{type, params, outputDir?, outputName?}`:

```json
[
  {"type": "music-minimax", "params": {"prompt": "..."}},
  {"type": "digital-human", "params": {"image": "/path/p.jpg", "audio": "/path/a.m4a", "text": "..."}}
]
```

## Submit — Mode A: openclaw

Take the session key verbatim from the **`session=` field of your runtime
context** and pass it as a plaintext flag (there is no environment variable):

```bash
python3 {baseDir}/scripts/rh_pool/pool.py enqueue \
  --openclawSessionKey "agent:main:xxxx" \
  --type music-minimax --param prompt="lo-fi chill beats, soft piano"

python3 {baseDir}/scripts/rh_pool/pool.py enqueue \
  --openclawSessionKey "agent:main:xxxx" --from-file jobs.json
```

What enqueue does: creates (or reuses) one global polling automation, then
fires one immediate tick so the batch starts within ~1s. The JSON response
contains `"mode": "openclaw"`, `"automation"` and `"kick"`.

- **Your turn ends after submit.** Tell the user work started, then stop — do
  NOT poll `status`, sleep, or wait in-loop.
- When woken after drain: run `outputs --batch-id <batchId>` using the
  **batchId from the enqueue response** (prefer it over `--latest`). Deliver per
  `references/output-delivery.md` (`message` tool + cost rules). One task's
  detail: `status --pool-id <id> --lines`.
- **Errors are reported, never auto-degraded.** If `automation.action ==
  "error"` or `kick.action == "failed"` (non-zero exit), tell the user what
  went wrong verbatim — do NOT retry as Mode B or start a watcher. The jobs
  stay safely queued.

## Submit — Mode B: generic hosts (no openclaw)

Enqueue with **no mode flag** — the detached watcher starts automatically:

```bash
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --type image-gen-qwen --param prompt="..."
python3 {baseDir}/scripts/rh_pool/pool.py enqueue --from-file jobs.json
```

Response contains `"mode": "watch"` and `"watcher": {"action": "issued"}`. The
watcher ticks immediately, then every `pollIntervalSeconds`, and exits at
drain; a batch opened in the drain window keeps it running. If start fails
(`"action": "failed"`, non-zero exit), report verbatim — do not improvise
another polling scheme.

**Do NOT promise auto wake-up** — the watcher's exit event is only seen with
the user's next message:

1. After enqueue, tell the user honestly, e.g. "开始生成啦，完成后你回来发任意
   一句话，我立刻查收并交付～", then end your turn. Never poll or sleep.
2. When the user returns, first run `pool.py status`. Deliver only when
   `currentBatchId` is null; otherwise report progress and end the turn.
3. Once drained, run `outputs --batch-id <batchId>` (from the enqueue response;
   `--latest` only if you lack it) and deliver `OUTPUT_FILE:` paths as
   **clickable absolute file links** with the non-zero `COINS:` / `COST:` /
   `THIRD_PARTY:` lines (generic-host column of `references/output-delivery.md`).
   Never paste RunningHub internal URLs.
4. After an IDE/host restart mid-flight: `pool.py reconcile` first; if work is
   still outstanding, restart the watcher with
   `python3 {baseDir}/scripts/rh_pool/notify.py watch`.

## Check progress

- `ls [N]` — human-readable table for one batch: id, workflow name, instance,
  submit time, wall duration (trailing `…` = still running), `rh_status`, fees.
  The header reports task and outstanding counts. `N` positive = absolute batch
  id; negative = offset back (`ls -1`); no arg = latest.
- `status` — JSON overview: `currentBatchId` (null when drained), global
  `counts`, and the **10 newest** tasks. Use `--limit N` for another size,
  `--all` for the full ledger, `--status-filter RUNNING` for one state,
  `--pool-id <id>` for one task (`--lines` for protocol lines).
- `outputs --batch-id N | --latest` — `BATCH:` header with per-state counts,
  every `OUTPUT_FILE:`, aggregated `COINS:`/`COST:`/`THIRD_PARTY:`, max
  `DURATION:`, and `ERROR:<poolId>: …` per failure.

Statuses: `PENDING` → `DISPATCHED` → `SUCCESS` / `FAILED` / `SUBMIT_FAILED`;
`rh_status` (QUEUED → RUNNING → SUCCESS/FAILED) is RunningHub's live status,
written on every poll.

## Output locations and names

- **Default:** `data/pool/output/batch-<batchId>/<poolId>_<nodeId>_<idx>.<ext>`
  inside the skill's pool home — persistent on every host, grouped per batch,
  dirs created automatically.
- **Real projects:** give each job `outputDir` (no batch subdir added) and
  optional `outputName` (basename **without extension**); multiple results get
  `_0`, `_1` suffixes, reruns overwrite. Per-job dirs/names may differ in one
  batch. CLI: `--output-dir DIR`, `--output-name NAME`.

```json
[
  {"type": "image-edit-banana2", "params": {"prompt": "beat 1 wide"},
   "outputDir": "D:/film/keyframes", "outputName": "kf_1a"},
  {"type": "digital-human",
   "params": {"image": "D:/film/keyframes/kf_1a.png", "audio": "D:/film/a.m4a", "text": "..."},
   "outputDir": "D:/film/clips", "outputName": "clip_1a"}
]
```

## Batches (internal)

No flag needed: while any job is outstanding, new enqueues **join the open
batch**; after drain the next enqueue opens a new one. Batch state is derived
from task rows (crash-safe) and scopes the drain-time wake-up.

## Manual enqueue (testing only)

`--manual` queues jobs and starts nothing; advance with `pool.py tick`. Never
use it in normal user-facing operation.

## Configuration

`config/skill-config.json` — every key optional:

| Key | Meaning |
|-----|---------|
| `concurrency` | Max jobs in flight at once (default 3) |
| `pollIntervalSeconds` | Automation/watcher tick cadence (default 30) |

The pool home (`data/pool`: ledger + default outputs) is hardcoded inside the
skill. Requirements: `python3` + `curl` on `PATH`; Mode A additionally needs
the `openclaw` CLI (or `OPENCLAW_BIN`).

---

# Appendix A — workflow catalog and selection

Reference only — not needed to operate the pool. Run `workflow list` for live
params. Cost figures are ledger observations (order of magnitude); trust the
`COINS:`/`THIRD_PARTY:` lines of `outputs` for real charges.

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

### Selection rules

1. **生图默认 Qwen Image 2.1，不用 Nano Banana 2**（后者另收约 ¥0.19/张
   现金）。仅当需要 7～10 图融合或 Qwen 效果不达标且用户接受现金时才用。
2. **图片编辑按参考图数量**：0 张→`image-gen-qwen`；1 张→`image-edit-qwen`；
   2～6 张→`image-edit-qwen-multi`；7～10 张→`image-edit-banana2`。
3. **H3 视频按复杂度**："让一张图动起来"→`h3-first-frame`；多角色一致、
   动作/运镜迁移、续写、参考音色配音→`h3-multi-ref`。
4. **换主体不要挂源视频**（实测）：视频槽会锚定源片主角身份（editing 与
   weak_reference 写法均失败）。只挂目标主体图片；要复刻动作时按附录 B 的
   动作迁移写法并整体替换场景。
5. **配音路径**："用某人的声音念文案"→`voice-clone-emo`（音频）；"照片人物
   开口口播"→`digital-human`（视频，音频参数只取音色）；视频旁白→H3
   multi-ref 音频槽。

# Appendix B — MiniMax H3 multi-ref prompt guide

`i2v-minimax-h3-multi-ref` 的 prompt 必须按 MiniMax Ref2VA **六段式**写
（英文效果最好，台词可中文）：

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

Verified patterns:

- **多图锁定主体/场景**：`[reference generation]`，每图给 relationship
  （`fully_preserved` = 身份外观必须保留；`attribute_transfer` = 只借风格）。
- **动作/运镜迁移**（视频槽核心价值）：图片 `fully_preserved` 定"谁来演"；
  视频写 *motion reference: weak_reference, do not copy its identity or
  background, only the exact action timeline*，场景整体换成新环境（实测狗图
  +猫视频动作+秋日庭院 → 金毛在草地上逐拍演猫的动作，无猫元素泄漏）。
- **视频续写**：`[video continuation + keyframe completion]`，图片槽放源片
  末帧（本地 ffmpeg 抽取），视频槽源片 `fully_preserved`，新动作低幅度。
- **音频两种用法**：①音色参考——人声 + 新的 `<d>` 台词；②整轨复用——
  `<Audio 1>: fully_copy`，时间轴 1:1 复刻（实测开口误差 ≤6ms），
  `durationSeconds` 对齐原片。
- m4a / mp4 直传即可，无需转码。
