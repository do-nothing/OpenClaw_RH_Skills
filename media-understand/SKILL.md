---
name: media-understand
description: >
  Understand local audio and video files (and images) by asking a multimodal LLM
  (Qwen3.8-Omni on Alibaba Cloud Model Studio) arbitrary questions: describe what
  happens on screen, read on-screen text (incl. Chinese OCR), transcribe speech /
  dialogue / narration verbatim, identify music mood and sound events, extract an
  event timeline, summarize, answer questions about a recording, inspect footage
  for defects, reverse-engineer production notes from a finished clip, etc.
  Use whenever an agent cannot itself read an mp4/mp3/wav and needs the actual
  content of a media file. Audio and video understanding is the primary capability;
  image understanding is a fallback for agents without built-in vision.
---

# media-understand

A thin, generic wrapper that sends a **local audio / video / image file** plus your
instruction to a multimodal LLM and returns its text answer. It does not generate or
edit media, and it contains no task-specific templates — *what* to ask is entirely up
to the calling agent.

- Script: `scripts/media_understand.py` (Python 3.9+, standard library only)
- Model: `qwen3.8-omni-flash` (fixed; callers never choose models or read API docs)
- Backend: Alibaba Cloud Model Studio (Bailian / 百炼) OpenAI-compatible endpoint
- Inputs: local files only, sent as base64 data URLs (no upload hosting needed)

## When to use

Trigger on any need to **know the content** of a media file:

- "这个视频里发生了什么 / 描述画面 / 有哪些镜头 / 时间线"
- 转写视频或音频里的人声、对话、旁白（中文/英文）
- 读出画面上的文字（含中文 OCR）、检查有无乱码假字
- 听辨音乐情绪、人声/环境声、声音事件
- 摘要、问答、质检、素材盘点、从成片反推脚本/分镜
- Agent 自身无法读取 mp4/mp3（没有内建音视频理解）时

**Images are a fallback, not the primary path.** Most agents already have built-in
vision where the image can be placed directly into the conversation context — that is
strictly better (no upload, no tokenization, higher fidelity). Only use this skill for
images when the calling agent genuinely lacks image-reading ability.

## Quick start

```powershell
# Ask anything about a video / audio / image (generic, full model capability)
python scripts/media_understand.py ask clip.mp4 "逐个镜头描述画面，并读出画面上的中文标题"
python scripts/media_understand.py ask meeting.m4a -p questions.txt --out result.json
cat list.txt | python scripts/media_understand.py ask footage.mov

# Verbatim speech transcription (convenience wrapper)
python scripts/media_understand.py transcribe clip.mp4
python scripts/media_understand.py transcribe voice.m4a --language zh-CN
```

Options: `--fps 2.0` (video sampling), `--system` (system message),
`--no-thinking` (cheaper/faster answers), `--raw` (full API JSON + token usage),
`--out PATH`.

The model answers on stdout; token usage is printed to stderr.

## API key

Requires `DASHSCOPE_API_KEY`. If it is missing, the script prints setup instructions
and exits with code 2. Short version:

1. Log in at https://bailian.console.aliyun.com/ → API-KEY 管理 → create key (`sk-...`)
2. Persist it (PowerShell, current user):

```powershell
[Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY","sk-...","User")
```

First call to a model normally activates it automatically; otherwise enable
`qwen3.8-omni` on the model card. Pricing: ~¥0.8/M input, ¥2.7/M output tokens —
a 20 s video question costs roughly ¥0.01–0.05.

## How trustworthy are the answers

Based on ground-truthed evaluation against finished videos with known production data
(14 Chinese headlines OCR, 14 narration sentences, shot counts, timings):

| Trust directly | Verify before relying |
|---|---|
| Verbatim speech transcription | Exact direction/moment of fine-grained motion → extract frames (ffmpeg) |
| OCR of clear on-screen text (incl. Chinese) | Music mood, humming, sound effects / SFX → listen yourself |
| Shot / segment counts | Exact timing of a described event |
| Total duration estimate (~±4% in tests) | The *shapes* of suspected garbled/fake text — its existence is detectable reliably, the invented glyphs are not |

Precise media facts must never be asked from the model — measure them with ffprobe
(duration, resolution, fps, codecs, sample rate). See
[references/ffprobe-cookbook.md](references/ffprobe-cookbook.md).

For pass/fail style checks against a specification, feed the spec into the question:
with no brief the model only applies generic standards and will miss brief-specific
violations (e.g. "must be flat 2D" breaches).

## References

- [references/model-notes.md](references/model-notes.md) — wire formats, supported
  file types, token accounting, observed strengths/limits, large-file handling
- [references/ffprobe-cookbook.md](references/ffprobe-cookbook.md) — ffprobe/ffmpeg
  recipes that pair naturally with media understanding (measure, sample, extract)
