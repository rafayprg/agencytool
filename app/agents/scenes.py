"""Stage 4: transcript -> scenes (one spoken sentence-group each, mapped to a slice
of the phone footage) + the on-screen UI label to call out ("tap X")."""
import json
import re

from .job import Job

MAX_SCENE_SEC = 14.0
MIN_SCENE_SEC = 3.0
ACTION_RE = re.compile(
    r"\b(?:tap|click|select|press|open|choose|hit|toggle|turn on|turn off|go (?:in)?to|head (?:over )?to|scroll (?:down )?to)"
    r"\s+(?:on\s+|up\s+|onto\s+|into\s+)?((?:[^,.?!;:]|\.(?=\w))+)",  # keeps "google.com" whole
    re.IGNORECASE,
)
STOP_RE = re.compile(
    r"(?:^|\s+)\b(?:at|and|from|so|which|then|here|there|for|if|because|when|after|while|to|in order|"
    r"it'll|it will|you'll|you can|every|each|button|icon|option|menu|tab)\b.*$",
    re.IGNORECASE,
)
LEAD_RE = re.compile(r"^(?:the|your|that|this|a|an|little|those|these)\s+", re.IGNORECASE)
NOT_LABELS = {"", "it", "this", "that", "them", "there", "here", "now", "then", "so", "up", "down", "back"}
MAX_LABEL_WORDS = 5
SPLIT_DOT_RE = re.compile(r"(\w) \.(\w)")  # whisper writes "google .com"


def _sentences(segments: list[dict]) -> list[dict]:
    words = [w for seg in segments for w in seg.get("words", []) if w["w"]]
    if not words:  # no word timings: fall back to whisper segments
        return [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments]
    out, cur = [], []
    for w in words:
        cur.append(w)
        dur = cur[-1]["e"] - cur[0]["s"]
        if re.search(r"[.?!]$", w["w"]) and dur >= MIN_SCENE_SEC or dur >= MAX_SCENE_SEC:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return [{"start": c[0]["s"], "end": c[-1]["e"], "text": " ".join(w["w"] for w in c)} for c in out]


def find_callout(text: str) -> str:
    """'Next, tap on manage your Google account at the top.' -> 'Manage your Google account'."""
    m = ACTION_RE.search(text)
    if not m:
        return ""
    label = STOP_RE.sub("", m.group(1).strip())
    for _ in range(3):
        label = LEAD_RE.sub("", label)
    words = label.split()
    if not words or len(words) > MAX_LABEL_WORDS or label.lower() in NOT_LABELS:
        return ""
    return label[0].upper() + label[1:]


def clean_text(text: str) -> str:
    return SPLIT_DOT_RE.sub(lambda m: m.group(1) + "." + m.group(2), text)


def build(segments: list[dict], duration: float) -> list[dict]:
    sents = _sentences(segments)
    scenes = []
    for i, s in enumerate(sents):
        start = 0.0 if i == 0 else s["start"]
        end = sents[i + 1]["start"] if i + 1 < len(sents) else duration
        scenes.append({
            "id": i + 1,
            "src": [round(start, 2), round(max(end, start + 1), 2)],
            "text_src": clean_text(s["text"]),
            "callout_src": find_callout(clean_text(s["text"])),
        })
    return scenes


def run(job: Job) -> None:
    transcript = json.loads(job.path("analysis", "transcript.json").read_text(encoding="utf8"))
    scenes = build(transcript["segments"], job.data["duration"])
    job.path("script", "scenes_src.json").write_text(json.dumps(scenes, ensure_ascii=False, indent=1), encoding="utf8")
    job.log("Scene Planner", f"{len(scenes)} scenes, {sum(1 for s in scenes if s['callout_src'])} with a tap callout")
