# explainer.json 结构（派生状态，勿手改）

由 `sync_script.py` 从 `script.md` 派生；后续脚本回写任务 ID、实测数据、镜头规划。
schema 版本：`openclaw-explainer-1`。

## 顶层

```json
{
  "schema_version": "openclaw-explainer-1",
  "project": "compound-interest",
  "topic": "…", "audience": "…", "core_takeaway": "…", "tone": "…",
  "aspect": "16:9",
  "target_duration_s": 90,
  "visual_style": "clean-diagram",
  "voice": {"mode": "tts", "group": "auto", "sample_path": null},
  "voice_groups": [
    {"id": "g01", "beats": ["b01", "b02", "b03"],
     "raw_path": "audio/vo_g01.m4a", "seg_path": "audio/seg_g01.m4a",
     "raw_duration_s": 34.2, "seg_duration_s": 35.5,
     "card": false, "align_method": "silence", "tts_pool_id": "…", "tts_coins": 26}
  ],
  "music": {"enabled": true, "prompt": "…", "path": null, "pool_id": null},
  "captions": true,
  "chapter_cards": false,
  "chapters": [{"id": "c1", "title": "…", "from_beat": "b01"}],
  "status": "draft",
  "script_sha256": "…",
  "aspect_map": {"image": "16:9 (Widescreen)", "video": 5, "width": 1280, "height": 720},
  "endpoints": {
    "tts":  {"type": "voice-clone-emo", "workflowId": "…"},
    "music": {"type": "music-yue2", "workflowId": "…", "accompanimentNodeId": "56"},
    "image": {"type": "image-gen-qwen", "workflowId": "…"},
    "image_edit": {"type": "image-edit-qwen", "workflowId": "…"},
    "video_first_frame": {"type": "i2v-minimax-h3-first-frame", "workflowId": "…"},
    "video_first_last_frame": {"type": "i2v-minimax-h3-first-last-frame", "workflowId": "…"}
  },
  "beats": [ … ],
  "shots": [ … ]
}
```

`status`：draft / audio / shots / keyframes / clips / assembled / verified。

## beats[]

| 字段 | 写入阶段 | 说明 |
|---|---|---|
| `id` / `title` | sync | b01… / 标题中文名 |
| `narration` | sync | 旁白原文（TTS 与字幕唯一来源） |
| `visual_duty` | sync | 8 枚举之一 |
| `visual_see` | sync | 中文「看到」 |
| `on_screen_text` | sync | 字符串数组（≤3 项，每项 ≤8 字） |
| `progressive` | sync | 渐进步骤数组 |
| `continuity` / `avoid` | sync | 可空 |
| `narration_sha256` | sync | 级联失效依据 |
| `est_duration_s` | sync | 字数 × 0.24 |
| `vo_path` / `vo_duration_s` / `tts_pool_id` | audio | 实测；分组模式 `vo_path` 指向所属组的原始整组音频，`vo_duration_s` 为对齐后的语音段长 |
| `vo_group_id` / `vo_seg_start_s` / `vo_seg_end_s` | audio | 仅分组模式：所属组与该 beat 在归一化段内的语音坐标 |
| `pauses_path` / `pauses` | audio | `[{start,end,duration}]`，相对该 beat 语音起点；分组模式由整组停顿按边界切分 |
| `last_tts_error` | audio | 失败即写 |

## shots[]（扁平，plan_shots 写入）

```json
{
  "id": "b03s1",
  "beat_id": "b03",
  "ord": 1,
  "mode": "first_frame",
  "shot_size": "WIDE",
  "camera_move": "push_in",
  "timeline_start_s": 18.65,
  "used_duration_s": 5.77,
  "submit_duration_s": 6,
  "cut_at_s": 24.42,
  "cut_basis": "sentence_pause",
  "pause_duration_s": 0.62,
  "chapter_id": "c1",
  "scene_en": "",
  "motion_en": "",
  "last_frame_change_en": "",
  "avoid_en": "",
  "keyframe_prompt": null,
  "keyframe_prompt_sha256": null,
  "first_frame_path": null,
  "last_frame_path": null,
  "image_pool_id": null,
  "last_image_pool_id": null,
  "image_coins": 0,
  "clip_prompt": null,
  "clip_path": null,
  "clip_source_duration_s": null,
  "video_pool_id": null,
  "video_coins": 0,
  "last_image_error": null,
  "last_video_error": null
}
```

要点：

- `mode`：`first_frame`（一张关键帧）或 `first_last_frame`（首帧 + 尾帧编辑）。
- `used_duration_s`：成片实际使用长度（非末镜按停顿切点精确裁切）；
  `submit_duration_s = clamp(ceil(used),4,15)`，提交给 H3/FL2VA 的整数秒。
- `cut_basis`：`sentence_pause`（≥0.45s 停顿）/ `short_pause`（0.25–0.45s）/
  `forced_no_pause`（窗口扩大后仍无停顿，硬切，审批门必须人工处理）/
  `single_shot`（该 beat 只有一镜）/ `beat_last`（beat 末镜）。
- 逐句模式（`voice.group: beat`）：beat 末镜合成时保留完整整数秒源片，beat 块长 =
  Σ 前序镜 used + 末镜 submit。
- 分组模式（默认）：所有镜头按 used 精确裁切，beat 块长由归一化组段时间轴决定，
  plan_shots 会强校验 Σused 与音频时间轴一致。
- `scene_en / motion_en / last_frame_change_en / avoid_en` 由 agent 写入
  `prompts.en.json` 后经提示词脚本合并进本文件；中文视觉字段绝不直接进提示词
  （script.md 写了「禁忌」但 avoid_en 留空时，提示词脚本会警告该禁忌未生效）。

## 级联失效规则（sync_script）

- 旁白哈希变化：清空该 beat 的 `vo_*`、`pauses*`，删除其全部 shots（镜头规划/关键帧/视频重做）。分组模式下整组音频是一个整体：任意 beat 旁白/章节结构/`voice.group` 变化 → 整个 `voice_groups` 时间轴作废。
- beat 被删除：连带删除其 shots 记录（磁盘文件保留但不再引用）。
- 视觉字段变化、`visual_style/aspect/chapters` 变化：不清空产物；重生成提示词后，
  哈希不一致的镜头由脚本列出，提示用 `--force` 重滚关键帧。
