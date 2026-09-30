# Vox 拼贴 MVP 创意规范

本文件只管 16:9 B-roll 所需的最小创意规则（LOOK 层：画面怎么长）。A/C-roll、本地零件动画、大胆档运镜、多画幅均不在本版范围。叙事弧线/钩子/节拍/时长档位在 `narrative.md`。

## 1. 核心视觉 DNA

每张关键帧都必须像一张“可以直接印刷的手工拼贴海报”，而不是普通 AI 插画或会动的 PPT。固定保留这些元素：

- 手撕或剪刀裁切的纸边
- 胶带、纸张投影、纸模板形状
- 半调网点、旧报纸/杂志剪片
- 大块平涂色背景
- 清晰分层、边缘明确的剪纸人物和物件
- 印刷颗粒、轻微套色误差
- 扁平 2D、插画/印刷质感
- 短而粗的标题文字直接生成在关键帧里

禁止把画面做成：3D 渲染、CGI、光滑电商图、纯赛博朋克光效、写实电影截图或无层次的扁平矢量图。

## 2. 三套默认风格

### A. `newsprint-editorial` 报纸社论（默认）

- **适用：** 历史、社会现象、经济概念、知识讲解、反常识问题
- **画面：** 老报纸版面、档案照片剪片、杂志插图、粗黑标题、红/黄重点色块
- **配色：** 米白报纸色、炭黑、深红、芥末黄
- **字体感觉：** 压缩粗黑体、报社头条、全 caps 数字/英文
- **质感：** 旧报纸、重半调网点、轻微油墨错位
- **运动：** 有活力但不过火，适合默认 `punchy`

### B. `swiss-modern` 瑞士现代

- **适用：** 科技、产品、流程解释、数据、商业工具
- **画面：** 网格、几何块面、简洁信息图、大面积留白、明确视觉层级
- **配色：** 白/浅灰 + 黑 + 一个高饱和红色或蓝色强调色
- **字体感觉：** Helvetica/Akzidenz 式简洁无衬线、紧排大字
- **质感：** 干净纸张、轻微颗粒，少胶带和旧报纸
- **运动：** 克制、精确，适合 `calm`

### C. `chinese-ink` 新中式纸本拼贴

- **适用：** 中国历史、传统文化、诗词、文物、东方美学
- **画面：** 宣纸、水墨/木刻人物、书法标题、朱砂印章、中式报纸或票据碎片
- **配色：** 宣纸米白、墨黑、朱砂红、少量石青/赭石
- **字体感觉：** 粗壮中文书法/碑刻感标题，配少量小字
- **质感：** 宣纸纤维、墨迹晕染、木刻印刷、印章
- **运动：** 缓慢、留白、克制，适合 `calm`

选题决定风格，而不是语言决定风格。讲中国历史优先 `chinese-ink`；讲通用经济或社会概念可默认 `newsprint-editorial`；讲科技产品优先 `swiss-modern`。

## 3. beat / 镜头叙事结构

默认按 `narrative.md` 的节拍表选 beat 数（15–22s→4、30s→6、45s→8–10、60s→10–12），beat 内顺序由 `arc` 决定。最短的 `hook_payoff` 4 beat：

| beat | 功能 | 内容要求 | 参考成片时长 |
|---|---|---|---:|
| b1 | 钩子（≤3s 见回报） | 直接抛问题、反常识事实或冲突，不做铺垫 | 4s 上下 |
| b2 | 背景 | 交代时代、场景、人物或问题从哪里来 | 4–5s |
| b3 | 机制 | 展示关键原因、过程或转折，信息最密 | 4–5s |
| b4 | 结论 | 给出洞察、升华或一句记得住的话 | 4–5s |

一个 beat 默认 1 个 anchor 主镜（WIDE，带标题）；可在 b2/b3 这种重点 beat 后加一个 **detail 特写镜**（CLOSE/DETAIL，无标题、无旁白，句中硬切），是可选的节奏升级而非必须。广告/产品类把 arc 换成 `pas`/`bab`（见 narrative.md），不要另造模板。

### 文案要求

- 第一镜前 3 秒必须让观众知道“为什么要看”，给 b1 选一个 `hook_type`。
- 每句旁白约 12–22 个中文字，宁短勿长（硬上限对应 7.35s≈45 字）。旁白归 beat 的 anchor。
- 屏幕字幕逐字等于旁白（合成脚本自动中文换行），不要单独写“精简字幕”。
- `headline` 控制在 20 字以内（建议 4–10 字），只在 anchor 镜出现，detail 镜无标题。
- 不要全片都讲概念；至少两 beat 要有明确物件和动作。
- 最后一句要能独立成立，适合作为记忆点。

## 4. 六种安全运镜

只允许以下六个平面安全 token（均匀平移/缩放，不扭曲画面）。**相邻镜头（含 anchor→detail）不得重复**，`static` 预留给结论/金句 beat。

| token | 用法 | 提示词含义 |
|---|---|---|
| `push_in` | 开场制造关注、聚焦 | 极慢、均匀推近，文字整体一起缩放 |
| `pull_out` | 揭示全局、收尾 | 极慢、均匀拉远，不改变透视 |
| `pan` | 展示时间线、地图、流程、列表 | 水平平移，保持平面，不改变透视 |
| `tilt` | 表现规模、倒数、纵向结构 | 纵向平移，平稳平面 |
| `parallax` | 机制解释、分层场景 | 前景/中景/背景以不同速度轻微移动 |
| `static` | 结论、金句、标题落点 | 镜头锁定，只有纸片元素轻微运动 |

`hook_payoff` 默认节奏：`push_in → pan → parallax → static`；其他 arc 的节奏序列见 `narrative.md`。双镜头 beat 里 detail 要与它的 anchor 换族（如 anchor=pan 则 detail=push_in）。

不使用 orbit、dolly zoom、roll、whip、手持晃动或快速 zoom；这些容易把平面海报变形成 3D，也容易让文字崩坏。

## 5. 元素运动规则

元素运动是纸片“活起来”的主要来源，但要像刚体纸片一样运动。

安全动作：

- 漂移、摇摆、轻晃、滑动、翻转、铰链式摆动
- 纸片几何图形轻微弹入或归位
- 半调网点脉动、胶带轻颤、报纸碎片飘动
- 前景、中景、背景产生小幅视差

限制：

- 元素只能像纸一样移动，不融化、不生长、不变成别的物体。
- 标题、印章、数字和版面必须稳定清晰。
- 可以有多个元素运动，但不要每镜都安排一个横穿全屏的“英雄元素”。
- 一个镜头只使用一种主运镜；元素运动可以丰富，但不能要求复杂剧情时间线。

## 6. 关键帧提示词模板

所有镜头共用同一段风格锚点，只替换场景、颜色和标题，保证系列感。

**字段隔离是硬规则：** 中文 `scene` / `element_motion` / `palette_note` 只用于分镜沟通和旁白，绝不进入图像提示词；提示词只能使用 `scene_en` / `element_motion_en` / `palette_en`。否则模型会把中文分镜句直接画成标题、标签或乱码（详见 `pitfalls.md` 第 1 节）。

英文提示词中必须包含严格文字规则：除精确指定的中文 `headline` 外，不生成任何可读文字、字母、数字、报纸标题、标签、店招或时间线文字；史料纸片只用抽象不可读墨痕。

```text
Mixed-media hand-cut PAPER COLLAGE, modern editorial zine style, flat 2D paper collage.
Clearly separated torn/scissor-cut paper layers, deckled edges, tape, real paper shadows, halftone dots, newsprint scraps, paper-stencil shapes and print grain.
People and objects are printed-image or illustrated paper cut-outs, not 3D, not CGI, not photorealistic.
Scene as layered paper cut-out pieces: {scene_en}.
Background and flat-color palette: {palette_en}.
Add one torn-paper banner with the exact Chinese headline “{headline}” and no other readable text; render only these exact characters, sharp and legible.
Strict text rule: apart from that headline, render no words, letters, numbers, newspaper headlines, labels, signs or timeline text; documentary scraps are abstract unreadable ink marks.
16:9 horizontal editorial poster, straight-on scanned-flat camera, one focal point, clear hierarchy, consistent paper grain.
Visual theme: {theme_description}.
```

当 `title_on_image=false` 时，把标题段替换为：

```text
本镜头不要大标题，只保留小型贴纸、箭头或印章作为图形点缀。
```

### 写场景的方法

不要只写“古代集市”。要写成可被剪成零件的画面；关键道具要写清形态并否定错误物。例如小人携带海贝壳时，要明确 `recognizable spiraled sea shell`，并排除 `ball / sphere / sports equipment / orange`。

中文分镜表达：

```text
远处海岸线和纸浪作为背景，中层是古代集市的帐篷、陶罐和谷物袋，前景是一枚放大的海贝壳、一只交换货物的手、几片票据和几何纸碎；所有物件边缘清楚、分层明确。
```

## 7. 图生视频提示词模板

视频阶段只描述“怎么动”，不要重新发明画面内容。

```text
把这张静态海报变成扁平 2D 纸片拼贴动态图形，保持原有画面、构图、印刷质感和所有文字稳定。

运镜：{camera_instruction}
元素运动：{element_motion}。所有元素都像刚体纸片一样滑动、摇摆、翻转或产生视差，保持纸张边缘和投影。
美学：保留撕纸、胶带、半调网点、旧报纸、纸模板形状和大胆平涂背景。
情绪：{mood}。
色彩：保持原画面的高对比配色和印刷颗粒。
稳定性：这是一个连续单镜头，没有剪辑、没有场景切换；标题、印章、数字和版面清晰稳定；镜头平行于海报，不产生 3D 透视旋转；纸片不融化、不形变、不生成新物体。
```

### 运镜展开

- `push_in`：一次极慢、平滑、均匀的推近，文字和版面作为整体轻微放大。
- `pan`：一次缓慢水平平移，像阅读一张横向纸本长卷，不改变透视。
- `parallax`：镜头基本稳定，前景、中景、背景以不同速度轻微错位移动。
- `static`：镜头锁定不动，只有纸片、胶带和网点有很轻的呼吸感。

## 8. 质量验收清单

### 音频通过标准

- 每句旁白都能在对应镜头窗内听清，不能只有第一句明显。
- BGM 必须无人声；旁白播放时音乐确定性压低，旁白间隙恢复。
- ffprobe 逐段量旁白时长，单句不超过镜头预算；成片总时长等于镜头时长之和。
- 验收时分别检查纯旁白 stem 与成品混音，不能只凭一次试听判断。

### 关键帧通过标准

- 一眼能看出纸片拼贴，而不是普通插画。
- 至少能辨认出撕纸边、胶带、网点、报纸剪片、纸片投影中的 3 项。
- 主体只有一个视觉焦点。
- 背景是克制的平涂色或纸张纹理，不抢主体。
- 标题短、准确、清晰，没有错字、多字或乱码。
- 除标题外没有可读文字，中文分镜句没有泄漏成画面文字。
- 关键道具/主体与分镜一致（如“海贝壳”不能画成球）；发现错误先返工关键帧，再重做视频。
- 四张图像像同一套片子，纸张颗粒和版式语言一致。

### 视频片段通过标准

- 文字不扭曲、不闪烁、不被重新拼写。
- 画面保持扁平 2D，没有明显 3D 化或透视翻转。
- 纸片元素不融化、不变形成其他物体。
- 一个镜头内没有突然切镜头或场景跳变。
- 运动幅度小而明确，镜头结束时稳定。
- 关键道具在整段中不变成别的物体。
- 整片运镜要有变化，收尾/金句 beat 有“落下来”的静态收束感。

## 9. 失败处理

- 关键帧不符合拼贴质感：停止批量生成，先只调整一镜的提示词，由用户确认后再继续。
- 图生视频文字崩坏：优先考虑后期字幕承载文字，后续关键帧减少烧入标题；不得静默反复提交。
- 图生视频发生 3D 形变：降低运动幅度，改成 `static` 或更保守的 `push_in`，但必须经用户确认后才能重新生成。
- 任一 RunningHub 任务超时或失败：报告端点、任务 ID、镜头 ID 和错误，等待用户决定是否重试。
