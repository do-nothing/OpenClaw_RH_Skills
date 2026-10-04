# script.md 讲稿格式（唯一人工编辑源）

每个项目一个 `script.md`。结构：YAML front matter + beat 正文。
`sync_script.py` 把它解析进 `explainer.json`；旁白用哈希做级联失效依据。

## Front matter

```yaml
---
project: compound-interest          # 英文/数字短名，目录名一致
topic: 为什么复利能让小钱变大钱？     # 一句话知识点
audience: 没有理财基础的普通上班族     # 观众已有认知水平
core_takeaway: 关键不是本金大小，而是让收益继续参与增长
tone: 口语、对话感、好奇、不贩卖焦虑
target_duration_s: 90               # 仅规划参考（0-300，0=不指定）；最终时长由实测旁白决定，不用它卡内容
aspect: 16:9                        # 16:9(默认)/9:16/1:1/4:3/3:4
visual_style: clean-diagram         # clean-diagram/paper-collage/swiss-infographic/warm-editorial
voice:
  mode: tts                         # tts=内置音色；clone 需 sample_path
  group: auto                       # auto=按章整组一次合成（默认，语气连贯）；beat=逐 beat 合成
  sample_path:
music:
  enabled: true
  duck: true                         # false=BGM 恒定 0.22 铺底，旁白间隙不浮起
  prompt: 克制的纪录片配乐，弹拨乐器与轻打击，纯器乐，无人声
captions: true
chapter_cards: false                # true 才插入全屏章节卡（默认只有 chip+进度条）
chapters:
  - { id: c1, title: 钱怎么变大, from_beat: b01 }
  - { id: c2, title: 时间的力量, from_beat: b04 }
---
```

规则：

- `voice.group`：`auto`（默认）把相邻 beat 按章节拼成一条文案一次合成（通常一章一组；章节预估超 90s 才兜底拆组，上限不是平台限制，是控制重配费用的工程值），组内语气与停顿自然；下载后本地对齐回每个 beat，音频成为全片主时间轴。`beat` 为逐 beat 合成（改单句后 `--only` 返工更省，节奏为固定 0.45s 句尾）。对齐失败不自动花钱重试，改稿或临时切 `beat` 后重跑。
- `chapters` 可选；实测成片 ≥90s 时建议 2–4 章，每章至少 2 个 beat；标题 ≤8 字；`from_beat` 必须存在且递增。
- 不写 chapters = 整片无章节，脚本不自动猜。
- 章节 chip/进度条由本地合成层渲染，绝不进 AI 生成图。

## Beat

二级标题切 beat，编号必须是 `b01、b02…` 且连续；标题后面的中文名只给人看：

```markdown
## b03 机制

复利，就是赚到的收益不拿走，继续放进本金里，下一轮一起产生新收益。

- 视觉职责：mechanism
- 看到：本金长出硬币，硬币没有被拿走，而是滚回本金堆，下一轮本金堆变大
- 文字：收益 → 本金
- 渐进：
  1. 本金产生一笔收益
  2. 收益留在池子里
  3. 更大的本金产生更多收益
- 连贯：沿用 b02 的硬币和圆盘，不换主体
- 禁忌：不要出现真实货币符号、银行 logo
```

1. **标题后的第一段纯正文是该 beat 唯一旁白原文**，直接送 TTS、逐字做字幕。
   一个 beat 可含多个句子，但属于同一条连续旁白；列表/注释绝不进 TTS。
2. 视觉字段（受控，未识别字段报错）：

| 字段 | 必填 | 内容 |
|---|---|---|
| `视觉职责` | 是 | hook / subject / definition / mechanism / compare / evidence / analogy / keyword |
| `看到` | 是 | 一句话写具体对象与动作；禁止景别、机位、运镜、画风词（特写/俯拍/推镜/慢镜头/海报风等会触发校验警告） |
| `文字` | 否 | 允许入画的关键词/数字/短箭头；`/` 或顿号分隔，每项 ≤8 字，最多 3 项；禁止整句旁白 |
| `渐进` | 否 | 2–3 个有序小步骤，复杂机制的多镜信号；超过 3 步建议拆 beat |
| `连贯` | 否 | 沿用哪个 beat 的主体/场景，供阶段 3 判断首尾帧 |
| `禁忌` | 否 | 不能出现的东西（错误联想、品牌、乱码） |

3. 第一个 beat 职责必须是 `hook`；收尾 beat 建议 `keyword`。
4. 预估时长 = 有效字数（中文字符 + 英文单词 + 数字词元）× 0.24s，仅参考。
   单 beat 预估 >15s 只提示「大概率多镜」；出现两个独立论点才需要拆 beat。

## 视觉职责枚举（8）

| 值 | 认知任务 | 阶段 3 倾向 |
|---|---|---|
| hook | 反常识/痛点瞬间（仅首 beat） | 强焦点、推近 |
| subject | 主体长什么样 | 中近景图示 |
| definition | 「它是什么」概念定义 | 干净图示 |
| mechanism | 因果/流程/循环 | 带渐进→多 shot、首尾帧连贯 |
| compare | 前后/对错/大小/有无对比 | 并列构图或硬切 |
| evidence | 数据、比例、时间线 | 信息图、少装饰 |
| analogy | 具象比喻抽象 | 比喻主体全程一致 |
| keyword | 金句/结论视觉强化（收尾） | static、大字关键词 |

## 锁稿与改动

- `--strict` 通过且用户确认即锁稿：此后 script.md 每一行旁白都有哈希。
- 改旁白：`group: beat` 模式只作废该 beat；`group: auto`（默认）一条整组音频是一个整体，改任意一句作废整组（组内其他 beat 的停顿/镜头时间也会变）。改视觉字段 → 英文提示词需重生成，脚本列出受影响镜头，由用户决定是否 `--force` 重滚。
