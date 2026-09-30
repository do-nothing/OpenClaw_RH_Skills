---
name: vox-director-rh
description: 把一句话选题制作成 Vox 风格纸片拼贴讲解/广告短视频（15–60 秒，16:9）。仅 B-roll：叙事分镜、拼贴关键帧、图生视频、中文旁白、可选配乐、字幕和本地 ffmpeg 合成，媒体生成走 RunningHub。用户提到拼贴视频、Vox 风格、纸片拼贴讲解片、motion collage、拼贴广告、把某个主题/概念做成拼贴讲解视频时使用。
---

# Vox Director (RunningHub 任务池版)

把一句话主题做成一条**纸片拼贴讲解视频**：每个 beat 是一张撕裂纸张拼贴海报，被赋予运动，配中文旁白、配乐和字幕。媒体生成统一走 **RunningHub 通用异步任务池**（`runninghub` 技能的 `pool.py`），本地用 **ffmpeg + Pillow** 合成；可选的视频理解 QA 走姊妹技能 **media-understand**（阿里云百炼 Qwen3.8-Omni，按 token 计费）。

本版本基于上游 Vox Director 移植，技术路线刻意不同：上游跑 Atlas Cloud 且失败自动重投；我们跑 **RunningHub 任务池，禁止自动重发任务**（省钱、防多扣），并固化了中文文字泄漏、8 秒源片、Windows 编码等实战规则。当前只做 **B-roll**（从主题生成全部画面）；A-roll（真人口播拼贴化）、C-roll（单照锚定）、元素级本地动画引擎属后续梯队，见文末。

## 核心思想（先读这个）

拼贴的「样子」和「运动」是两步：

1. **样子在图像步骤诞生。** 每个 beat 是一张由文生图模型做出来的成品拼贴海报。所有拼贴 DNA（撕纸、剪片、半调网点、强色、标题字）都在图里。图不是丰富拼贴，后面救不回来。
2. **运动是后加的。** 默认让图生视频模型让整张海报动起来（"living poster"，全自动）。需要更强烈的节奏时，一个 beat 可拆成 wide 主镜 + detail 特写两个画面，句中硬切。

一切取决于提示词。写任何图像/视频提示词前，视觉读 `references/creative-mvp.md`，故事读 `references/narrative.md`。

## 不可越过的规则

1. 每个阶段完成后必须停下，让用户确认，再进入下一阶段。
2. 所有付费生成前，说明将生成的数量、池任务类型、预计等待时间和费用（RH 算力币/第三方现金），并等待用户明确确认。
3. RunningHub 池任务只等待**同一次入队批次**的结果；排队或处理慢不等于失败，**禁止因等待时间长而重复入队**。
4. 任务失败、超时或已拿到 poolId 后，立刻停止当前阶段，报告 poolId、任务类型和错误，**必须等人工确认才能重新发起，禁止自动重试/重复入队**。
5. 已存在的非空本地素材默认复用，不重复生成；只有用户明确要求重滚才 `--force` 覆盖。
6. 不用 Atlas Cloud，不保存/打印 API key，不执行未审计的上游脚本。
7. 最终视频必须本地抽帧检查，并确认音频、字幕、画幅、时长；媒体文件用 `MEDIA:<绝对路径>` 直接发到聊天窗口交付，不要只贴本地路径。
8. 动手前必读 `references/pitfalls.md`（中文文字泄漏、8 秒固定、Pillow 字幕、音画时长、Windows 编码、禁重发等已验证修复）。
9. 中文分镜字段（`scene`/`element_motion`/`palette_note`）只用于沟通和旁白，**绝不进入图像/视频提示词**；进模型的只能是 `_en` 字段，中文只允许出现在 `headline`。

## 能力范围

- 时长：**15–60 秒**（`--duration` 接受 10–75）。长片靠**更多 beat**，不是更长的单句。
- beat / shots：一个 beat = 一句旁白 + 一条字幕，含 1 个 **anchor** 主镜（WIDE，带标题）+ 可选 1 个 **detail** 特写（CLOSE/DETAIL，无标题无旁白，句中硬切）。
- 画幅：仅 16:9（竖屏属后续梯队）。
- 语言：中文旁白、中文字幕。
- 视觉主题（10）：newsprint-editorial、swiss-modern、chinese-ink、american-retro、punk-zine、soviet-constructivist、wpa-propaganda、70s-groovy、atomic-age、gilded-deco。
- 叙事弧线 arc（8）：hook_payoff、how_it_works、timeline、myth_buster、pas、bab、man_in_hole、listicle（见 `references/narrative.md`）。
- 运镜（6 个平面安全档）：static、push_in、pull_out、pan、tilt、parallax；相邻镜头不得重复，`static` 留给收尾金句。
- 风格：纸片、撕纸、报纸剪贴、半调网点、平涂色块、大号标题。
- 音频：中文 TTS（`voice-clone-emo` 工作流，默认预置女声，无需样本）；用户给清晰样本时传入样本做声音克隆（情绪表达型）。配乐可选，失败可关掉继续。
- 合成：ffmpeg + ffprobe + Pillow，输出 `final.mp4`。

明确不做：A-roll、C-roll、元素级本地动画引擎、多画幅、英文工作流、大胆档运镜（orbit/dolly_zoom/roll/whip）、自动重发任务。

## 前置检查

- RunningHub 技能可用（通用任务池 `scripts/rh_pool/pool.py`，已配置 API key）、`ffmpeg`/`ffprobe` 在 PATH（找不到时脚本回退 winget 全路径）、Python + Pillow。缺失先报告，不进入生成。
- 可选 QA 需要姊妹技能 `media-understand` 与 `DASHSCOPE_API_KEY`（未配置时引导用户开通，不影响主流程）。

## 标准流程（主题 → 成片）

每个项目一个 `out/<project>/beats.json`，每阶段一个脚本。

### 阶段 0 · 环境检查（免费）

确认上述依赖；不联网。

### 阶段 1 · 选题到分镜（强制审批门 1）

先读 `references/narrative.md`，按主题选 **arc**（历史→timeline、原理→how_it_works、广告→pas/bab、纠偏→myth_buster、逆袭→man_in_hole、盘点→listicle，拿不准用 hook_payoff）。离线建项目，不产生费用：

```powershell
python scripts/new_project.py --project <project> --root out --topic "<一句话主题>" `
  --theme <theme> --arc <arc> --ending hard_cut --duration 30 --music `
  [--detail b3,b6]   # 可选：给这些 beat 追加无标题 detail 特写（多生成画面、多花钱）
```

生成 `beats.json` 与 `keyframes/ clips/ audio/ _seg/` 目录。草稿按时长自动铺好 N 个 beat（见下表），每 beat 带 arc 阶段提示、景别、不重复运镜；b1 是 ≤3s 钩子（含 `hook_type`）。把占位旁白/标题/英文字段替换成正式分镜后，必须过严格校验：

```powershell
python scripts/new_project.py out/<project> --validate-only --strict
```

严格校验通过，才能把**完整分镜（arc、每句旁白、哪些 beat 带 detail）**给用户确认。这是第一个强制门。

### 阶段 2 · 选视觉风格（强制审批门 2）

读 `references/creative-mvp.md`，最多给 3 个主题方向，用文字说明差异，结合主题的时代/文化/语气选（讲中国历史优先 chinese-ink，通用经济概念默认 newsprint-editorial，科技产品 swiss-modern）。用户眼选后再定 `theme`。当前不做真实多风格试片以省成本。

### 阶段 3 · 拼贴关键帧

先离线生成英文关键帧提示词（中文标题精确保留，画面只用 `_en`）：

```powershell
python scripts/generate_keyframe_prompts.py out/<project> --set-default-endpoint
```

提示词含严格文字规则：除指定中文 `headline` 外不渲染任何可读文字、字母、报纸标题、标签、店招、时间线。原理/返工见 `references/pitfalls.md` 第 1、2 节。再 dry-run 看待提交任务（免费）：

```powershell
python scripts/generate_keyframes.py out/<project>          # dry-run
python scripts/generate_keyframes.py out/<project> --submit # 用户确认数量/模型/费用后
```

默认池类型 `image-gen-qwen`（通义万相 Qwen Image 2.1，RH 算力币计费、零现金），只传 `aspectRatio="16:9 (Widescreen)"`，不传分辨率。全片关键帧作为**一个批次**入队（池并发 3，自动排队），脚本用 manual tick 推进并等待同一次批次，失败即停。下载到 `keyframes/`（池按真实类型加扩展名）并回写路径，然后暂停让用户检查拼贴质感、标题、风格一致性。弱图在这一步重滚（便宜），别花钱去动烂图。

### 阶段 4 · 图生视频

关键帧确认后，按视觉镜头（含 detail）生成 8 秒源片（整阶段一个批次）：

```powershell
python scripts/generate_clip_prompts.py out/<project>       # 离线写英文视频提示词
python scripts/generate_clips.py out/<project>              # dry-run
python scripts/generate_clips.py out/<project> --submit     # 确认后
```

- 只用 6 个平面安全运镜；**相邻镜头（含 anchor→detail、跨 beat）不得重复**，节奏序列按 arc（见 `references/narrative.md`）。
- 池类型 `i2v-minimax-h3-first-frame`（MiniMax H3，plus 实例，RH 算力币）：首帧 `image` + `prompt`，`durationSeconds=8`（范围 4–15，8 是本地合成预算），`aspectSelect=5`（16:9）。H3 无分辨率参数，输出原生分辨率，合成阶段 scale+pad 兜底到 1280×720。
- 全片源片作为一个批次入队，manual tick 等待同一次批次，失败即停、绝不重发。
- 主体/道具错误通常关键帧就有，按"关键帧→确认→视频"级联返工，不能只重做视频。
- 可选视频理解 QA 走姊妹技能 **media-understand**（Qwen3.8-Omni，按 token 计费、约几分钱/镜，先 dry-run）：`qa_video_understand.py`，返回 `TITLE_OK/PROP_PRESENT/TEXT_LEAK/STYLE_2D/MOTION/VERDICT`，问题中自动带上该镜 headline/道具 brief（不带 spec 会漏风格违规）。

### 阶段 5 · 旁白与可选配乐

旁白**按 beat** 生成（只有 anchor 产一条 TTS，detail 不产），全片同一声音：

```powershell
python scripts/generate_audio.py out/<project>              # dry-run
python scripts/generate_audio.py out/<project> --submit     # 确认后
```

旁白池类型 `voice-clone-emo`：不传 `referenceAudio` 时走工作流预置的默认女声（已实测可用，零样本）；在 beats.json `voice` 中配置样本路径时传入 `referenceAudio` 做声音克隆。该工作流**不支持** voice_id/emotion/speed 参数。配乐池类型 `music-yue2`：只传 `style`、不传 `lyrics`（工作流用预置假歌词约束结构，再经 RoFormer 人声分离），三个产物中取**伴奏（节点 56）**为纯音乐成品，全片旁白+配乐同一批次入队。也可复用旧项目 `audio/bgm.mp3`（写入 `music.path`，合成自动循环铺满）。

**时长硬预算：** 8 秒源片，每 beat 留 `LEAD 0.20 + TAIL 0.45`，单段语音最多 **7.35 秒**。每条 TTS 生成后立即 ffprobe，超时即停——该工作流无法调速，只能**压缩该 anchor 旁白字数**后用 `--only <anchorId> --force --submit` 单独重做；不裁语音、不改镜头结构、不假拉长视频。

### 阶段 6 · 本地合成

```powershell
python scripts/assemble.py out/<project>
```

- **时长单一来源（beat 级）：** beat 跨度 `span=LEAD+旁白实际时长+TAIL`；单镜头 beat anchor 用满 span，双镜头 beat `anchor=span−Σdetail`。旁白从 beat 起点 +0.20s 起、**连续铺过 anchor→detail 切点**，同一条 beat 字幕在两个画面全程显示。视频裁剪、旁白偏移、BGM 闪避窗口共读这份计时；`dur_s`/`target_duration_s` 仅规划用，所以音画不漂移。
- **字幕用 Pillow 渲全幅透明 PNG（2× 超采样）再 overlay，不用 drawtext**（drawtext 中文字体内置行高会让两行空一行）。滤镜层级 `[bg][1:v]overlay=0:0`（视频为底、字幕为顶）。
- 字幕逐字等于旁白；Pillow `textlength` 量真实像素，标点后优先断句，**宽度阈值 90%（能一行就一行）**，超长才两行（行高 1.15）。样式为源技能 `white`：白字+深褐描边+高斯软阴影、无背景框，字号=短边 0.045（720p=32px），底留 6%。详见 `references/pitfalls.md` 第 8 节。
- BGM 闪避用确定性时间窗音量包络（不用 sidechaincompress），`-stream_loop -1` 循环铺满。

### 阶段 7 · 验证与交付

- ffprobe 检查时长（=各镜头时长之和）、视频流和音频流。
- 从首、中、尾抽 JPG 检查画幅和字幕；双镜头 beat 额外在切点前后各抽一帧，确认字幕贯穿、画面已切。
- 音频量化验收：纯旁白 stem 在每个 beat 窗有电平；成品混音对比"旁白窗"与"间隙窗"确认 BGM 已压低。不能只靠听。
- 报告总时长、路径、各阶段花费与失败/复用；用 `MEDIA:<绝对路径>` 把最终 MP4 直接发到聊天窗口。

## 节奏：镜头该多长

最常见错误是一个 beat 一个长镜头。目标**每 3–5 秒有一次画面变化，单张海报不要挂超过 ~7 秒**。

| 成片 | beat 数 | 每 beat | 旁白字数（中文，参考） |
|---|---:|---|---|
| 15–22s | 4 | 4–5.5s | 12–22 字最稳 |
| ~30s | 6 | ~5s | 12–24 字 |
| ~45s | 8–10 | 5–6s | 12–24 字 |
| ~60s | 10–12 | 5–6s | 12–24 字 |

- 建项时 `--duration` 自动选 beat 数：≤22→4、≤32→6、≤42→8、≤52→10、更长→12。
- 每句旁白仍受 **7.35s ≈ 30 字**物理上限约束；**长片是 beat 更多，不是句子更长**。想紧凑就压字数，这是最便宜的质量开关。
- 双镜头 beat 用在最需要强调的 beat（机制、金句），别全片翻倍。
- 比例：钩子 1–3s → 主体 70–80% → 金句/收尾 10–20%。结尾 `hard_cut`（默认，利重播）/`quick_cta`（≤2s 广告）/`loop_close`（首尾呼应）。

## beats.json 结构（v2）

扁平 `shots[]`，每个 shot = 一张关键帧 + 一条 8s 源片；用 `beat_id` 把 1–2 个 shot 组成 beat。关键字段与全部校验规则见 `references/mvp-schema.md`。要点：

- 顶层：`schema_version=openclaw-vox-mvp-2`、`project/topic/language=zh-CN/aspect=16:9/target_duration_s/theme/arc/ending/voice/music/captions/no_duplicate_submit=true`。
- anchor shot：`id=s1..`、`beat_id=b1..`、`beat_role=anchor`、`shot_size`、`dur_s`、`hook`+`hook_type`(仅 b1)、`title_on_image`、`headline`、`narration`、`scene(_en)`、`camera_move`、`element_motion(_en)`、`palette(_en)`。
- detail shot：`id=s3b`、同 `beat_id`、`beat_role=detail`、`shot_size∈{CLOSE,DETAIL}`、`title_on_image=false`、**无 headline 无 narration**。
- 旧 v1 项目（`openclaw-vox-mvp-1`，4 镜各带旁白）继续被全部脚本支持：每 shot 视为单镜头 beat。

## 池任务类型（workflowId 以 runninghub 的 task-types.json 为准，生成前用 pool.py --info 核）

| 任务 | 池类型 type | 计费 / 备注 |
|---|---|---|
| 关键帧 | `image-gen-qwen`（通义万相 Qwen Image 2.1） | RH 算力币，零现金；只传 aspectRatio |
| 关键帧高质量备选 | `image-edit-banana2`（Nano Banana 2） | 第三方现金约 ¥0.19/张；需手动改脚本 |
| 图生视频 | `i2v-minimax-h3-first-frame`（MiniMax H3，plus） | RH 算力币，较贵；8s / aspectSelect=5(16:9) / 原生分辨率 |
| 旁白 | `voice-clone-emo` | RH 算力币；不传 referenceAudio 走预置默认女声，传样本则克隆；无 voice_id/emotion/speed |
| 配乐 | `music-yue2` | RH 算力币；只传 style，lyrics 省略=假歌词+人声分离，取伴奏节点(56)产物 |
| 可选视频 QA | 不经 RH：姊妹技能 `media-understand`（Qwen3.8-Omni，百炼 token 计费） | 需 `DASHSCOPE_API_KEY`，先 dry-run |

## 失败与复用

- 任一 `keyframe_path`/`clip_path`/`vo_path` 已存在且非空默认复用；各生成脚本支持 `--only s2,s4` 与 `--force`，返工只重做受影响镜头。关键帧改动须级联刷新该镜 clip 提示词和视频；旁白/字幕改动只需重跑音频与合成。
- 失败时在该 shot 写 `last_*_error`，保留 poolId 和池类型，整阶段停止等人确认，绝不自动重发/重新入队。

## 项目状态

当前目录即工作技能目录。上游 MIT License 与版权声明保留（见 `ATTRIBUTION.md`）。后续梯队：9:16 竖屏、paper 字幕样式/水印、更多 TTS 声音、whip 转场（二梯队）；C-roll（需图像 edit）、A-roll（需 video-edit）、元素级本地动画引擎（三梯队）。
