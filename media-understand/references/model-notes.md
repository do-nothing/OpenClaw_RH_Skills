# Model notes — qwen3.8-omni-flash via Model Studio

Backend, wire details and empirically observed behavior for `media_understand.py`.
Everything here was tested against the live endpoint (2026-09-30).

## Endpoint & auth

- `POST https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`
- Header `Authorization: Bearer $DASHSCOPE_API_KEY` (key prefix `sk-...`)
- OpenAI-compatible Chat schema. No SDK or third-party dependency needed.
- Workspace-specific domains also exist
  (`https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`);
  the shared dashscope domain works with plain API keys.

## Delivery channels (chosen automatically; `--channel` overrides)

The media reference given to the script can be a local path, an `http(s)://` public
URL, or an `oss://` temporary-storage URL. Auto selection:

1. URL input (`http(s)://`, `oss://`) → passed to the model untouched.
2. Local file ≤ 20 MiB → read and inlined as a base64 data URL.
3. Local file > 20 MiB → uploaded to Bailian free temporary storage
   (`GET /api/v1/uploads?action=getPolicy&model=...` → multipart POST to OSS →
   returns `oss://<key>`), then that URL is sent to the model. Upload is streamed
   (file-like multipart body, 1 MB chunks, explicit Content-Length), so memory use
   stays flat for large files.
   - Inline-channel ceiling, measured 2026-10-04: the gateway rejects any single
     JSON string value longer than **28,000,000 characters**
     (`StreamReadConstraints.getMaxStringLength()`), i.e. roughly 20 MB of source
     bytes after 4/3 base64 expansion plus the data-URL prefix. A 20.9 MB /
     28,049,408-char payload was rejected; 20 MiB encodes to ~27.96M chars (fits).
   - Safety net: if an inline payload is nevertheless rejected with that error,
     auto mode transparently retries once via the upload channel. A forced
     `--channel base64` reports the raw 400 instead of falling back.
   - The model call carrying an `oss://` URL must include the header
     `X-DashScope-OssResourceResolve: enable`, added automatically for `oss://`
     references only. Public https URLs need no special header.
   - Upload API hard limit: **1 GB per file**; URL valid **48 h**; file is bound
     to the model name and to the account (other models/accounts can't use it).
   - Model-side video ceiling is **2 h / 2 GB**; for 1–2 GB files host on OSS and
     pass the https URL directly.

## Input formats (per-modality wire shape)

| Media | content-part type | Payload |
|---|---|---|
| Video | `video_url` | `{"url": "<data URL or http(s)/oss URL>", "fps": 2.0}` |
| Audio | `input_audio` | `{"data": "<data URL or http(s)/oss URL>", "format": "mp3"}` |
| Image | `image_url` | `{"url": "<data URL or http(s)/oss URL>"}` |

Gotchas confirmed by trial:

- Audio is **not** `audio_url` (400). It is `input_audio`, and its field is `data`
  (not `url`) plus a required `format` (`mp3`, `wav`, `m4a`, ...). `data` accepts a
  full data URL; raw base64 without the `data:audio/...;base64,` prefix is rejected
  with "URL does not appear to be valid".
- `video_url.fps` controls sampled frames per second. Default 2.0 is a good
  cost/coverage balance for short clips; lower it for long videos, raise it when fine
  motion matters (and verify fine motion by frame extraction anyway — see SKILL.md).
- The model is **omni**: video input is understood both visually and acoustically —
  a video with a soundtrack needs no separate audio extraction for transcription.
  Usage shows separate `video_tokens` and `audio_tokens`.

Tested containers/codecs: mp4 (h264+aac), mp3, m4a (aac), png, jpg. A large set of
extensions is accepted by the script (`mkv/mov/webm/flac/ogg/...`); exotic codecs
inside a container may fail server-side — remux/transcode with ffmpeg first.

## Output

- `qwen3.8-omni-flash` is **text output only** (no audio generation; that needs other
  omni variants with `modalities: ["text","audio"]`).
- Thinking is on by default: usage contains
  `completion_tokens_details.reasoning_tokens` (billed as output tokens).
  `--no-thinking` sends top-level `"enable_thinking": false` — use it for
  transcription/simple OCR where the reasoning budget is wasted.
- JSON answers are not enforced — when you need structured output, ask for raw JSON
  in the prompt and parse defensively.

## Observed usage / cost (reference, not a contract)

| Task | Media | prompt tok | completion tok | wall time |
|---|---|---|---|---|
| Describe + transcribe one short video | 8 MB / 20 s mp4 @2fps | ~12 k | ~1.3 k | ~23 s |
| 8-dimension JSON QA on one video | ~20–29 s mp4 | 12–18 k | 3.7–6.7 k | 55–95 s |
| Reverse-write structured notes | same | 12–18 k | 3.1–4.3 k | 46–56 s |
| Transcribe one voice file | ~110 KB mp3 | ~0.1 k | ~0.3 k | ~5 s |

List price at test time: ¥0.8 / 1M input tokens, ¥2.7 / 1M output. The six-call full
evaluation over three videos cost about **¥0.15** total.

## Ground-truthed ability map

Evaluated against three finished editorial-collage videos whose production scripts,
headlines and narrations were known (4+4+6 shots, all Chinese):

**Reliable**

- Chinese speech transcription: all 14 sentences verbatim, including numerals
  ("2100万枚"), dashes and particles. (Via the standalone audio path the same
  utterance was normalized to "两千一百万枚" — semantically identical, so numeral
  *form* differs between paths; don't demand digit-for-digit transcriptions.)
- OCR of designed on-screen Chinese headlines: 14/14 characters correct. Punctuation
  may be normalized (full-width "？" → "?"), quotes may be added.
- Shot/section counts and section ordering.
- Total duration estimates within ~±4% of ffprobe reality (20/28/26 s videos).
- Scene/object/prop observation: faithful to frames, including things the production
  brief did not ask for (e.g. an actually-rendered "3D" logo the prompt forbade).
- Detecting *presence* of garbled/fake glyphs in newspaper textures (confirmed by
  human frame inspection).
- Detecting whether BGM contains human singing/voice (verified on a track with
  wordless female humming).

**Needs verification**

- Fine motion direction and ordering in a single shot ("flying outward" was once
  reported as "pulled inward"); same detail sometimes came out right in another call.
- Music mood / genre / SFX descriptions: plausible but partially fabricated
  (invented "paper-rustle SFX", missed humming on one video while reporting it on
  another). Treat as leads, listen to confirm.
- "Transcribing" garbled fake text: it emits confident-looking pseudo-glyph strings
  that do not match the pixels. Trust the *flag*, not the quoted shapes.
- QA verdicts without a brief: generic standards only; brief-specific breaches
  (flat-2D requirement, exact prop list) are missed unless the brief is supplied in
  the prompt.

## Large file / failure handling

- No manual handling is needed for 20 MB–1 GB local files: the upload to temporary
  storage is automatic, with progress notes on stderr.
- Files > 1 GB are rejected by the upload API; the script instead tells the caller to
  host the file on OSS and pass an https URL (model accepts up to 2 h / 2 GB).
- Temporary storage is a dev/test facility (48 h validity, 100 QPS policy limit, no
  SLA) — production systems should use Alibaba OSS and stable public URLs.
- On long videos: drop `--fps` (0.5–1.0), or extract the audio track and ask about
  sound and frames separately. Recipes: `references/ffprobe-cookbook.md`.
- HTTP 400 usually means unsupported codec/container, malformed media, or a missing
  `X-DashScope-OssResourceResolve` header on an oss:// call — remux to
  mp4/h264/aac or mp3/wav and retry.
- Rate limits / transient 5xx: retry by the caller; the script stays stateless.
