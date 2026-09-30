# RHClaw — RunningHub Skill for OpenClaw / DeepSeek Harness

[English](./README_en.md)

> ## 现已支持 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
>
> 与 [OpenClaw](https://github.com/openclaw/openclaw) 共用同一套标准 `SKILL.md`，安装和更新方式相同。

为 OpenClaw 和 DeepSeek Harness 打造的通用多媒体生成技能，由 [RunningHub](https://www.runninghub.ai) API 驱动。

**420 个标准 API 端点 + 9 个内置异步工作流 + 无限 AI 应用**，覆盖图片、视频、音频、3D 模型生成、多模态文本理解，以及任意用户创建的 AI 应用（ComfyUI 工作流）。

## 能力一览

| 类别 | 端点数 | 支持任务 |
|------|--------|----------|
| **图片** | 102 | 文生图、图生图、图片放大、Midjourney 风格 |
| **视频** | 230 | 文生视频、图生视频、首尾帧生成、视频续写/编辑、运动控制、多模态视频 |
| **音频** | 20 | 文字转语音、音乐生成、声音克隆 |
| **3D** | 16 | 文字转 3D、图片转 3D、多图转 3D |
| **文本** | 52 | 图片理解、视频理解、文本处理 |
| **异步工作流（任务池）** | 9 个内置类型 | Qwen/Nano Banana 出图改图、MiniMax H3 首帧/多参考生视频、语音克隆、数字人口播、文生音乐；支持批量提交、后台运行、断点续传 |
| **AI 应用** | 无限 | 运行任意 RunningHub AI 应用（自定义 ComfyUI 工作流） |

## 快速开始

### 安装

在 OpenClaw 或 DeepSeek Harness 对话中发送：

> 从 https://github.com/HM-RunningHub/OpenClaw_RH_Skills 安装 RunningHub 技能

助手会自动克隆仓库、复制文件到工作区，并引导你完成 API Key 配置。

### 更新

当技能有新版本时，在 OpenClaw 或 DeepSeek Harness 对话中发送：

> 从 https://github.com/HM-RunningHub/OpenClaw_RH_Skills 更新 并重新读取@runninghub/SKILL.md

助手会拉取最新代码并重新加载技能配置，无需重新输入 API Key。

### 前置条件

- **API Key** — 在 [RunningHub API 管理页面](https://www.runninghub.ai/enterprise-api/sharedApi) 创建（点击"新建"）
- **账户余额** — [前往充值](https://www.runninghub.ai/vip-rights/4)，API 调用需要余额

## 使用方式

安装完成后，直接用自然语言跟助手对话即可：

- *"帮我画一只在公园里玩耍的小狗"*
- *"把这张照片做成视频"*
- *"给我的视频配个背景音乐"*
- *"把这张图放大到 4K"*
- *"把这张图转成 3D 模型"*
- *"用这几张参考图帮我批量生成一组图"*（异步工作流）
- *"用这段视频的动作让照片里的人演一遍"*（H3 动作迁移工作流）
- *"帮我克隆一个音色念这段文案"*、*"让这张照片的人开口播这条文案"*（异步工作流）
- *"帮我跑这个 AI 应用 https://www.runninghub.ai/ai-detail/1877265245566922800"*
- *"最热门的 AI 应用有哪些？"*
- *"推荐一些最新的 AI 应用"*

助手会自动选择最合适的方式：交互性的单次出图/出片走标准 API 菜单；批量、长耗时或需要多素材参考的任务走异步工作流任务池；AI 应用则获取应用节点信息、引导你设置参数并运行；还可以浏览推荐、最热、最新的 AI 应用。

### 视频生成交互

生成视频时，助手会展示 7 个精选模型让你选择：

> 1. 🚀 **全能视频V3.1 Fast** — 又快效果又好，性价比之王
> 2. 🔥 **全能视频X** — Grok 驱动，画面想象力超强，创意天花板
> 3. 🎯 **可灵 v3.0 Pro** — 运动自然，拍人物首选
> 4. 🎬 **全能视频V3.1 Pro** — 电影感拉满，适合风景大片
> 5. ✨ **Vidu Q3 Pro** — 风格化独特，适合创意短片
> 6. 🌊 **MiniMax H3** — 最高2K、最长15秒，画面细腻
> 7. 🌱 **Seedance 2.5** — 最长30秒+自动配音+支持真人，最高4K

选个数字就能开始生成，不选默认用全能视频V3.1 Fast。所有模型均有折扣，大约 2–7 折。

> 上面是标准 API 的同步模型菜单。多参考素材（最多 9 图 + 3 视频 + 3 音频）、动作迁移、视频续写、参考音色配音等高级玩法走 **MiniMax H3 多参考生视频**异步工作流，详见下文《异步工作流任务池》。

### 图片生成交互

生成图片时，助手会展示 5 个精选模型让你选择：

> 1. 🎨 **Nano Banana Pro** — 默认推荐，综合效果最好
> 2. ⚡ **Nano Banana 2** — 最快最便宜
> 3. 🎭 **Midjourney v8** — 欧美大片质感
> 4. 🤖 **GPT Image 2** — GPT image2 同款，语义理解强，改图也很稳
> 5. 📷 **Seedream v5 Pro** — 字节跳动出品，写实照片感超强

选个数字就能开始生成，不选默认用 Nano Banana Pro。所有模型均有折扣，大约 2–7 折。

> 批量出图或多图融合（2～10 张参考图）走异步工作流：Qwen Image 2.1 系列只扣算力币，Nano Banana 2 工作流另收约 ¥0.19/张第三方费用，默认优先 Qwen。

## 项目结构

```
runninghub/
├── SKILL.md                        # 技能定义（OpenClaw / DeepSeek Harness，路由表 + 示例 + 交互规则）
├── scripts/
│   ├── runninghub.py               # 标准模型 API 客户端（420 端点）
│   ├── runninghub_app.py           # AI 应用客户端（自定义 ComfyUI 工作流）
│   ├── build_capabilities.py       # 从 models_registry.json 生成 capabilities.json
│   └── rh_pool/
│       ├── pool.py                 # 异步工作流任务池（提交/轮询/下载/查询）
│       └── notify.py               # 后台 watcher（非 openclaw 宿主）
├── config/
│   ├── task-types.json             # 9 个内置工作流类型定义（参数→工作流节点映射）
│   ├── skill-config.json           # 任务池并发/轮询配置（均为可选项）
│   └── workflows/                  # 已归档的工作流导出（供 workflow validate 校验）
├── references/                     # 详细流程参考（SKILL.md 路由后按需加载）
│   ├── task-pool.md                # 任务池完整流程 + 工作流选型表 + H3 提示词指南
│   ├── image-models.md             # 图片模型菜单与匹配规则
│   ├── video-models.md             # 视频模型菜单与匹配规则
│   ├── ai-application.md           # AI 应用浏览与运行
│   ├── api-key-setup.md            # API Key 配置
│   └── output-delivery.md          # 产物交付与费用报告规则
└── data/
    ├── capabilities.json           # 标准 API 完整端点目录（自动生成）
    └── pool/                       # 任务池数据：SQLite 账本 + output/batch-N/ 产物
```

## 脚本模式

### 标准模型 API（runninghub.py）

| 模式 | 命令 | 用途 |
|------|------|------|
| **检查** | `--check` | 验证 API Key + 查询余额 |
| **列表** | `--list [--type T] [--task T]` | 浏览可用端点 |
| **详情** | `--info ENDPOINT` | 查看端点参数 |
| **执行** | `--endpoint EP --prompt "..." -o /tmp/out` | 使用指定端点执行 |
| **自动** | `--task TASK --prompt "..." -o /tmp/out` | 自动选择最佳端点 |

### AI 应用（runninghub_app.py）

| 模式 | 命令 | 用途 |
|------|------|------|
| **检查** | `--check` | 验证 API Key + 查询余额 |
| **浏览** | `--list [--sort S] [--size N] [--page N]` | 浏览推荐/最热/最新 AI 应用 |
| **节点** | `--info WEBAPP_ID` | 查看 AI 应用的可修改节点 |
| **执行** | `--run WEBAPP_ID --node ... --file ... -o /tmp/out` | 运行 AI 应用 |

### 异步工作流任务池（rh_pool/pool.py）

任务池把工作流任务异步化：批量提交、并发预算内排队、后台轮询、完成自动下载、
SQLite 账本持久化（重启后 `reconcile` 断点续传）。单个任务也走任务池。

**9 个内置工作流类型**（`pool.py workflow list` 查看实时参数）：

| 类型 | 用途 | 费用特点 |
|------|------|----------|
| `image-gen-qwen` | Qwen Image 2.1 文生图（提示词自动扩写） | 仅算力币 |
| `image-edit-qwen` | Qwen Image 2.1 单图编辑 | 仅算力币 |
| `image-edit-qwen-multi` | Qwen Image 2.1 多图编辑（主图 + 最多 5 张参考图） | 仅算力币 |
| `image-edit-banana2` | Nano Banana 2：文生图/改图/最多 10 图融合 | **另收约 ¥0.19/张现金** |
| `i2v-minimax-h3-first-frame` | MiniMax H3 单首帧图生视频（4–15 秒有声） | 算力币 |
| `i2v-minimax-h3-multi-ref` | H3 高级：9 图 + 3 视频 + 3 音频，动作迁移/续写/配音 | 算力币（挂视频更贵） |
| `voice-clone-emo` | IndexTTS2 音色克隆（可选情绪参考） | 仅算力币 |
| `digital-human` | Wan MultiTalk 照片口播数字人 | 算力币 |
| `music-yue2` | YuE2 文生歌曲/纯音乐（bf16，含人声分离，出混音/伴奏/人声干声） | 算力币 |

选型建议：生图/改图默认用 Qwen（零现金），需要 7～10 图融合或 Qwen 效果
不达标时才用 Nano Banana 2；简单"让图动起来"用 H3 首帧，多素材/动作迁移/
续写/配音用 H3 多参考。H3 多参考需按六段式 Ref2VA 格式写提示词，完整模板
和实测技巧见 [runninghub/references/task-pool.md](./runninghub/references/task-pool.md)。

| 模式 | 命令 | 用途 |
|------|------|------|
| **列出类型** | `pool.py workflow list` | 查看内置工作流及参数 |
| **提交单个** | `pool.py enqueue --type image-gen-qwen --param prompt="..."` | 自动启动后台 watcher |
| **批量提交** | `pool.py enqueue --from-file jobs.json` | JSON 任务列表，一次提交 |
| **查看批次** | `pool.py ls` / `ls 10` / `ls -1` | 最新批次/指定批次/倒数第 N 批（人类可读表格） |
| **总览状态** | `pool.py status` | 当前批次、计数、最近 10 条任务（`--all` 全量） |
| **单任务详情** | `pool.py status --pool-id 7` | rh_status、下载产物、费用明细 |
| **批次产物** | `pool.py outputs --latest` / `--batch-id 10` | 产物路径 + 聚合费用 |
| **重启恢复** | `pool.py reconcile` | 重新同步状态并下载已完成产物 |

产物默认落在 `runninghub/data/pool/output/batch-<批次>/`；批量提交、宿主
模式（openclaw 自动唤醒 / 通用宿主后台 watcher）等完整流程见
[runninghub/references/task-pool.md](./runninghub/references/task-pool.md)。

## 更新能力目录

当 RunningHub 上线新的 API 端点时，重新生成目录：

```bash
python3 scripts/build_capabilities.py \
  --registry /path/to/ComfyUI_RH_OpenAPI/models_registry.json \
  --output data/capabilities.json
```

## 姊妹技能：media-understand（音视频理解）

[media-understand](./media-understand/SKILL.md) 是本仓库的通用**媒体理解**技能（与生成无关，独立可用）：把本地音频/视频（及图片）连同任意提问发给多模态大模型 Qwen3.8-Omni，回答画面描述、中文 OCR、语音逐字转写、声音事件、时间线、摘要、质检等任意问题。零第三方依赖，仅需阿里云百炼 API Key。

```powershell
python media-understand/scripts/media_understand.py ask clip.mp4 "描述画面并读出画面上的文字"
python media-understand/scripts/media_understand.py transcribe meeting.m4a
```

## 许可证

[Apache-2.0](./LICENSE)
