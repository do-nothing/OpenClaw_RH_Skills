# scripts/

全部脚本均已实现并通过端到端验证：

1. `new_project.py`：创建目录、写入草稿 `beats.json`，并可做基础/严格校验；不调用网络。支持 v2 叙事层（`arc`/`ending`/`--detail`/`shot_size`），同时接受旧 v1 项目。
2. `generate_keyframe_prompts.py`：离线生成英文关键帧提示词（10 个主题 + 景别引导）。
3. `generate_keyframes.py`：整阶段一个批次入队 RH 任务池（`image-gen-qwen`，算力币/零现金），manual tick 等待同批任务，dry-run、复用已有素材、失败即停。
4. `generate_clip_prompts.py`：离线生成英文图生视频提示词（6 个平面安全运镜）。
5. `generate_clips.py`：整阶段一个批次入队 RH 任务池（`i2v-minimax-h3-first-frame`，MiniMax H3，8s/16:9）；只等待，不自动重发。
6. `generate_audio.py`：**按 beat** 生成分段旁白（`voice-clone-emo`，只有 anchor 镜产一条 TTS）+ 一条可选配乐（`music-yue2`，取分离后伴奏产物），旁白与配乐同一批次；支持传样本声音克隆；7.35s 时长前置校验。
7. `assemble.py`：ffprobe/ffmpeg/Pillow 合成 `final.mp4`；一 beat 可跨 anchor+detail 两个画面、句中切镜，字幕跨画面持续。
8. `qa_video_understand.py`：可选的视频理解 QA，调用姊妹技能 media-understand（Qwen3.8-Omni，百炼 token 计费，先 dry-run）。
9. `rh_pool_client.py`：任务池适配层（供 3/5/6 调用）：`enqueue_batch --manual` 入队、`tick` 非阻塞推进、`wait_for` 等待同批 poolId 全部终态，超时绝不重发。

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

分镜严格校验通过后，离线生成英文关键帧提示词（每镜一条），并把中文标题作为必须精确保留的文本写入提示词。该脚本不访问网络、不产生费用。

```powershell
python scripts/generate_keyframe_prompts.py out/<project> --set-default-endpoint
```

默认池任务类型为 `image-gen-qwen`（通义万相 Qwen Image 2.1，RH 算力币、零现金）。该类型只传 `aspectRatio="16:9 (Widescreen)"`，不传分辨率；高质量备选 `image-edit-banana2` 会产生第三方现金。

## generate_keyframes.py

先 dry-run 检查本批次即将入队的任务：

```powershell
python scripts/generate_keyframes.py out/<project>
```

用户明确确认数量、类型和费用后，才允许实际提交：

```powershell
python scripts/generate_keyframes.py out/<project> --submit
```

脚本把全片关键帧作为一个批次入队（`enqueue --manual`，不启动后台 watcher），自己 tick 推进并只等待同一次批次的 poolId，不因为排队或处理慢而重新入队。失败时记录 poolId 与错误并立即停止。已存在且非空的本地关键帧默认复用，`--force` 才重生成。产物名 `keyframes/kf_<sid>.<真实扩展名>`。
