# ffprobe / ffmpeg cookbook for media understanding

The model tells you what it *thinks* a file is; ffprobe tells you what the file
**is**. Measure media facts with ffprobe, use model answers for meaning. All commands
work on Windows PowerShell; on macOS/Linux the same flags apply (swap path quoting).

## 1. What exactly is this file — one command

```powershell
ffprobe -v error -show_streams -show_format -of json clip.mp4
```

Frequently wanted fields (`format=duration,size,bit_rate`; per stream
`codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels`):

```powershell
ffprobe -v error -show_entries format=duration:stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels -of default=noprint_wrappers=1 clip.mp4
```

Machine-readable per line:

```powershell
ffprobe -v error -show_entries format=duration -of csv=p=0 clip.mp4
```

## 2. Container ≠ codec — anticipate API rejection

`file.mp4` / `file.mkv` says nothing about what is inside. An mkv may carry H.265,
AV1, FLAC or ASS subtitles — multimodal endpoints commonly accept only H.264/AAC.
Check before uploading:

```powershell
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 clip.mkv
```

If it is not `h264` (or audio not `aac`/`mp3`), transcode/remux rather than guessing:

```powershell
# safe universal target: h264 + aac in mp4
ffmpeg -y -i in.mkv -c:v libx264 -c:a aac out.mp4
# copy when the inner codecs are already fine (instant, lossless)
ffmpeg -y -i in.mov -c copy out.mp4
```

## 3. Frame extraction — verify what the model claimed to see

Two placements of `-ss`, genuinely different semantics:

```powershell
# fast seek (jumps to nearest keyframe): instant, timestamp may be a little off
ffmpeg -y -ss 12.5 -i clip.mp4 -frames:v 1 frame.jpg

# accurate seek (decodes up to the point): exact timestamp, slower on long files
ffmpeg -y -i clip.mp4 -ss 12.5 -frames:v 1 frame.jpg
```

- Spot-verifying a model claim ("at 12.5 s X happens") → accurate seek.
- One frame per second into a folder (indices zero-padded for sorting):

```powershell
ffmpeg -y -i clip.mp4 -vf fps=1 frames\f_%03d.jpg
```

- Downscale on extraction to keep review images light:
  `-vf "fps=1,scale=960:-1"`.

## 4. Extract audio — ask about sound cheaply, or pre-process it

```powershell
# direct stream copy when the container already has mp3/aac (instant, lossless)
ffmpeg -y -i clip.mp4 -vn -c:a copy voice.m4a

# transcode to mp3 when the source codec is exotic
ffmpeg -y -i clip.mp4 -vn -c:a libmp3lame -q:a 4 voice.mp3
```

Sending the extracted audio alone is far cheaper than the whole video when the
question is only about speech or sound.

## 5. Locate speech segments and silence

Useful before asking "what is said between 0:10 and 0:20", or to find shot/section
boundaries in speech-driven video:

```powershell
ffmpeg -i clip.mp4 -af "silencedetect=noise=-30dB:d=0.4" -f null -
```

stderr lists `silence_start` / `silence_end`. `noise` is the threshold (raise to
-24 dB for noisy recordings), `d` the minimum quiet gap in seconds.

Loudness / "is this track even audible / clipping":

```powershell
ffmpeg -i clip.mp4 -af volumedetect -f null -
ffmpeg -i clip.mp4 -af astats=metadata=1:reset=1 -f null -
```

## 6. Shrink before sending to the model

Rough size estimation: base64 inflates bytes by ~33%. A 19 MB file is a ~25 MB JSON
payload. Options in increasing order of aggressiveness:

```powershell
# lower video sampling fps on the API call instead: --fps 0.5  (no re-encode needed)

# trim to the relevant time range first
ffmpeg -y -ss 10 -i clip.mp4 -t 20 -c copy segment.mp4

# downscale + crf bitrate for heavy files
ffmpeg -y -i clip.mp4 -vf scale=1280:-2 -c:v libx264 -crf 30 -c:a aac -b:a 96k small.mp4

# sound-only question? strip video (see section 4)
```

## 7. Misc. pairing tricks

- Concatenate several short clips into one question (requires matching codecs;
  easiest is normalizing all to the same h264/aac profile, then concat demuxer).
- Burn a timecode overlay before sampling frames yourself:
  `-vf "drawtext=text='%{pts\:hms}':x=10:y=10:fontsize=32:fontcolor=yellow:box=1"`
  — gives every review frame an exact clock for verifying event timestamps.
- Probe a whole folder quickly (PowerShell):

```powershell
Get-ChildItem -Recurse -Include *.mp4,*.mov,*.mkv | ForEach-Object {
  $d = ffprobe -v error -show_entries format=duration -of csv=p=0 $_.FullName
  "{0,8:N1}s  {1}" -f [double]$d, $_.Name
}
```
