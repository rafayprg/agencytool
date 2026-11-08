# Pipeline notes

The pipeline is now the **Media Agency Studio** web app — see [README.md](README.md) for install, run and use.

Each step is one agent in `app/agents/`, run in order by `app/worker.py`:

| # | Agent | File | Output in `jobs/<id>/` |
|---|---|---|---|
| 1 | Downloader | `ingest.py` | `source/video.mp4`, `video.info.json`, thumbnail |
| 2 | Phone Cropper | `crop.py` | `analysis/phone.mp4`, `crop_preview.jpg`, `full_frame.jpg` |
| 3 | Transcriber | `transcribe.py` → `whisper_worker.py` | `analysis/transcript.json` |
| 4 | Scene Planner | `scenes.py` | `script/scenes_src.json` |
| 5 | Translator | `translate.py` (+ `gemini.py`) | `script/scenes.json` |
| 6 | Script Review | (you, in the UI) | `scenes.json` with `"reviewed": true` |
| 7 | Voice Artist | `voice.py` | `render/public/vo/*.mp3`, `render/timeline.json` |
| 8 | Video Editor | `render.py` → `studio/` (Remotion) | `render/final_16x9.mp4`, `final_9x16.mp4` |
| 9 | Publisher | `publish.py` | `publish/` videos, `captions.srt`, `metadata.json`, `UPLOAD.txt` |

`scripts/tts.py` and `jobs/rje9RIuUxjI/` are from the first hand-made remake (2026-11-06) and are kept only for reference.

Rights: republishing another channel's screen recording can get a copyright strike — use your own or licensed footage.
