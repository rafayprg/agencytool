"""One video → many languages: language siblings share the main project's download and transcript."""
from .config import LANGUAGES
from .job import Job


def create(main: Job, langs: list[str], voices: dict[str, str] | None = None) -> list[Job]:
    """Make one sibling project per extra language (default voice per language unless given)."""
    voices = voices or {}
    out = []
    for lang in langs:
        if lang == main.data["options"]["lang"] or lang not in LANGUAGES:
            continue
        options = {**main.data["options"], "lang": lang, "voice": voices.get(lang) or LANGUAGES[lang][1]}
        child = Job.create(options, {"kind": "sibling", "input": main.id,
                                     "title": main.data.get("title", ""), "autopilot": main.data["source"].get("autopilot", False)})
        child.log("Orchestrator", f"{LANGUAGES[lang][0]} version of project {main.id}")
        out.append(child)
    if out:
        main.set(siblings=[*main.data.get("siblings", []), *(c.id for c in out)])
    return out
