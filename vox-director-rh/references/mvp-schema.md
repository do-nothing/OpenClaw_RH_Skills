# beats.json 字段设计（v2：beat / shots 叙事层）

v2 仍以**扁平 `shots[]`** 为最小视觉单元（每个 shot = 一张关键帧 + 一条 8s 源片，生成脚本几乎不变），但用 `beat_id` 把 1–2 个 shot 组成一个 **beat**：

- **beat = 一句旁白 + 一条字幕**，是音频和叙事单位。
- 每个 beat 第一个 shot 是 **anchor**（`beat_role=anchor`，WIDE，带旁白和可选画面标题）；
- 可选第二个 shot 是 **detail**（`beat_role=detail`，CLOSE/DETAIL，**无旁白、无标题**），beat 旁白连续铺到它上面、句中硬切。
- detail 是可选的节奏升级（多花一次关键帧+图生视频的钱），默认每个 beat 只有 anchor；只在最需要强调的 beat 上加。

旧 v1（`openclaw-vox-mvp-1`，4 shot 各自带旁白、无 beat_id）继续被所有脚本支持：每个 shot 视为只含一个 anchor 的 beat。

## 顶层字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `schema_version` | 是 | `openclaw-vox-mvp-2`（旧片为 `openclaw-vox-mvp-1`） |
| `project` | 是 | 英文/数字短名，用于目录和文件名 |
| `topic` | 是 | 用户给的一句话选题 |
| `language` | 是 | 目前固定 `zh-CN` |
| `aspect` | 是 | 目前固定 `16:9`（竖屏后续梯队） |
| `target_duration_s` | 是 | 10–75，仅规划用；**最终时长由旁白实际长度决定**，长片靠更多 beat |
| `theme` | 是 | 视觉风格名，见下「主题」 |
| `arc` | 是 | 叙事弧线，见 `references/narrative.md` |
| `ending` | 是 | `hard_cut`（默认）/ `quick_cta` / `loop_close` |
| `status` | 是 | `draft`、`keyframes`、`clips`、`audio`、`assembled`、`verified` |
| `image_endpoint` / `video_endpoint` | 否 | 记录池任务类型名（`image-gen-qwen` / `i2v-minimax-h3-first-frame`），仅说明用途 |
| `voice.mode` | 是 | `tts` 或 `clone`（clone 需 `sample_path`） |
| `music.enabled` / `music.prompt` / `music.path` | 是/是/否 | 可复用旧项目 `audio/bgm.mp3`，合成时循环铺满 |
| `captions` | 是 | 目前要求 `true` |
| `watermark` | 否 | 为空则不加水印 |
| `no_duplicate_submit` | 是 | 固定 `true` |

## 主题 theme（10 个）

`newsprint-editorial`（默认）、`swiss-modern`、`chinese-ink`、`american-retro`、`punk-zine`、`soviet-constructivist`、`wpa-propaganda`、`70s-groovy`、`atomic-age`、`gilded-deco`。视觉描述在 `generate_keyframe_prompts.py` 的 `THEMES`。

## 叙事弧线 arc（8 个）

`hook_payoff`（默认）、`how_it_works`、`timeline`、`myth_buster`、`pas`、`bab`、`man_in_hole`、`listicle`。选弧与各弧 beat 走向、钩子/运镜节奏见 `references/narrative.md`。

## shots[] 字段

| 字段 | 必填 | 说明 |
|---|---:|---|
| `id` | 是 | 唯一镜头 id，anchor 用 `s1..sN`，detail 用 `s2b` 这类 |
| `beat_id` | v2 必填 | `b1..bN`，连续；同一 beat 的 anchor 在前、detail 在后 |
| `beat_role` | v2 必填 | `anchor` 或 `detail`；每 beat 恰好一个 anchor、至多一个 detail |
| `shot_size` | v2 必填 | `WIDE` / `MEDIUM` / `CLOSE` / `DETAIL`；detail 只能 CLOSE/DETAIL |
| `dur_s` | 是 | anchor 3.0–6.5；detail 1.2–4.0（规划值，成片由旁白时长驱动） |
| `hook` | anchor | b1 的 anchor 必须 `true` |
| `hook_type` | b1 | `direct_question` 等 7 种，见 narrative.md |
| `title_on_image` | 是 | anchor 可 true；**detail 必须 false** |
| `headline` | 条件 | 标题镜头必填，建议 ≤20 字；detail 必须留空 |
| `narration` | anchor | beat 的中文旁白；字幕逐字使用。**detail 必须留空** |
| `scene` / `scene_en` | 是 | 中文分镜（只给人看）/ 英文纸剪部件画面（进图像模型） |
| `camera_move` | 是 | `static`、`push_in`、`pull_out`、`pan`、`tilt`、`parallax`；相邻镜头不得重复 |
| `element_motion` / `element_motion_en` | 是 | 中文运动设计 / 英文刚体纸片运动 |
| `palette_note` / `palette_en` | 是 | 中文配色备注 / 英文配色（进模型） |
| `keyframe_prompt` / `keyframe_path` | 阶段写入 | 阶段 3；同时回写 `image_pool_id` / `image_coins` |
| `clip_prompt` / `clip_path` | 阶段写入 | 阶段 4；每条都是 8s 源片；同时回写 `video_pool_id` / `video_coins` / `clip_source_duration_s` |
| `vo_path` / `vo_duration_s` | 阶段写入 | 仅 anchor；按 beat 生成一条 TTS |

## 节奏与时长

- beat 数按时长选（15–22s→4、30s→6、45s→8–10、60s→10–12）；每个成片镜头通常 3–5s，单张海报挂超 ~7s 必闷。
- 单段语音硬预算 **7.35s**（8s 源片 − lead 0.20 − tail 0.45）；`generate_audio.py` 生成后 ffprobe，超时只能压缩该 anchor 旁白字数后 `--only <id> --force --submit` 重做（voice-clone-emo 无调速参数）。
- 双镜头 beat：anchor 时长 = `lead + 旁白 + tail − detail 时长`，旁白从 beat 起点 +0.20s 起、连续铺过切点；同一条 beat 字幕在 anchor+detail 全程显示。
- 相邻镜头（含 anchor→detail）运镜不得相同；`static` 留给收尾金句 beat。
- 旁白推荐 12–22 字最稳，硬上限 45 字；想紧凑就压字数，这是最便宜的质量开关。

## 中英分离（铁律）

- 中文 `scene`/`element_motion`/`palette_note` 只用于沟通和旁白；进入图像模型的只能是 `_en` 字段，避免图像模型把中文渲染成画面文字。
- 除指定 `headline` 外，画面不允许可读文字、报纸标题、标签、店招、时间线；史料质感用不可读墨痕。

## 失败与复用

- `keyframe_path`/`clip_path`/`vo_path` 已存在且非空默认复用，`--force` 才覆盖。
- poolId 入队后只能等待同一次批次，**禁止因慢而重新入队**；失败在该 shot 写 `last_*_error` 并整阶段停止，等人确认。
