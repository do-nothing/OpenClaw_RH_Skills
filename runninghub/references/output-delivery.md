# Output & Delivery

## Host difference — read this first

The same skill runs in two kinds of hosts. Pick the column that matches YOUR
available tools; the rest of this file is written for openclaw and only applies
there where it references the `message` tool.

| | **openclaw** (you have `message` / `exec`) | **Generic host** (Trae, other harnesses — no `message` tool) |
|---|---|---|
| Pre-task notice for slow jobs | `message` tool (see below) | A plain text reply before starting |
| Deliver media | `message` tool with `media`, then `NO_REPLY` | **Clickable absolute file links** in your reply (they open inside the host session) |
| Local paths as text | Forbidden (IM users cannot open them) | Correct and required — links, not raw path strings |
| `runninghub.cn` internal URLs | Never | Never |
| `![](...)` markdown images | Never | Never |

On a generic host you are delivering to the user in the same desktop/IDE
session, so absolute file links work; never claim you "sent" a file via a tool
you do not have.

## Progress Notification (for slow tasks)

**openclaw only.** For video, AI app, 3D, and music generation: **ALWAYS send a `message` notification BEFORE starting the script.** These tasks take 1-10+ minutes. Users must know the task has started.

```json
{ "action": "send", "text": "开始生成啦，视频一般需要几分钟，请稍等～ 🎬", "target": "<user>" }
```

Do this BEFORE calling `exec` to run the script. For fast tasks (text-to-image, image upscale, TTS), notification is optional.

Generic hosts: say the same kind of thing in a normal text reply before running the command.

## Media (image/video/audio/3D)

Script prints `OUTPUT_FILE:/path` and optionally cost/duration lines.

### openclaw — `message` tool is mandatory

Printing file paths as text does NOT work — users on Feishu/Lark/Slack cannot access local paths.

Step 1 — ALWAYS call `message` tool:
```json
{ "action": "send", "text": "搞定啦！花了 ¥0.12～ 要不要做成视频？🐱", "media": "/tmp/openclaw/rh-output/cat.jpg" }
```
Step 2 — Then respond with `NO_REPLY` (prevents duplicate message).

**If `message` tool call fails** (error/exception):
- Retry the `message` tool call once.
- If still fails → include `OUTPUT_FILE:<path>` in text AND tell user: "文件生成好了但发送遇到问题，我再试一次～"

**NEVER do these**:
- Print `OUTPUT_FILE:` as first-choice delivery (users see raw text, not a file!)
- Show `runninghub.cn` URLs (internal, users cannot open)
- Use `![](...)` markdown images
- Say "已发送" or "点击下面的附件" without actually calling `message` tool

### Generic host — clickable absolute file links

Give each `OUTPUT_FILE:` path as a clickable absolute link (one line per file),
optionally with a short caption containing the cost. Never paste the
RunningHub internal URL.

Workflow pool tasks: for a single task use
`pool.py status --pool-id <id> --lines` to get the same protocol lines
(`OUTPUT_FILE:` / cost / `DURATION:`) the synchronous scripts print; batch
delivery follows the task-pool reference.

## Cost reporting — three fee types

RunningHub can return up to three separate fees per task:

| Protocol line | Field | Meaning | Settlement |
|---|---|---|---|
| `COINS:N` | consumeCoins | Platform GPU compute, **consumed first** from the account's RH-coin balance | RH coins |
| `COST:¥X.XX` | consumeMoney | Platform compute fee charged to the **wallet balance once RH coins run out** | Wallet cash (¥ or $ per site version) |
| `THIRD_PARTY:¥Y.YY` | thirdPartyConsumeMoney | Extra cost from third-party APIs called inside the workflow | Wallet cash only — coins cannot cover it |
| `DURATION:Ns` | taskCostTime | Server compute time (seconds) | — |

**Rules:**
- Never mention a fee that is `0`, null, or absent.
- Report only what actually appeared, in one short phrase, in the order
  coins → wallet compute → third-party. Examples:
  - only `COINS:25` → "花了 25 RH 币～"
  - `COINS:25` + `THIRD_PARTY:¥0.19` → "花了 25 RH 币，另第三方费用 ¥0.19～"
  - only `COST:¥0.50` → "花了 ¥0.50～"
- Currency symbol follows the site version (¥ or $); print the amount as returned.

## Text Results

Print the text directly to user. Include cost per the rules above.

## Errors & Retry

| Error | Action |
|-------|--------|
| `NO_API_KEY` | Guide key setup → Read `{baseDir}/references/api-key-setup.md` |
| `AUTH_FAILED` | Key expired → https://www.runninghub.cn/enterprise-api/sharedApi |
| `INSUFFICIENT_BALANCE` | "余额不够啦～" → https://www.runninghub.cn/vip-rights/4 |
| `TASK_FAILED` | For video: offer fallback model. For others: show friendly error, offer retry. |

Workflow pool tasks surface failures via `status` (`SUBMIT_FAILED` / `FAILED`,
with `error_message`, and `ERROR:<message>` in `--lines` mode).

## General Notes

- Video is slow (1-5 min); script auto-polls up to 20 min.
- Images < 5MB → base64; larger → upload first.
- Key order: `--api-key` flag → `RUNNINGHUB_API_KEY` env → config file.
