# Output & Delivery

## Host difference — read first

Pick YOUR column; the `message` rules apply only on openclaw.

| | **openclaw** (has `message` / `exec`) | **Generic host** (Trae etc., no `message`) |
|---|---|---|
| Pre-task notice | `message` tool | Plain text reply |
| Deliver media | `message` with `media`, then `NO_REPLY` | Clickable absolute file links |
| Raw local paths as text | Forbidden | Correct (as links) |

Never show `runninghub.cn` URLs or `![](...)` markdown images on either host.

## Progress notification (slow tasks)

openclaw: BEFORE the script call, `message` → "开始生成啦，视频一般需要几分钟，请稍等～ 🎬".
Generic host: say the same in a normal reply.
Optional for fast tasks (image, upscale, TTS).

## Media delivery

Scripts print `OUTPUT_FILE:/path` plus cost/duration lines.

**openclaw:** call `message` (`{"action":"send","text":"...","media":"<path>"}`), then `NO_REPLY`. On failure: retry once; still failing, print `OUTPUT_FILE:<path>` with "文件生成好了但发送遇到问题，我再试一次～". Never claim "已发送" without the tool call.

**Generic host:** give each `OUTPUT_FILE:` as a clickable absolute file link.

Workflow pool: one batch → `pool.py outputs --batch-id <batchId>` (the batchId from the enqueue response; `--latest` as fallback) for all `OUTPUT_FILE:` lines + aggregated fees; one task → `pool.py status --pool-id <id> --lines`.

## Cost reporting

Lines you may see (0 / null / absent → never mention):

- `COINS:N` — RH 币算力
- `COST:X` — 钱包现金算力费（RH 币用完后扣）
- `THIRD_PARTY:X` — 第三方接口费，只能现金结算
- `DURATION:Ns` — 耗时

Report each present fee in one short phrase, coins first. Cash amounts are written as **¥/$X** (which currency depends on the API key's site; do not assert one):

- `COINS:25` → "花了 25 RH 币～"
- `COINS:25` + `THIRD_PARTY:0.19` → "花了 25 RH 币，另第三方费用 ¥/$0.19～"
- `COST:0.50` → "花了 ¥/$0.50～"

## Text results

Print directly; include cost per above.

## Errors

| Error | Action |
|---|---|
| `NO_API_KEY` | Read `{baseDir}/references/api-key-setup.md` |
| `AUTH_FAILED` | Key expired → https://www.runninghub.cn/enterprise-api/sharedApi |
| `INSUFFICIENT_BALANCE` | "余额不够啦～" → https://www.runninghub.cn/vip-rights/4 |
| `TASK_FAILED` | Video: offer fallback model. Others: friendly error + offer retry. |

Pool: `SUBMIT_FAILED` / `FAILED` in `status`; `--lines` prints `ERROR:<message>`.

## Notes

- Video takes 1-5 min; script auto-polls up to 20 min.
- Images < 5MB → base64; larger → upload first.
- Key order: `--api-key` → `RUNNINGHUB_API_KEY` env → config file.
