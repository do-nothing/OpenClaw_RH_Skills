# 调研笔记：讲稿优先型内容讲解片（2026-10-01）

> 目的：为 explainer-studio 技能设计提供外部参照。分为「行业工作流共识」「脚本结构」
> 「多媒体学习理论（学术依据）」「可参考工具」四块，附来源。

## 1. 行业工作流共识（Script → Voice → Visuals）

2026 年多家讲解片制作平台/指南的流程高度一致，均为**先写稿、再配音、最后配画面**：

- Astorie：讲解片的四个锁定输入 = 为耳朵写的脚本、旁白音色、B-roll/讲述镜头、
  画面文字；镜头按「已计时的旁白」逐 beat 规划，切点直接对齐旁白
  （[来源](https://astorie.ai/blog/how-to-create-ai-explainer-videos)）
- Cliprise 四阶段：Script（一切的地基）→ Voiceover（ElevenLabs，进下一阶段前质检）
  → Visual Generation（按脚本匹配画面）→ Assembly
  （[来源](https://www.cliprise.app/learn/workflows/marketing/ai-explainer-video-workflow-script-voice-video-cliprise)）
- Versely：brief → script+storyboard → 按镜头类型选模型生成 → 配音/配乐/交付
  （[来源](https://www.versely.studio/blog/how-to-make-an-ai-explainer-video-in-30-minutes-2026)）
- AI Tools Guidebook：失败模式总是「先有酷炫画面、再让稿子迁就」；
  正确顺序是 script first，8–10s 的生成块与旁白短语一一对应
  （[来源](https://aitoolsguidebook.com/en/articles/ai-explainer-video-tutorial/)）

**对本技能的含义**：「旁白先行、画面服务讲解」不是我们自创，而是行业成熟范式；
explainer-studio 与 vox-director-rh 的差异正好对应这两种创作心智。

## 2. 脚本结构参考

### 英语市场
- 字数基准（口播）：30s ≈ 75 词 / 60s ≈ 150 词 / 90s ≈ 220 词；
  超过 90s 的内容应拆成两支片子，而不是硬塞
  （[Astorie](https://astorie.ai/blog/how-to-create-ai-explainer-videos)）
- 爆款短视频 4 段式：Hook(0–3s) / Setup(3–15s 建立语境和赌注) /
  Main-Payoff(15–40s 交付价值) / CTA(最后 5s)
  钩子类型实测效果：故事钩 9.1 > 设问钩 8.8 > 视觉打断 8.6 > 命令钩 8.4 > 数字钩 7.9
  （[Viralo](https://viralo.studio/blog/script-structure-viral-short-form-video)）
- 长一点的 5 段式：Cold Open / Promise / Body（每 60–90s 一个 micro-hook +
  open loop 模式）/ Climax / CTA
  （[Mark Studios](https://www.markstudios.com/blog/video-scripting-hooks-cold-opens-that-retain-viewers)）

### 中文知识类
- 科普中国方法论：一个视频只讲**一个核心知识点**；三段式 = 开场抛结论 →
  中间 2–3 个小点拆解（每点 ≤30s）→ 结尾总结+延伸；知识从大众认知切入再深入
  （[科普中国](https://m.kepuchina.cn/tuwendetail?id=648995)）
- 完播率实战：黄金 3 秒（反常识/痛点/视觉冲击/利益承诺）；
  内容本身制造连环钩子（"第三个 90% 的人不知道"）；删除「大家好」类无效开场
  （[B站案例](https://www.bilibili.com/opus/1188348486531153929)）
- 画面/信息每 7–10 秒更新一次；复杂概念用具象比喻可视化
  （[科普中国](https://m.kepuchina.cn/tuwendetail?id=648995)）

### 本机实测（voice-clone-emo 内置音色，中文）
- 语速约 **0.21–0.24 s/字**（含句中停顿），写稿预估用 0.24×字数 最保守
- 例：29字→6.79s / 35字→7.73s / 41字→8.50s

## 3. 学术依据：Mayer 多媒体学习原则

R. Mayer（UCSB）基于数十年认知负荷实验提出，解释「什么画面真的帮人学懂」。
论文：[Evidence-Based Principles for How to Design Effective Instructional Videos
(2021)](https://sci-hub.st/downloads/2021-05-13//4c/mayer2021.pdf)；
通俗整理：[Mayer's 12 Principles](https://www.participationandlifelonglearning.co.uk/mod/book/tool/print/index.php?id=16438)

| 原则 | 内容 | 对分镜/画面的规则含义 |
|---|---|---|
| Multimedia | 文字+画面优于纯文字 | 每个 beat 必须有视觉解释，不做无画面空段 |
| Coherence | 删掉无关的画面/声音/装饰 | 最常被违反；拼贴装饰不得喧宾夺主 |
| Signaling | 高亮关键材料 | 关键词/数字用画面强调（箭头、放大、对比色） |
| Redundancy | 旁白+画面+逐字屏显三者并存反而更差 | 见下方「字幕口径」讨论 |
| Spatial/Temporal contiguity | 相关图文同时同地出现 | 说到什么，画面此刻就展示什么（时间对齐） |
| Segmenting | 复杂内容分段渐进呈现 | 支持 beat→多 shot 渐进揭示 |
| Modality | 画面旁解说优于画面旁屏显文字 | 信息靠"说"，画面不做大段文字 |
| Personalization | 对话体优于书面体 | 口播稿口语化 |
| Voice | 真人感、悦耳的声音 | 音色审批门 |
| Pre-training | 先给关键概念名称 | 术语在讲解前先给定义 |

**字幕口径的张力（需要技能内明确表态）**：Redundancy 原则反对逐字屏显，
但社媒静音自动播放场景又需要字幕。建议口径：
- 全量逐字字幕仅作为**分发层**（社媒平台自动字幕或底部窄字幕条），
  不与画面内的信息性文字重复；
- **画面内文字只放关键词/数字/结论**（Signaling），绝不整句复刻旁白。

## 4. 可参考的成熟工具（只参考，不依赖）

- [AutoFlowCut](https://touchizen.com/en/autoflowcut/)（开源 AGPL，Win/Mac）：
  Story 模式 = Research → Synopsis → Script → Scene split（按句或按时长拆）→
  Audio → Prompts；可批量生图/生视频并导出 CapCut/Premiere/Vrew 工程。
  「按句/按时长拆分场景」的交互值得借鉴
- [ScriptTask](https://scripttask.com/zh)：粘贴脚本→自动拆分段→配音/角色/分镜/字幕；
  改一段只重渲一段（增量复用思路与我们一致）
- [Recapo](https://recapo.ai/zh)：长素材拆解（解说/切片/营销），适合二创场景，
  与本技能「从零创作」定位不同
- Astorie / Cliprise / Versely：SaaS 画布，流程参照第 1 节

## 5. 尚未覆盖、后续会话可补查

- Qwen Image 2.1 / H3 在「信息图、图表、箭头、数字」类画面上的具体提示词规则
- 中文 ASR 静音检测切分的参数经验值（silencedetect 阈值）
- 长片（90s+）章节化（进度条章节、章节卡）的做法
