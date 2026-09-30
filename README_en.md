# RHClaw — RunningHub Skill for OpenClaw / DeepSeek Harness

[中文](./README.md)

> ## Now supports [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
>
> Same standard `SKILL.md` as [OpenClaw](https://github.com/openclaw/openclaw). Install and update the same way.

An OpenClaw and DeepSeek Harness skill that brings multimedia generation capabilities — including image, video, audio, 3D, and text — to conversational AI, powered by 420 [RunningHub](https://www.runninghub.cn) API endpoints. Built with zero external dependencies (pure Python 3 + curl), it lets users create rich media content through natural language, with support for standard model APIs, 9 built-in asynchronous workflows (task pool), and custom ComfyUI workflows (AI Applications).

## Capabilities

| Category | Endpoints | Tasks |
|----------|-----------|-------|
| **Image** | 102 | text-to-image, image-to-image, image upscale, Midjourney-style |
| **Video** | 230 | text-to-video, image-to-video, start-end frames, video extend/edit, motion control, multimodal video |
| **Audio** | 20 | text-to-speech, music generation, voice clone |
| **3D** | 16 | text-to-3D, image-to-3D, multi-image-to-3D |
| **Text** | 52 | image-to-text, video-to-text, text-to-text |
| **Async workflows (task pool)** | 9 built-in types | Qwen/Nano Banana image gen & edit, MiniMax H3 first-frame/multi-reference video, voice clone, digital human, music; batch submit, background runs, crash recovery |
| **AI Apps** | Unlimited | Run any RunningHub AI Application (custom ComfyUI workflow) |

## Quick Start

### Install

In your OpenClaw or DeepSeek Harness chat, say:

> Install the RunningHub skill from https://github.com/HM-RunningHub/OpenClaw_RH_Skills

The assistant will clone the repo, copy files to the workspace, and guide you through API key setup.

### Update

When a new version is available, say in your OpenClaw or DeepSeek Harness chat:

> Update from https://github.com/HM-RunningHub/OpenClaw_RH_Skills and re-read @runninghub/SKILL.md

The assistant will pull the latest code and reload the skill config. No need to re-enter your API key.

### Prerequisites

- **API Key** — Get one from [RunningHub API Management](https://www.runninghub.cn/enterprise-api/sharedApi) (click "新建")
- **Wallet balance** — [Recharge here](https://www.runninghub.cn/vip-rights/4) — API calls require funds

## Usage

Once installed, just talk to your OpenClaw assistant in natural language:

- *"Generate a picture of a dog playing in the park"*
- *"Turn this photo into a video"*
- *"Create background music for my video"*
- *"Upscale this image to 4K"*
- *"Convert this image to a 3D model"*
- *"Batch-generate a set of images from these references"* (async workflow)
- *"Make the person in this photo perform the action in this video"* (H3 motion-transfer workflow)
- *"Clone a voice to read this script"*, *"Make the person in this photo present this script"* (async workflows)
- *"Run this AI app: https://www.runninghub.cn/ai-detail/1877265245566922800"*
- *"What are the hottest AI apps?"*
- *"Show me the newest AI apps"*

The assistant automatically picks the right path: interactive one-shot image/video generation goes through the standard API menus; batch, long-running, or multi-reference tasks go through the asynchronous workflow task pool; AI Apps fetch node info, guide you through parameter setup, and run the workflow. You can also browse recommended, hottest, and newest AI apps.

### Video Model Selection

When generating video, the assistant presents 7 curated models to choose from:

> 1. 🚀 **RH-Video V3.1 Fast (全能视频V3.1 Fast)** — Fast with great quality, best value
> 2. 🔥 **RH-Video X (全能视频X)** — Grok-powered, incredible imagination
> 3. 🎯 **Kling v3.0 Pro (可灵)** — Natural motion, best for people
> 4. 🎬 **RH-Video V3.1 Pro (全能视频V3.1 Pro)** — Cinematic quality, great for landscapes
> 5. ✨ **Vidu Q3 Pro** — Unique stylized look
> 6. 🌊 **MiniMax H3** — Up to 2K and 15s, fine details
> 7. 🌱 **Seedance 2.5** — Up to 30s + auto audio + real people, up to 4K

Pick a number to start, or the default (RH-Video V3.1 Fast) is used automatically. All models are discounted, typically 20–70% off.

> The menu above is the synchronous standard API. Advanced features — up to 9 reference images + 3 reference videos + 3 reference audios, motion transfer, video continuation, voice-referenced narration — use the asynchronous **MiniMax H3 multi-reference** workflow, see "Asynchronous Workflow Task Pool" below.

### Image Model Selection

When generating images, the assistant presents 5 curated models to choose from:

> 1. 🎨 **Nano Banana Pro** — Best overall quality, recommended default
> 2. ⚡ **Nano Banana 2** — Fastest and most affordable
> 3. 🎭 **Midjourney v8** — Cinematic look
> 4. 🤖 **GPT Image 2** — Strong prompt understanding and reliable image editing
> 5. 📷 **Seedream v5 Pro** — ByteDance, strong photorealistic feel

Pick a number to start, or the default (Nano Banana Pro) is used automatically. All models are discounted, typically 20–70% off.

> Batch generation and multi-image fusion (2–10 references) use async workflows: the Qwen Image 2.1 types charge compute coins only, while the Nano Banana 2 workflow adds ~¥0.19/image third-party cash — Qwen is the default recommendation.

## Architecture

```
runninghub/
├── SKILL.md                        # Skill definition (routing table + examples + interaction rules)
├── scripts/
│   ├── runninghub.py               # Standard model API client (420 endpoints)
│   ├── runninghub_app.py           # AI Application client (custom ComfyUI workflows)
│   ├── build_capabilities.py       # Generates capabilities.json from models_registry.json
│   └── rh_pool/
│       ├── pool.py                 # Async workflow task pool (submit/poll/download/query)
│       └── notify.py               # Background watcher (non-openclaw hosts)
├── config/
│   ├── task-types.json             # 9 built-in workflow type definitions (param→node mapping)
│   ├── skill-config.json           # Pool concurrency/poll config (all optional)
│   └── workflows/                  # Archived workflow exports (for `workflow validate`)
├── references/                     # Detailed playbooks (loaded on demand via SKILL.md routing)
│   ├── task-pool.md                # Task pool flow + workflow selection table + H3 prompt guide
│   ├── image-models.md             # Image model menu and matching rules
│   ├── video-models.md             # Video model menu and matching rules
│   ├── ai-application.md           # AI app browsing and execution
│   ├── api-key-setup.md            # API key setup
│   └── output-delivery.md          # Output delivery and cost reporting rules
└── data/
    ├── capabilities.json           # Full standard endpoint catalog (auto-generated)
    └── pool/                       # Pool data: SQLite ledger + output/batch-N/ artifacts
```

## Script Modes

### Standard Model API (runninghub.py)

| Mode | Command | Purpose |
|------|---------|---------|
| **Check** | `--check` | Verify API key + check wallet balance |
| **List** | `--list [--type T] [--task T]` | Browse available endpoints |
| **Info** | `--info ENDPOINT` | View endpoint parameters |
| **Execute** | `--endpoint EP --prompt "..." -o /tmp/out` | Run with specific endpoint |
| **Auto** | `--task TASK --prompt "..." -o /tmp/out` | Auto-select best endpoint |

### AI Application (runninghub_app.py)

| Mode | Command | Purpose |
|------|---------|---------|
| **Check** | `--check` | Verify API key + check wallet balance |
| **Browse** | `--list [--sort S] [--size N] [--page N]` | Browse recommended/hottest/newest AI apps |
| **Nodes** | `--info WEBAPP_ID` | Show modifiable nodes for an AI app |
| **Execute** | `--run WEBAPP_ID --node ... --file ... -o /tmp/out` | Run an AI application |

### Asynchronous Workflow Task Pool (rh_pool/pool.py)

The pool makes workflow tasks asynchronous: batch submit, queue within a
concurrency budget, background polling, automatic downloads, and a durable
SQLite ledger (`reconcile` after restarts). Even a single task goes through
the pool.

**9 built-in workflow types** (`pool.py workflow list` for live params):

| Type | Purpose | Cost |
|------|---------|------|
| `image-gen-qwen` | Qwen Image 2.1 text-to-image (auto prompt expansion) | Coins only |
| `image-edit-qwen` | Qwen Image 2.1 single-image edit | Coins only |
| `image-edit-qwen-multi` | Qwen Image 2.1 edit with 1 main + up to 5 reference images | Coins only |
| `image-edit-banana2` | Nano Banana 2: text-to-image / edit / fuse up to 10 images | **Plus ~¥0.19/image cash** |
| `i2v-minimax-h3-first-frame` | MiniMax H3 single first-frame → video (4–15s, with sound) | Coins |
| `i2v-minimax-h3-multi-ref` | H3 advanced: 9 images + 3 videos + 3 audios; motion transfer / continuation / voice | Coins (higher with video refs) |
| `voice-clone-emo` | IndexTTS2 voice cloning (optional emotion reference) | Coins only |
| `digital-human` | Wan MultiTalk talking-head video from a photo | Coins |
| `music-yue2` | YuE2 song / instrumental generation (bf16, vocal separation; mix/accompaniment/vocals) | Coins |

Selection: prefer Qwen for image generation/editing (no cash); use Nano Banana
2 only for 7–10 image fusion or when Qwen quality is insufficient. Simple
"animate this image" → H3 first-frame; multi-reference / motion transfer /
continuation / voice → H3 multi-ref. H3 multi-ref requires the six-section
Ref2VA prompt format — full template and verified tips in
[runninghub/references/task-pool.md](./runninghub/references/task-pool.md).

| Mode | Command | Purpose |
|------|---------|---------|
| **List types** | `pool.py workflow list` | Show built-in workflows and params |
| **Submit one** | `pool.py enqueue --type image-gen-qwen --param prompt="..."` | Auto-starts background watcher |
| **Submit batch** | `pool.py enqueue --from-file jobs.json` | JSON list of jobs in one call |
| **View batch** | `pool.py ls` / `ls 10` / `ls -1` | Latest / absolute id / N batches back (human table) |
| **Overview** | `pool.py status` | Current batch, counts, 10 newest tasks (`--all` for everything) |
| **One task** | `pool.py status --pool-id 7` | rh_status, downloads, fees |
| **Batch outputs** | `pool.py outputs --latest` / `--batch-id 10` | Output paths + aggregated fees |
| **Restart recovery** | `pool.py reconcile` | Re-sync states and download finished outputs |

Outputs land under `runninghub/data/pool/output/batch-<id>/` by default. The
full flow (batch jobs, host modes — openclaw wake-up vs generic-host
background watcher) is documented in
[runninghub/references/task-pool.md](./runninghub/references/task-pool.md).

## Updating Capabilities

When RunningHub adds new API endpoints, regenerate the catalog:

```bash
python3 scripts/build_capabilities.py \
  --registry /path/to/ComfyUI_RH_OpenAPI/models_registry.json \
  --output data/capabilities.json
```

## Sister skill: media-understand (audio/video understanding)

[media-understand](./media-understand/SKILL.md) is the repo's generic **media understanding** skill (generation-independent, usable on its own): send a local audio/video file (and images) with any question to the Qwen3.8-Omni multimodal LLM — visual description, Chinese OCR, verbatim speech transcription, sound events, timelines, summarization, QA, defect checks, etc. No third-party dependencies; only an Alibaba Cloud Model Studio (Bailian) API key is required.

```powershell
python media-understand/scripts/media_understand.py ask clip.mp4 "Describe the visuals and read out the on-screen text"
python media-understand/scripts/media_understand.py transcribe meeting.m4a
```

## License

[Apache-2.0](./LICENSE)
