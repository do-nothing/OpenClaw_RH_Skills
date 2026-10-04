---
name: explainer-studio
description: 把一个知识点或观点做成讲稿先行的中文内容讲解片（30–300 秒，16:9 默认可换比例），流程为口播稿审批、旁白实测时长与停顿、按停顿切镜头、关键帧、图生视频、本地字幕与章节层合成；媒体生成走 RunningHub 任务池，媒体理解 QA 走 media-understand。用户提到知识讲解片、科普视频、原理解释视频、观点表达视频、explainer、把某个知识点做成视频时使用。不要用于拼贴广告片或情绪宣传片（用 vox-director-rh）。
---

# Explainer Studio（RunningHub 任务池版）

把一个知识点 / 观点做成一支**以旁白为主轴的中文内容讲解片**（默认 16:9，30–300 秒；最终时长由实测旁白决定）。

信条：**先有一篇讲得通的稿子；画面是旁白的视觉解释，不是主角。** 成功标准是观众看完能用自己的话复述这个知识点，不是「画面好看」。

媒体生成统一走 **RunningHub 通用异步任务池**（`runninghub` 技能的 `pool.py`），本地用 **ffmpeg + ffprobe + Pillow** 合成；可选媒体理解 QA 走姊妹技能 **media-understand**（直接送原文件，不做压缩代理）。

## 与 vox-director-rh 的边界

| | vox-director-rh（已冻结） | explainer-studio（本技能） |
|---|---|---|
| 创作心智 | 视觉优先：拼贴海报先行，运动后加 | 语言优先：讲稿先行，画面辅助理解 |
| 适合 | 广告/宣传片、情绪打动、转化 | 科普、知识输出、原理解释、观点表达 |
| 第一产物 | 关键帧 | 完整口播稿 |
| 视觉风格 | 纸片拼贴为必选 | 风格开放：clean-diagram / paper-collage / swiss-infographic / warm-editorial |
| 片长 | 15–60s | 30–300s（超过 5 分钟建议拆系列） |

两个技能目录独立演化，不抽公共代码；共用执行器是 runninghub 任务池。

## 术语

- **beat（段落/拍点）**：一个论点单元 = 一条连续旁白 + 一个或多个镜头。beat 没有 15s 上限。
- **shot（镜头）**：一次视频生成任务产出的连续画面，成片使用 4–15 秒。
- **keyframe（关键帧）**：镜头画面设计稿；首帧模式 1 张，首尾帧模式 2 张（尾帧由首帧单图编辑得到）。
- **关系**：旁白 : beat = 1:1（严格，旁白不按镜头切开）；beat : shot = 1:N；shot : generation job = 1:1。

## 不可越过的规则

1. 每阶段结束必须停下等用户确认，再进下一阶段。
2. 所有付费生成前，说明数量、池任务类型、预计等待与 RH 币费用，用户明确确认后才 `--submit`。
3. 池任务只等待同一次入队批次；慢不等于失败，**禁止因等待而重复入队**。失败/超时立刻停在当前阶段并报告 poolId，**禁止自动重发**（启动级 code=1000 速败由任务池侧自动补投，见 runninghub 配置）。
4. 已存在非空素材默认复用；返工只重做受影响项（脚本支持 `--only` / `--force`）。部分失败输出汇总表（成功/失败、实测时长、已花费），信息一次给全。
5. 文案在审批门 1 锁死。锁稿后改动某 beat 旁白，该 beat 的音频、停顿、镜头规划、关键帧、视频全部级联失效（脚本用哈希自动判定），其余 beat 继续复用。
6. 进图像/视频模型的提示词只能是英文与被允许的画面文字；中文只用于旁白、字幕、章节和明确指定的画面关键词。
7. 画面内只允许关键词/数字/指定标题，禁止整句文字和乱码；全量逐字字幕是底部字幕条，由 Pillow 本地渲染，不进生成图。
8. 最终视频必须本地 ffprobe + 首中尾抽帧 + 切点帧 + 音频电平验收，用 `MEDIA:<绝对路径>` 交付。

## 标准流程（每阶段一个脚本）

项目目录 `out/<project>/`；唯一人工编辑源是 `script.md`，机器状态在 `explainer.json`（脚本派生，不要手改，除 stage 3 的镜头模式/运镜与英文画面稿注入文件，见下）。

格式与字段的权威定义：[references/script-format.md](references/script-format.md)（讲稿格式、视觉字段、枚举）、[references/schema.md](references/schema.md)（explainer.json 结构）。

### 阶段 0 · 环境检查（免费）

runninghub 任务池可用（API key 已配置）、ffmpeg/ffprobe 在 PATH（或 winget 全路径）、Python + Pillow。脚本会从 `runninghub/config/task-types.json` 解析所有池类型的 workflowId 快照写入项目，workflowId 不硬编码在本技能。

### 阶段 1 · 讲稿创作（审批门 1 —— 最重的门）

离线建项目（不产生费用）：

```powershell
python scripts/new_project.py --project <name> --root out --topic "一句话知识点" `
  --aspect 16:9 --duration 90 --style clean-diagram --music
```

然后与用户共创，把 `out/<name>/script.md` 写成正式讲稿：整篇口播稿（耳朵语法：短句、一句一个意思、具体名词，删掉「大家好/今天我们来讲」），每个 `## bXX` 是一个 beat，标题后第一段正文是该 beat 旁白原文；视觉意图只写认知任务（`视觉职责/看到/文字/渐进/连贯/禁忌`），**不写景别、运镜、构图**。中文预估语速 0.24 s/字（仅参考）。结构：钩子（前 3s 反常识/痛点/利益承诺）→ 2–3 个小点 → 收尾总结。

解析、校验并派生机读状态：

```powershell
python scripts/sync_script.py out/<name> --strict
```

审批材料：逐句讲稿 + beat 切分 + 每句预估时长 + 视觉职责 + 预计镜头数信号（带 `渐进` 的 beat 预计多镜）。用户确认后文案锁死。

### 阶段 2 · 旁白与配乐（付费门）

```powershell
python scripts/generate_audio.py out/<name>            # dry-run 报价
python scripts/generate_audio.py out/<name> --submit   # 确认后
```

- 旁白（`voice.group: auto` 默认）：相邻 beat 按章节拼成一条文案、一条 `voice-clone-emo` 任务一次说完（通常一章一组；章节预估超 90s 才拆组兜底），组内语气与停顿自然；全片同一声音（内置音色不传参考音；克隆则所有任务传同一参考音），不支持 voice_id/emotion/speed。`voice.group: beat` 退回每 beat 一条（改单句返工更省）。
- 整组下载后做**本地免费对齐**：silencedetect 找全部句间停顿，全局 DP 选边界（每句语速一致性 + 标点加权位置先验 + 长停顿奖励），并校验每段语速 0.10–0.50s/字；失败即停（保留原始音频，不自动花钱重试），改稿或临时切 `beat` 重跑。对齐后归一化成 `audio/seg_gXX.m4a`（段首 lead 0.20s、段尾 0.45s，章节卡组段首烘 1.4s 静音），它就是全片主时间轴。
- 配乐（可选）：`music-yue2` 只传英文 style、不传 lyrics，取节点 56 伴奏。全部旁白 + 一条 BGM 同一批次。
- 完成后 ffprobe 实测；组内停顿按 beat 切分写入 `audio/pauses_bXX.json`。数据齐备才进阶段 3。

### 阶段 3 · 镜头设计（审批门 2）

```powershell
python scripts/plan_shots.py out/<name>
```

按实测旁白与停顿确定性规划：beat 跨度 `S` 取自主时间轴——分组模式是相邻 beat 语音起点之间的真实窗口（保留自然句间停顿），逐句模式为 `0.20+vo+0.45`；镜头数 `n=round(S/8)` 夹取于 `[ceil(S/15), floor(S/4)]`（有渐进步数时优先取步数）；理想等分切点在 ±1.2s 内吸附最近停顿中点（句号停顿 ≥0.45s 优先），保证每镜成片使用长度落在 4–15s；吸附不到标 `forced_no_pause` 并警告。分组模式**所有镜头精确裁切到 used 时长**（音频是主时间轴，不允许整数秒余量累积），逐句模式余量落在 beat 末镜。分组模式写完会校验镜头块总长与音频时间轴一致，否则拒绝产出。

输出带时间码的镜头表：shot、起止、切点时间、`cut_basis`、命中停顿时长、模式、建议运镜。模式（first_frame / first_last_frame）**纯按艺术连贯性选择，不考虑价格**；需要改模式或运镜时：

```powershell
python scripts/plan_shots.py out/<name> --mode b03s1:first_last_frame --move b03s2:push_in
```

同时为阶段 4/5 准备英文画面稿文件 `out/<name>/prompts.en.json`（模板由提示词脚本生成；agent 按 script.md 的中文视觉意图写英文 `scene_en/motion_en/last_frame_change_en/avoid_en`，写好后重新生成提示词）。

### 阶段 4 · 关键帧（付费门，两波）

```powershell
python scripts/generate_keyframe_prompts.py out/<name>   # 离线组装英文提示词并校验
python scripts/generate_keyframes.py out/<name> --wave first --submit   # 波次 A：全部首帧
# 用户检查首帧（弱图在此重滚最便宜）
python scripts/generate_keyframes.py out/<name> --wave last --submit    # 波次 B：首尾帧镜头的尾帧
```

- 首帧：`image-gen-qwen`（只扣 RH 币），`aspectRatio` 按项目画幅映射。
- 尾帧：`image-edit-qwen` 单图编辑，指令锁定「同主体同场景同构图同风格，仅改变 last_frame_change_en 描述的姿态/状态」。
- 每波一个批次，失败即停；首帧波次失败不投尾帧。

### 阶段 5 · 图生视频（付费门，一个混合批次）

```powershell
python scripts/generate_clip_prompts.py out/<name>      # 离线英文视频提示词（FL2VA 按提交整数秒分段）
python scripts/generate_clips.py out/<name>             # dry-run，展示每镜秒数与模式
python scripts/generate_clips.py out/<name> --submit
```

- 首帧镜：`i2v-minimax-h3-first-frame`；首尾帧镜：`i2v-minimax-h3-first-last-frame`（分段提示词，尾帧必填）。两种类型混在同一池批次。
- 每镜提交整数秒 `durationSeconds=clamp(ceil(used_duration_s),4,15)`；视频端显式传 `aspectSelect`（不用 6=跟随首帧）。
- 下载后 ffprobe 复核源片长度 ≥ 该镜需覆盖时长，不足即失败停住。只等这一批，失败绝不自动重发。

### 阶段 6 · 本地合成

```powershell
python scripts/assemble.py out/<name>
```

- 旁白实际时长决定 beat 跨度，切点对齐停顿；末镜保留完整整数秒源片，beat 间无黑场。
- 字幕：Pillow 2× 超采样渲全幅透明 PNG 再 overlay（不用 drawtext）；白字+深色描边+软阴影、无背景框，底部留 6%，宽度阈值 90%。
- BGM：确定性时间窗闪避（旁白窗压低），`-stream_loop -1` 铺满。
- 章节（实测成片 ≥90s 时建议）：本地渲染的章节 chip + 顶部章节进度条，零生成成本；全屏章节卡需在 front matter 显式 `chapter_cards: true`。
- 画布分辨率按画幅映射（16:9→1280×720，9:16→720×1280 等），非目标比例源片 scale+pad 兜底。

### 阶段 7 · 验证与交付

- ffprobe 时长/流；首中尾抽 JPG；多镜 beat 切点前后各抽一帧；章节 chip/进度条核对；纯旁白 stem 与成品混音的电平量化验收。
- 可选媒体 QA（`scripts/qa_understand.py`，先走 dry-run 报价）：默认按 shot 质检（TEXT_OK/TEXT_LEAK/DUTY_MATCH/CONTINUITY/VERDICT，问题带该镜规格）；整片质检可选。直接送原文件给 media-understand（本地文件自动上传；前置断言 ≤1GB、≤2h，超过 1GB 时自行托管成 URL 再调用），无 `DASHSCOPE_API_KEY` 时跳过、不阻塞。
- 报告时长/花费/复用，`MEDIA:<绝对路径>` 交付。

## 画幅

项目级 `aspect` 默认 16:9，可在阶段 1 指定：16:9 / 9:16 / 1:1 / 4:3 / 3:4（图文两端共同支持的才放行；21:9 视频端无对应值，直接报错）。映射：图像 `aspectRatio` 与视频 `aspectSelect`（16:9→5、9:16→4、1:1→1、4:3→3、3:4→2）在阶段 0 解析快照。

## 失败与复用

- 旁白改动：该 beat 音频→停顿→镜头→关键帧→视频级联失效；只改视觉意图：英文提示词哈希漂移，脚本列出需 `--force` 重滚的镜头；只改尾帧变化描述：只重投尾帧编辑与该镜视频。
- 池侧启动级失败自动补投（code=1000，默认最多 2 次）；其他错误码失败即停、报告 poolId。
