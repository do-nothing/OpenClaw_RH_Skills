#!/usr/bin/env python3
"""
media_understand.py — thin, generic wrapper over a multimodal LLM (qwen3.8-omni-flash
on Alibaba Cloud Model Studio / Bailian, OpenAI-compatible endpoint).

It does one thing: send a local audio / video / image file (or a URL) plus your
instruction to the model and print the model's text answer. No business logic,
no task templates.

Subcommands:
  ask          <media> "<question / instruction>"   generic, model capability exposed
  ask          <media> -p prompt.txt                read instruction from file
  transcribe   <media>                              convenience: verbatim speech transcription

<media> may be a local file path OR an http(s):// URL (or an oss:// temporary URL).
Delivery channel is chosen automatically (--channel to override):
  - small local files (<=25 MB): inline base64 data URL
  - large local files: uploaded to Bailian free temporary storage (max 1 GB,
    URL valid 48 h), then referenced by oss:// URL
  - http(s) / oss URLs: passed through to the model untouched

Common options:
  --fps N            video sampling fps sent to the model (default 2.0)
  --system TEXT      optional system message
  --no-thinking       disable the model's chain-of-thought (cheaper, faster, dumber)
  --raw               print the full API JSON response (incl. token usage)
  --out PATH          write result to a file instead of stdout
  --channel CHANNEL   auto (default) | base64 | url

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
import urllib.parse
import urllib.request

ENDPOINT = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3.8-omni-flash"

# Bailian temporary-storage upload API
UPLOAD_POLICY_URL = "https://dashscope.aliyuncs.com/api/v1/uploads"
TEMP_STORAGE_MAX_BYTES = 1024 * 1024 * 1024  # hard server-side limit of the upload API

# Header required by the compatible endpoint whenever a media URL uses the
# internal oss:// scheme (temporary storage). Public https URLs don't need it.
OSS_RESOLVE_HEADER = "X-DashScope-OssResourceResolve"

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv", ".ts", ".m4v", ".wmv"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".oga", ".aac", ".wma", ".m3a", ".opus"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

# Local files up to this size are inlined as base64 data URLs (no extra upload
# round trip). Larger files are auto-uploaded to temporary storage.
#
# Measured gateway constraint (2026-10-04): a single JSON string value may be at
# most 28,000,000 characters (Jackson StreamReadConstraints). Base64 expands
# bytes by 4/3 and the data URL adds a short prefix: a 20 MiB file encodes to
# ~27.96M characters (fits), while a 20.9 MB file reached 28,049,408 (rejected).
# 20 MiB is therefore the safe inline ceiling.
BASE64_MAX_BYTES = 20 * 1024 * 1024

UPLOAD_CHUNK = 1024 * 1024

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


def is_remote(ref):
    return ref.startswith(("http://", "https://", "oss://"))


def name_of_ref(ref):
    """File-ish name of a reference: basename for paths, URL path basename for URLs."""
    if is_remote(ref):
        return os.path.basename(urllib.parse.urlparse(ref).path)
    return os.path.basename(ref)


def media_kind(ref):
    ext = os.path.splitext(name_of_ref(ref))[1].lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in IMAGE_EXT:
        return "image"
    die(f"Unsupported file type: {ext or '(no extension)'}\n"
        f"Supported video: {sorted(VIDEO_EXT)}\nSupported audio: {sorted(AUDIO_EXT)}\n"
        f"Supported image: {sorted(IMAGE_EXT)}")


def guess_mime(ref, kind):
    mime, _ = mimetypes.guess_type(name_of_ref(ref))
    if not mime:
        mime = {"video": "video/mp4", "audio": "application/octet-stream",
                "image": "image/png"}[kind]
    return mime


def part_for_url(url, kind, fps, ref_for_ext=None):
    """Build a content part referencing an http(s)/oss/data URL."""
    if kind == "video":
        return {"type": "video_url", "video_url": {"url": url, "fps": fps}}
    if kind == "audio":
        # OpenAI-compatible format for Qwen-Omni: input_audio.data accepts a
        # data URL or an http(s)/oss URL; input_audio.format is required.
        ext_src = ref_for_ext if ref_for_ext is not None else url
        fmt = os.path.splitext(name_of_ref(ext_src))[1].lower().lstrip(".")
        return {"type": "input_audio", "input_audio": {"data": url, "format": fmt}}
    return {"type": "image_url", "image_url": {"url": url}}


def part_base64(path, kind, fps):
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    return part_for_url(f"data:{guess_mime(path, kind)};base64,{b64}", kind, fps)


class _MultipartReader:
    """File-like object streaming a multipart/form-data body: field preamble
    bytes -> file chunks -> closing boundary, so big files aren't buffered."""

    def __init__(self, pre, fileobj, post):
        def gen():
            yield pre
            while True:
                chunk = fileobj.read(UPLOAD_CHUNK)
                if not chunk:
                    break
                yield chunk
            yield post

        self._it = gen()
        self._buf = b""

    def read(self, size=-1):
        if size is None or size < 0:
            size = UPLOAD_CHUNK
        while len(self._buf) < size:
            try:
                self._buf += next(self._it)
            except StopIteration:
                break
        result, self._buf = self._buf[:size], self._buf[size:]
        return result


def upload_to_temp_storage(path, api_key):
    """Upload a local file to Bailian free temporary storage; return oss:// URL."""
    qs = urllib.parse.urlencode({"action": "getPolicy", "model": MODEL})
    req = urllib.request.Request(
        f"{UPLOAD_POLICY_URL}?{qs}",
        headers={"Authorization": f"Bearer {api_key}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            policy_data = json.loads(resp.read().decode("utf-8"))["data"]
    except urllib.error.HTTPError as e:
        die(f"Failed to get upload policy: HTTP {e.code}\n{e.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as e:
        die(f"Failed to get upload policy (network error): {e.reason}")

    file_name = os.path.basename(path)
    key = f"{policy_data['upload_dir']}/{file_name}"
    boundary = "----media-understand-boundary7f3a9c21"

    def field(name, value):
        return (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                f"{value}\r\n").encode("utf-8")

    pre = b"".join([
        field("OSSAccessKeyId", policy_data["oss_access_key_id"]),
        field("Signature", policy_data["signature"]),
        field("policy", policy_data["policy"]),
        field("x-oss-object-acl", policy_data["x_oss_object_acl"]),
        field("x-oss-forbid-overwrite", policy_data["x_oss_forbid_overwrite"]),
        field("key", key),
        field("success_action_status", "200"),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
         f"filename=\"{file_name}\"\r\nContent-Type: {guess_mime(path, media_kind(path))}\r\n\r\n"
         ).encode("utf-8"),
    ])
    post = f"\r\n--{boundary}--\r\n".encode("utf-8")

    total_len = len(pre) + os.path.getsize(path) + len(post)
    with open(path, "rb") as f:
        body = _MultipartReader(pre, f, post)
        req = urllib.request.Request(
            policy_data["upload_host"], data=body, method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "Content-Length": str(total_len)})
        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            die(f"Upload to temporary storage failed: HTTP {e.code}\n"
                f"{e.read().decode('utf-8', 'replace')}")
        except urllib.error.URLError as e:
            die(f"Upload to temporary storage failed (network error): {e.reason}")

    return f"oss://{key}"


def resolve_content(media, kind, fps, channel):
    """Return (content_part, extra_request_headers) for the given media reference."""
    if is_remote(media):
        if channel == "base64":
            die("--channel base64 cannot be used with a remote URL; use a local file.")
        headers = {OSS_RESOLVE_HEADER: "enable"} if media.startswith("oss://") else {}
        return part_for_url(media, kind, fps), headers

    size = os.path.getsize(media)
    use_url = channel == "url" or (channel == "auto" and size > BASE64_MAX_BYTES)
    if not use_url:
        return part_base64(media, kind, fps), {}

    if size > TEMP_STORAGE_MAX_BYTES:
        die(f"{os.path.basename(media)} is {size/1024/1024:.1f} MB; Bailian temporary "
            f"storage accepts files up to 1 GB, while the model itself accepts up to "
            f"2 GB / 2 h videos. Host the file on Alibaba OSS (or any public URL) and "
            f"pass the https URL directly, e.g.:\n"
            f"  python media_understand.py ask \"https://your-host/v.mp4\" \"...\"")

    print(f"[media-understand] {os.path.basename(media)} is {size/1024/1024:.1f} MB; "
          f"uploading to Bailian temporary storage (URL valid 48 h)...", file=sys.stderr)
    oss_url = upload_to_temp_storage(media, os.environ["DASHSCOPE_API_KEY"])
    print("[media-understand] upload complete; calling model...", file=sys.stderr)
    return part_for_url(oss_url, kind, fps, ref_for_ext=media), \
        {OSS_RESOLVE_HEADER: "enable"}


class PayloadTooLong(Exception):
    """Raised when the gateway rejects a base64 string over its max length."""


def post_completion(messages, no_thinking, extra_headers):
    body = {"model": MODEL, "messages": messages}
    if no_thinking:
        # Qwen3 series on the compatible endpoint: top-level extra parameter.
        body["enable_thinking"] = False

    headers = {"Authorization": f"Bearer {os.environ['DASHSCOPE_API_KEY']}",
               "Content-Type": "application/json"}
    headers.update(extra_headers)

    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        # The inline base64 channel has a measured per-string cap of 28M chars.
        # Surface this specific error so call_model can fall back to the URL
        # channel in auto mode; every other HTTP error is fatal as before.
        if e.code == 400 and "exceeds the maximum allowed" in raw \
                and "StreamReadConstraints" in raw:
            raise PayloadTooLong(raw)
        try:
            raw = json.dumps(json.loads(raw), ensure_ascii=False, indent=2)
        except Exception:
            pass
        die(f"API request failed: HTTP {e.code}\n{raw}")
    except urllib.error.URLError as e:
        die(f"Network error: {e.reason}")


def call_model(media, prompt, fps, system, no_thinking, channel):
    kind = media_kind(media)
    media_part, extra_headers = resolve_content(media, kind, fps, channel)

    def messages_with(part):
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user",
                         "content": [part, {"type": "text", "text": prompt}]})
        return messages

    try:
        return post_completion(messages_with(media_part), no_thinking, extra_headers)
    except PayloadTooLong:
        # Only auto mode may silently switch channels; a forced base64 channel
        # reports the raw error, and remote URLs can never reach this branch.
        if channel != "auto":
            raise
        print("[media-understand] note: inline payload rejected as too large by "
              "the gateway; uploading to temporary storage instead...",
              file=sys.stderr)
        media_part, extra_headers = resolve_content(media, kind, fps, "url")
        return post_completion(messages_with(media_part), no_thinking, extra_headers)


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
    ap = argparse.ArgumentParser(
        description="Understand local audio/video/image files (or URLs) via multimodal LLM.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("media",
                       help="local audio/video/image file path, or an http(s):// / oss:// URL")
        p.add_argument("--fps", type=float, default=2.0,
                       help="video sampling fps sent to model (default 2.0)")
        p.add_argument("--system", help="optional system message")
        p.add_argument("--no-thinking", action="store_true",
                       help="disable chain-of-thought (cheaper/faster)")
        p.add_argument("--raw", action="store_true", help="print full API JSON")
        p.add_argument("--out", help="write result to file")
        p.add_argument("--channel", choices=("auto", "base64", "url"), default="auto",
                       help="delivery channel: auto (default), force base64, or force "
                            "URL via temporary-storage upload (local files only)")

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
    if not is_remote(args.media) and not os.path.isfile(args.media):
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

    payload = call_model(args.media, prompt, args.fps, args.system,
                         args.no_thinking, args.channel)
    emit(payload, args.raw, args.out)


if __name__ == "__main__":
    main()
