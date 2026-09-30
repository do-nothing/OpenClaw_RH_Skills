#!/usr/bin/env python3
"""
media_understand.py — thin, generic wrapper over a multimodal LLM (qwen3.8-omni-flash
on Alibaba Cloud Model Studio / Bailian, OpenAI-compatible endpoint).

It does one thing: send a local audio / video / image file plus your instruction to
the model and print the model's text answer. No business logic, no task templates.

Subcommands:
  ask          <media> "<question / instruction>"   generic, model capability exposed
  ask          <media> -p prompt.txt                read instruction from file
  transcribe   <media>                              convenience: verbatim speech transcription

Common options:
  --fps N          video sampling fps sent to the model (default 2.0)
  --system TEXT    optional system message
  --no-thinking    disable the model's chain-of-thought (cheaper, faster, dumber)
  --raw            print the full API JSON response (incl. token usage)
  --out PATH       write result to a file instead of stdout

Auth: set DASHSCOPE_API_KEY (see SKILL.md "API key" section).
Python 3.9+, standard library only.
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request

ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3.8-omni-flash"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".ts", ".m4v", ".wmv"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".oga", ".aac", ".wma", ".m3a", ".opus"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

# Rough guard only — the API enforces the real limit. Above this we warn and
# point at ffmpeg compression instead of blindly uploading.
SOFT_MAX_BYTES = 25 * 1024 * 1024

KEY_HELP = """\
[media-understand] DASHSCOPE_API_KEY is not set.

Get a free API key from Alibaba Cloud Model Studio (Bailian / 百炼):
  1. Open https://bailian.console.aliyun.com/ and log in with an Alibaba Cloud account
  2. Top-right avatar / API-KEY management (API-KEY 管理) -> Create API-Key
  3. Make sure the qwen3.8-omni model service is enabled (first call auto-activates
     on most accounts; otherwise open the qwen3.8-omni-flash model card and click 开通)

Set the environment variable (new shells pick it up automatically):

  Windows (PowerShell, persistent, current user):
    [Environment]::SetEnvironmentVariable("DASHSCOPE_API_KEY","sk-...","User")
  Windows (current session only):
    $env:DASHSCOPE_API_KEY="sk-..."
  macOS / Linux (persistent, add to ~/.zshrc or ~/.bashrc):
    export DASHSCOPE_API_KEY="sk-..."
"""


def die(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


def media_kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    die(f"Unsupported file type: {ext or '(no extension)'}\n"
        f"Supported video: {sorted(VIDEO_EXT)}\nSupported audio: {sorted(AUDIO_EXT)}\n"
        f"Supported image: {sorted(IMAGE_EXT)}")


def data_url(path, kind):
    mime, _ = mimetypes.guess_type(path)
    if not mime:
        mime = {"video": "video/mp4", "audio": "application/octet-stream",
                "image": "image/png"}[kind]
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return mime, b64


def build_content_part(path, kind, fps):
    mime, b64 = data_url(path, kind)
    if kind == "video":
        return {"type": "video_url",
                "video_url": {"url": f"data:{mime};base64,{b64}", "fps": fps}}
    if kind == "audio":
        # OpenAI-compatible format for Qwen-Omni: input_audio.data accepts a
        # data URL; input_audio.format is required (e.g. mp3 / wav / m4a).
        fmt = os.path.splitext(path)[1].lower().lstrip(".")
        return {"type": "input_audio",
                "input_audio": {"data": f"data:{mime};base64,{b64}", "format": fmt}}
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}


def call_model(path, prompt, fps, system, no_thinking):
    kind = media_kind(path)
    size = os.path.getsize(path)
    if size > SOFT_MAX_BYTES:
        print(f"[media-understand] note: {os.path.basename(path)} is {size/1024/1024:.1f} MB; "
              f"large base64 uploads may be rejected. See references/ffprobe-cookbook.md "
              f"for downscaling / audio extraction.", file=sys.stderr)

    content = [build_content_part(path, kind, fps), {"type": "text", "text": prompt}]
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": content})

    body = {"model": MODEL, "messages": messages}
    if no_thinking:
        # Qwen3 series on the compatible endpoint: top-level extra parameter.
        body["enable_thinking"] = False

    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {os.environ['DASHSCOPE_API_KEY']}",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.dumps(json.loads(detail), ensure_ascii=False, indent=2)
        except Exception:
            pass
        die(f"API request failed: HTTP {e.code}\n{detail}")
    except urllib.error.URLError as e:
        die(f"Network error: {e.reason}")


def read_instruction(args):
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            return f.read().strip()
    if args.question:
        return args.question
    if not sys.stdin.isatty():
        data = sys.stdin.read().strip()
        if data:
            return data
    die("No instruction given. Pass it as the last argument, via -p/--prompt-file, or stdin.")


def emit(payload, raw, out):
    if raw:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = payload["choices"][0]["message"]["content"]
        u = payload.get("usage")
        if u:
            print(f"[tokens in={u.get('prompt_tokens')} out={u.get('completion_tokens')}]",
                  file=sys.stderr)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"written: {out}", file=sys.stderr)
    else:
        print(text)


def main():
    ap = argparse.ArgumentParser(description="Understand local audio/video/image via multimodal LLM.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("media", help="path to a local audio / video / image file")
        p.add_argument("--fps", type=float, default=2.0,
                       help="video sampling fps sent to model (default 2.0)")
        p.add_argument("--system", help="optional system message")
        p.add_argument("--no-thinking", action="store_true",
                       help="disable chain-of-thought (cheaper/faster)")
        p.add_argument("--raw", action="store_true", help="print full API JSON")
        p.add_argument("--out", help="write result to file")

    p_ask = sub.add_parser("ask", help="ask anything / give any instruction about the media")
    add_common(p_ask)
    p_ask.add_argument("question", nargs="?", help="question or instruction (or use -p / stdin)")
    p_ask.add_argument("-p", "--prompt-file", help="read instruction from a UTF-8 text file")

    p_tr = sub.add_parser("transcribe", help="verbatim transcription of speech in the media")
    add_common(p_tr)
    p_tr.add_argument("--language", default="", help="optional language hint, e.g. zh-CN / en")

    args = ap.parse_args()

    if not os.environ.get("DASHSCOPE_API_KEY"):
        die(KEY_HELP, code=2)
    if not os.path.isfile(args.media):
        die(f"File not found: {args.media}")

    if args.cmd == "ask":
        prompt = read_instruction(args)
    else:
        kind0 = media_kind(args.media)
        noun = {"audio": "音频", "video": "视频", "image": "图片"}[kind0]
        lang = f" 语言：{args.language}。" if args.language else ""
        prompt = f"请逐字转写这段{noun}中的全部人类语音，只输出转写文本，不要添加任何解释、总结或标点之外的内容。{lang}"
        if kind0 == "image":
            die("transcribe only works with audio or video (no speech track in an image)")

    payload = call_model(args.media, prompt, args.fps, args.system, args.no_thinking)
    emit(payload, args.raw, args.out)


if __name__ == "__main__":
    main()
