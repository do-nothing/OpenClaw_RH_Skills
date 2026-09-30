# Vox 拼贴 MVP：实战坑位与修复（Windows + RunningHub）

这些规则来自一次真实端到端跑通（《贝壳凭什么？》18 秒，4 镜）。按“现象 → 根因 → 做法”记录，都是已经被验证过的修复，不要重新踩。

## 1. 中文分镜文字会被模型渲染进画面（最关键）

**现象：** 关键帧顶部出现整句中文场景描述，或时间线/报纸上出现乱码伪汉字。

**根因：** 把中文 `scene` / `element_motion` / `palette_note` 直接写进图像提示词后，图像模型会把提示词里的中文当成画面文字去画。

**做法（已固化进 `generate_keyframe_prompts.py`）：**

- 分镜里中文与英文画面字段严格分离：
  - 中文 `scene` / `element_motion` / `palette_note`：只给人和 agent 看，用于旁白与分镜沟通，**绝不进入图像提示词**。
  - 英文 `scene_en` / `element_motion_en` / `palette_en`：唯一允许进入图像模型的画面描述；除引用 `headline` 外不得含中文。
- 提示词显式加“严格文字规则”：除指定中文标题外，不渲染任何可读文字、字母、数字、报纸标题、标签、店招、时间线文字；史料纸片只用抽象不可读墨痕。
- `new_project.py --strict` 校验三个 `_en` 字段：非空、长度区间、无中文、无占位符。
- 标题镜头的中文 `headline` 精确保留，并用引号给出“只渲染这些字”。

## 2. 道具/主体在关键帧就画错，重生成视频没用

**现象：** s2 小人手里是橙色篮球而不是海贝壳。

**根因：** 错误在关键帧里已经存在，图生视频只是忠实让它动起来。

**做法：** 发现主体/道具错误时，返工顺序必须是 **关键帧 → 人工确认 → 视频**，不能只重做视频。在 `scene_en` 里用否定句锁死道具，例如：

> clearly holding in both hands a single recognizable spiraled sea shell … NOT a ball, NOT a sphere, NOT any sports equipment, NOT orange.

## 3. H3 first-frame 任务的时长是参数，不是固定 8 秒

**现象：** 以为时长固定，其实池类型 `i2v-minimax-h3-first-frame` 的 `durationSeconds` 接受 4–15 整数（默认 5）。

**做法：**

- 本地合成预算按 8 秒源片设计（每镜 LEAD 0.20 + 旁白 + TAIL 0.45，7.35s 语音硬上限），所以脚本固定传 `durationSeconds=8`、`aspectSelect=5`（16:9）。
- H3 **没有分辨率参数**，输出原生分辨率；assemble 用 scale+pad 兜底到 1280×720。
- 别把"模型通用介绍"的参数当成具体 SKU，一切以 runninghub 技能 `task-types.json` 的类型定义为准（改动前 `pool.py` 查类型信息）。

## 4. 池类型的文件参数走本地路径，池自动上传

- typed job 里文件类参数（如 H3 的 `image`）直接写本地文件绝对路径；`pool.py` 入队时自动上传（带缓存），不要手写 RH 上传字段。
- `outputName` 是**无扩展名 stem**：单结果落 `<stem>.<真实ext>`，多结果 `<stem>_0.<ext>`；回写 `clip_path` 时以池状态行 `OUTPUT_FILE:` 为准，不要假设扩展名。
- 每阶段整批入队时带 `--manual`（不启后台 watcher），由 `rh_pool_client.py` 自己 tick 推进；一个批次只等这一批 poolId。

## 5. Windows 编码（GBK / 中文提示词）

**现象：** 调用 `pool.py` 等子进程时抛 `UnicodeEncodeError: 'gbk' codec`；PowerShell 控制台把中文和 em dash、弯引号显示成乱码。

**做法：**

- 所有封装脚本开头对 stdout/stderr 做 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
- 调用 RunningHub 子进程时注入环境变量 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，并用 `encoding="utf-8", errors="replace"` 捕获输出。
- 控制台打印尽量用英文/ASCII 状态行（DRY-RUN、Saved、Task ID 等），避免因终端代码页误判参数。控制台显示乱码不等于传给 API 的参数乱码，以实际提交命令和结果文件为准。

## 6. 字幕走 Pillow，不用 drawtext（Windows 字体路径 + 行高双重坑）

**历史现象：** drawtext 用 `fontfile=C\:/Windows/Fonts/simhei.ttf` 会报 `No option name near '/Windows/Fonts/...'`（盘符冒号被滤镜当选项分隔）；而且 drawtext 的中文字体内置行高会让两行字幕空一行。

**做法（已固化）：**

- **字幕不再用 drawtext**，改由 `render_caption_png()` 用 Pillow 直接读 `C:\Windows\Fonts\simhei.ttf` 渲全幅透明 PNG（2× 超采样），再 overlay；详见第 8 节。因此无需复制字体到 `_seg/`，也没有盘符冒号问题。
- ffmpeg 9 输出单帧用 `-update 1`，消除 image2 的 sequence pattern 警告。
- Gateway 刚装完 ffmpeg 后 PATH 未继承：封装脚本先 `shutil.which`，找不到再回退到 winget 全路径
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*-full_build\bin`。

## 7. 音频闪避：不要依赖 sidechaincompress（曾只在 s1 生效）

**现象：** 成片只有第一句旁白听得清，后三句像“消失”了。

**根因：** `sidechaincompress` 在“分段 adelay 后再 amix”的人声轨上只在第一段稳定触发，s2–s4 的 BGM（峰值约 −7～−8dB）没被压低，盖住了旁白。人声明明都在，但被音乐淹没。

**做法（已固化进 `assemble.py`）——用确定性时间窗音量包络，不用侧链：**

1. ffprobe 读出每段旁白真实时长。
2. 每句旁白前导 `LEAD_S=0.20s` **只在偏移里加一次**（早期版本在 offset 和 adelay 各加一次 0.15s，会整体错位）。
3. BGM：基础 `volume=0.45`，再叠加 `volume=0.20:enable='between(t,a,b)+between(t,c,d)...'`，旁白窗内固定压低。
4. 旁白整体 `volume=1.35` 提亮，再 `amix(normalize=0)`。
5. BGM 用 `-stream_loop -1` 循环输入，再 `atrim` 到总时长：复用的旧 BGM（如 23s）短于新片（如 30s）时尾部不会突然没音乐。
6. 混音末尾 `apad=whole_dur=<总时长>` 补齐。

**注意：** 时长、偏移、闪避窗口现在全部由旁白实际长度统一推导（见第 9 节），不要再用 beats 里的 `dur_s`。

**验收方法（必须量化，不能只“听一下”）：**

- 单独渲染“纯旁白 stem”，在每个 beat 窗用 `volumedetect` 确认每句都有电平。
- 在成品混音里分别取“旁白核心窗”和“旁白间隙窗”，确认间隙 BGM 明显更低。
- ffprobe 确认成片时长等于各镜头计算时长之和。

## 8. 字幕必须逐字等于旁白，不要用精简 caption

**现象：** OpenClaw 移植早期单独设了 `caption` 字段并允许“比旁白更短”，导致屏幕字幕和听到的旁白不一致。

**源技能做法：** 上游 `vox-director-source` 数据里只有 `narration`，`assemble.py` 直接 `render_caption(beat["narration"], …)`，字幕仅做换行不改写。

**做法（已对齐）：**

- 不再设/不再要求 `caption` 字段；屏幕字幕逐字使用 `narration`。
- `new_project.py` 模板与严格校验已移除 caption，只保留 narration（4–45 字，推荐 12–22 字；最终以 generate_audio 的 7.35s 时长校验为准）。
- **字幕用 Pillow 渲染透明 PNG 再 overlay，不要用 drawtext。** drawtext 采用字体内置行高，中文两行之间会凭空多出近一行的空隙（调 `line_spacing` 为负数也不可控、还会吃标点/描边）。`assemble.py` 的 `render_caption_png()` 逐行按显式像素行高摆放（`CAPTION_LINE_HEIGHT=1.15` 倍字号，中文方块字适用；英文才需源技能默认的 1.30），2× 超采样后缩回 720p，小字笔画清晰。`wrap_cjk(text, font, max_w)` 用 Pillow `textlength` 量**真实像素宽度**（不再按全角字估算，中英数字混排如“2100万枚”更准），先在 `，、；：` 标点后断句、单个小句超长才按字硬切。
- **换行阈值取画面 90%（`CAPTION_WIDTH_RATIO=0.90`）：能一行就一行。** 中文是等宽方块字、边缘整齐，比英文耐满；90% 时两侧仍至少留 64px。早期用源技能给英文的 80%，导致 85% 宽的句子被白白拆两行。实测：18–24 字句全单行，仅 41 字的 s3 两行。
- **观感对齐源技能 `white` 样式：白字+深褐描边+高斯软阴影，不要背景框。** 源技能 `text_overlay.py` 明确 `NO band`——靠描边+投影在花哨拼贴上保证可读，而不是盖半透明黑底。曾用 `box=1:boxcolor=black@0.55` 黑框，笨重且多行像空行，已废弃。现用参数（720p，超采样前）：字号 `int(H*0.045)=32`、描边 `round(size*0.08)`、描边色 `0x1a1410`、阴影偏移 (2,3) 高斯模糊 4px、底部留 6%。
- **overlay 滤镜层级别写反：** ffmpeg 是 `[底层][顶层]overlay`，字幕必须是顶层，即 `[bg][1:v]overlay=0:0`（输入 0 是视频、1 是字幕 PNG）。写成 `[1:v][bg]` 会让不透明视频盖住字幕，表面成功但帧里无字。
- **“每次字太多”的根源是文案长，不是字幕器。** 中文旁白写到 40 字以上必然两行且偏挤。首选在分镜阶段压到 12–22 字；长句靠小字号+90% 换行+1.15 行高保持不难看。

## 9. 音画时长必须单一来源：由旁白实际长度决定（最容易错位）

**现象（bitcoin 项目连续踩了三层）：**

1. 旁白交叉：第一句还没说完第二句就开始。
2. 不交叉后音画不符：声音讲 s3，画面还在 s2。
3. 旁白比 8 秒源片还长，视频根本裁不出那么长。

**根因：时长存在两套。** 早期 `assemble.py` 视频按 beats 预设的 `dur_s`（4.0/4.5/4.5/5.0）裁剪，音频却按旁白 TTS 实际长度摆位，总时长用 `sum(dur_s)`。当某句旁白写长了（bitcoin s2/s3 都超过 8.6s），两套长度必然漂移，于是交叉、错位、超源片时长接连出现。

**做法（已重构 `assemble.py`，单一时长来源，v2 以 beat 为单位）：**

- beat 跨度只由 anchor 旁白实际长度决定：`span = LEAD(0.20) + vo_dur + TAIL(0.45)`。
- 单镜头 beat：anchor 用满整个 span。双镜头 beat：`anchor_dur = span − Σdetail_dur`，detail 用各自规划 `dur_s`；旁白从 beat 起点 +0.20s 起、**连续铺过 anchor→detail 切点**，同一条 beat 字幕在两个画面全程显示。
- 视频裁剪、旁白偏移、BGM 闪避窗口**全部读这同一份 beat 计时**，不再读 `dur_s`；前导 0.20s 只在偏移里加一次。
- 硬上限是源片 8s：任一视觉段 `> 8` 直接报错退出。旁白超长（`span` 容不下 anchor 最小长 + detail）时只对该 beat 的 anchor 提速重做 TTS，绝不裁语音、不假拉长视频。
- BGM 用 `-stream_loop -1` 循环铺满总时长，复用的旧 BGM 在长片尾部不会断。
- 合成末尾不再用 `-shortest`（音视频同长）。
- `dur_s` / `target_duration_s` 降级为**分镜规划提示**，不参与最终计时。
- 旧 v1 项目每 shot 即一个 beat（`beat_groups` 归一化），公式退化为原 `shot_dur=LEAD+vo_dur+TAIL`，行为不变。

**前置拦截（已加进 `generate_audio.py`）：** 每段 TTS 一生成完立即 ffprobe，语音 > `8 − 0.20 − 0.45 = 7.35s` 就停止，并打印该镜需要的提速倍率和可直接复制的 `--only sN --speed x --force --submit` 命令，不让问题拖到合成阶段。

**分镜阶段就要写短：** 正常语速中文 TTS 约 0.2–0.24s/字，7.35s ≈ 30 字上下，数字/英文读得更久。旁白按 12–22 字写最稳；超过 ~30 字基本会超 8s 源片预算。

## 10. 旁白超时怎么返工

- 优先在分镜阶段把旁白写短（推荐 12–22 字），这是零成本、最自然的解法。
- 已经生成后才超时：只对该镜提速重做 TTS（例：1.05 → 1.18，把 8.65s 压进 7.35s），不要改镜头结构、不要裁语音。
- `generate_audio.py --only s4 --speed 1.18 --force --submit`：只重做单段；`--only` 时不重复生成 BGM。
- shell-money 项目曾用此法把 5.56s 旁白以 1.17 速压到 4.55s。

## 11. 分阶段返工与 --only

- `generate_keyframe_prompts.py`、`generate_keyframes.py`、`generate_clip_prompts.py`、`generate_clips.py`、`generate_audio.py` 都支持 `--only s2,s4` 与 `--force`。
- 默认复用已存在的非空素材；返工只重做受影响镜头，省钱、省时间。
- 关键帧改动后，必须级联刷新该镜的 `clip_prompt` 和视频；旁白/字幕改动只需重跑音频与合成。

## 12. 慢任务等待纪律：任何失败都不能自动重提（真实教训）

**现象：** bitcoin 项目只需要 4 条视频，实际提交了约 10 次、生成了 9 条，多出的都浪费了。原因是执行者只等了几分钟就以为任务卡死/丢失，重复运行提交脚本。

**铁律：**

- 图生视频是慢任务，单次可能 **10–20 分钟甚至更久**；几分钟没结果完全正常，不等于失败。
- 一次提交后只能等待这一个任务，**禁止因为等待时间长、看不到新输出就重新运行提交脚本**。
- 失败、超时、或已拿到 poolId：立刻停止本阶段，报告池类型/poolId/错误，**必须等人工确认后才能重新发起**。
- 判断进度优先看本地输出文件是否出现、RunningHub 后台任务状态，而不是看本地脚本有没有新打印。
- 长批量提交建议让脚本一次跑完并耐心等待；要分段提交就用 `--only`，但同一条任务绝不能因为“等不及”再发一次。

## 13. 成本与节奏实测参考（RH 算力币，具体数以池账本 COINS 行为准）

- `image-gen-qwen` 关键帧：**零现金**，只扣 RH 算力币（Qwen 文生图额度），适合反复重滚弱图。
- `i2v-minimax-h3-first-frame`（MiniMax H3，plus 实例）：池里最贵的一档，量级参考——H3 多参考测试约 **348 算力币/条**；first-frame 单图以实际 `COINS:` 行结算。
- `voice-clone-emo` 旁白：实测 **10 算力币/段**（默认音色，poolId 38 已验证）；`music-yue2`（含人声分离）实测约 **7～9 算力币/条**（poolId 41/44 已验证）。
- 只有显式改用 `image-edit-banana2` 等类型才产生第三方现金（约 ¥0.19/张）。
- 关键帧/TTS 较快；视频是慢任务，单条可能 **10–20 分钟**。全程坚持"一个批次只等一次，任何失败都不自动重新入队"。

## 14. 可选：用 media-understand 做自动 QA（不是 RunningHub）

QA 走姊妹技能 **media-understand** 的 `ask`（Qwen3.8-Omni，阿里云百炼，token 计费约 ¥0.01–0.05/镜），需要 `DASHSCOPE_API_KEY`；不再调用任何 RH 视频理解端点。

**实测采信边界（重要）：** 中文标题 OCR、旁白逐字转写、镜头数/总时长估计（±3.5%）可采信；**精细动作方向、BGM 情绪/哼鸣、拟声音效不可盲信**，必须人工抽帧/听片复核。另外 QA 问题**必须带该镜头 brief**（headline 原文 + `qa_prop` 关键道具），否则模型会漏掉风格违规——曾发生成片里真有简笔画 3D 符号（违反 NOT 3D），但空 spec 问题下模型没判失败。

封装 `scripts/qa_video_understand.py`：在 beats 给镜头填 `qa_prop`（要核验的关键道具），默认 dry-run，`--only s2 --submit` 才调用；固定标签问题让模型回 `TITLE_OK / PROP_PRESENT / TEXT_LEAK / STYLE_2D / MOTION / VERDICT`，完整答案落盘 `qa/qa_sN.txt`，VERDICT 回写 beats.json。作为**可选环节**在视频阶段后按需启用，不要默认强制跑。
