# scripts/

全部脚本均已实现并通过端到端验证：

1. `new_project.py`：创建目录、写入草稿 `beats.json`，并可做基础/严格校验；不调用网络。支持 v2 叙事层（`arc`/`ending`/`--detail`/`shot_size`），同时接受旧 v1 项目。
2. `generate_keyframe_prompts.py`：离线生成英文关键帧提示词（10 个主题 + 景别引导）。
3. `generate_keyframes.py`：调用 RunningHub Nano Banana 2 生成关键帧，dry-run、复用已有素材、逐任务等待、失败即停。
4. `generate_clip_prompts.py`：离线生成英文图生视频提示词（6 个平面安全运镜）。
5. `generate_clips.py`：调用 RunningHub 图生视频（V3.1，8s/720p）；只等待，不自动重发。
6. `generate_audio.py`：**按 beat** 生成分段旁白（只有 anchor 镜产一条 TTS）+ 一条可选配乐；支持豆包语音克隆；7.35s 时长前置校验。
7. `assemble.py`：ffprobe/ffmpeg/Pillow 合成 `final.mp4`；一 beat 可跨 anchor+detail 两个画面、句中切镜，字幕跨画面持续。
8. `qa_video_understand.py`：可选的视频理解 QA（按镜收费，先 dry-run）。

## new_project.py

创建草稿项目（先读 `references/narrative.md` 选 `arc`）：

```powershell
python scripts/new_project.py --project shell-money --root out --topic "为什么古代人会把贝壳当钱？" `
  --theme newsprint-editorial --arc hook_payoff --ending hard_cut --duration 18 --music `
  [--detail b2,b3]   # 可选：给这些 beat 加无标题 detail 特写镜（会多生成画面、多花钱）
```

草稿按 `--duration` 自动铺 N 个 beat（≤22→4、≤32→6、≤42→8、≤52→10、更长→12），每 beat 一个 anchor 镜；`--detail b3,b6` 会在这些 beat 后插入 CLOSE 特写。字段与校验规则见 `references/mvp-schema.md`。

基础结构校验：

```powershell
python scripts/new_project.py out/shell-money --validate-only
```

严格内容校验（占位符全部替换后才能通过）：

```powershell
python scripts/new_project.py out/shell-money --validate-only --strict
```

语音克隆项目在创建时提供样本路径：

```powershell
python scripts/new_project.py --project demo --root out --topic "主题" --voice clone --sample-path "C:\path\sample.m4a"
```

该脚本只读写本地文件，不访问网络、不提交 RunningHub 任务。

## generate_keyframe_prompts.py

分镜严格校验通过后，离线生成 4 条英文关键帧提示词，并把中文标题作为必须精确保留的文本写入提示词。该脚本不访问网络、不产生费用。

```powershell
python scripts/generate_keyframe_prompts.py out/<project> --set-default-endpoint
```

默认端点固定为 RunningHub 图片模型菜单中的 Nano Banana 2：`rhart-image-n-g31-flash-lite/text-to-image`。该低价渠道只传 `aspectRatio=16:9`，不传分辨率。

## generate_keyframes.py

先 dry-run 检查 4 条即将提交的任务：

```powershell
python scripts/generate_keyframes.py out/<project>
```

用户明确确认数量、模型和费用后，才允许实际提交：

```powershell
python scripts/generate_keyframes.py out/<project> --submit
```

脚本逐个镜头提交并等待同一个 RunningHub 任务，不因为排队或处理慢而重发。失败时记录任务 ID 与错误并立即停止。已存在且非空的本地关键帧默认复用，`--force` 才重生成。
