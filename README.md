# Media Agency Studio

A local web app that remakes phone-tutorial videos in another language — no Claude Code,
no paid API. Paste a YouTube link (or upload a file), choose a language, a voice and an
editing style, and a chain of agents hands you a finished video plus everything needed to upload it.

```
Link / upload ─► Downloader ─► Phone Cropper ─► Transcriber ─► Scene Planner ─► Translator
                                                                                      │
   Publisher ◄── Video Editor ◄── Voice Artist ◄── (Script Review: you check/edit) ◄──┘
```

| Agent | What it does | Runs on |
|---|---|---|
| Downloader | Video + title/tags from a YouTube video, playlist, channel, public Google Drive folder, or your upload. A playlist/channel/folder becomes one project per video. | yt-dlp, gdown |
| Phone Cropper | Finds the phone screen-recording in the frame and cuts it out (auto-detect; you can fix the box in the project page) | ffmpeg + numpy |
| Transcriber | Every spoken word with timings | faster-whisper, on your PC |
| Scene Planner | Splits the talk into scenes, finds the buttons to tap ("tap Settings") | rules |
| Translator | Translates (not rewrites) into your language, writes step headings + thumbnail words | Groq free key → Gemini free key → Google free → MyMemory free (choose in Settings) |
| Script Review | Optional pause so you can edit lines, headings and callouts | you |
| Voice Artist | Records each line with the voice you chose | edge-tts (free Microsoft voices) |
| Video Editor | Background, phone frame, headings, "TAP" callouts, word-by-word captions, music, 16:9 + 9:16 | Remotion |
| Thumbnail Artist | Saves the original creator's thumbnail and designs a new 1280×720 one in your language (hook words, "step by step" badge, the key phone screen) | Remotion still |
| Publisher | Videos, thumbnails, captions.srt, title, description with chapters, tags | — |

## Install (once)

1. Install **Python 3.12** (python.org, tick *Add to PATH*) and **Node.js 20+** (nodejs.org, LTS).
2. Copy this whole `media-agency` folder to your PC.
3. Double-click **`setup.bat`** (downloads libraries and the speech model; ~10 minutes).

## Run

Double-click **`start.bat`** → the browser opens **http://127.0.0.1:8790**.
To use another port: `set STUDIO_PORT=8899` before `start.bat`.

## Use

1. **New video** — paste a link or drop a file → pick language → listen to voices (▶) and pick one →
   pick an editing style → Start.
2. **Projects** — watch every agent work. When the script is ready (if review is on), edit it and press
   *Save & record voice*. At the end, play/download both videos, captions and the upload text.
3. In a finished project you can change the style, voice or speed and re-make without redoing the rest.
   A wrong phone box can be fixed there too (*Re-crop & re-render*).
4. **Editing styles** — edit colours, font, phone side, caption size, music; or upload a reference image /
   clip to create a matching style.
5. **Settings** — optional free Gemini key (https://aistudio.google.com/apikey) for natural translations
   and step headings; Whisper model size; defaults.

## Autopilot (24/7, watched folder)

Use it with your own downloader: the downloader saves videos into a folder, the studio makes them.

1. **Autopilot** tab → set the *watched folder* (and optionally an *output folder* for finished packages).
2. Pick language, voice, speed, style and formats once — every video uses them, with no review pause.
3. Press **Start autopilot**. Keep the PC and `start.bat` running.

How it behaves:
- Checks the folder every 30 s; a file is taken only when its size stops changing and it is older than the
  "wait" time (default 60 s), so half-downloaded files are never touched. `.part`/`.ytdl`/`.tmp` are ignored.
- Originals are **copied**, never moved or deleted. A `<name>.info.json` next to the video (yt-dlp style)
  gives the title, tags and language.
- `data/autopilot_ledger.json` remembers every file it took — nothing is made twice.
- At most "videos in progress at once" (default 2) wait/run; the rest are picked as those finish.
- A failed video (usually a network blip) is retried automatically after 10 minutes, up to 3 times.
- **Stop autopilot** stops picking new files; videos already being made finish (or stop them in Projects).

## Never the same video twice (Library)

Every video gets a fingerprint — its YouTube id (from the link or a `.info.json`), or a hash of the file.
`data/library.json` remembers them all. A video already made (or being made) is skipped by Autopilot and
refused on New video (tick *make it again* to override). The **Library** list on the Autopilot page shows
everything with its status and can be downloaded as CSV for Excel. Failed or deleted projects may be made again.

## Speed, many languages, two PCs

- **Pipeline (batch) mode** — Settings → *Pipeline*: while one video renders, the next ones are downloaded,
  transcribed, translated and voiced. 2–3 is best; 0 = one video at a time.
- **Graphics card** — run `setup-gpu.bat` once (NVIDIA only). Transcription then runs on the GPU
  (5–10× faster); *Auto* falls back to the CPU by itself.
- **One video → many languages** — tick *Also make this video in…* (New video) or *Also make every video in*
  (Autopilot). The download, crop and transcript are done once; each language gets its own project.
  The Library remembers videos per language, so a Spanish version never blocks a Portuguese one.
- **Two PCs** — share one folder on the network (e.g. `\\WHITE-PC\studio-shared`) and put it in
  Settings → *Shared library folder* on both PCs. Both can then watch the same downloads folder: each
  video (per language) is claimed by exactly one PC.
- **Disk saver** — Autopilot deletes working files after each video (the finished package stays; with an
  output folder only that copy is kept) and pauses when free disk space drops below the limit.
- **Telegram** — Settings → Telegram: a message for every finished or failed video and when Autopilot pauses.
- **Auto-start** — `install-autostart.bat` starts the studio minimised every time you log in to Windows
  (`remove-autostart.bat` undoes it). Set Windows *Sleep* to *Never* for night runs.

## Costs

Everything is free. Internet is needed for downloading, the free translators and the voices.
The Gemini key is optional and uses Google AI Studio's free tier.

## Folders

```
app/server.py        web server + API (FastAPI)
app/worker.py        the orchestrator that runs the agents
app/agents/          one file per agent
app/web/             the browser UI
studio/              the Remotion video editor (React)
styles/*.json        editing styles
jobs/<id>/           everything for one video (source, analysis, script, render, publish)
data/settings.json   your settings (Gemini key stays here, on your PC)
crop_presets.json    fixed phone boxes per YouTube channel, e.g. {"Channel name": "W:H:X:Y"}
```

## Rights

Re-publishing another channel's footage can get a copyright strike. Use your own recordings,
your clients' footage, or videos you have permission to use.
