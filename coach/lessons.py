"""Lessons from coaching videos, for replay review: py -m coach learn-video FILE

A coach on video explains *why* while showing the game. This turns a video
file on your PC into lesson cards the replay review can learn from:

1. faster-whisper (the voice extra) writes down what the coach says, with
   times; the advice is cut into stretches of about 20 seconds.
2. For each stretch, two frames from that moment (read with PyAV, which
   faster-whisper installs) and the coach's words go to your vision model,
   which writes a card: the situation on screen, the point, why it matters,
   what to do, and tags.
3. Cards are saved as JSON (plus one frame) in the app folder's lessons/,
   one folder per video. Read them, delete the wrong ones.

In replay review, the cards that match the moment (same kind of moment,
same stage of the game) go into the prompt as a real coach's examples, so
the model reasons from them instead of guessing.

Nothing is downloaded: the video must already be on your PC, and should be
one you are allowed to use.
"""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .vision import MAX_WIDTH, Frame

log = logging.getLogger(__name__)

FOLDER = "lessons"
CHUNK_SECONDS = 20.0
TAGS = ("laning", "last hits", "trading", "creep equilibrium", "pulling", "stacking", "rotation", "rune",
        "lotus", "fight", "death", "escape", "vision", "map awareness", "farming", "items", "objectives",
        "positioning", "spell use")
STAGES = ("laning", "mid", "late")

CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "skip": {"type": "boolean"},
        "situation": {"type": "string"},
        "point": {"type": "string"},
        "why": {"type": "string"},
        "advice": {"type": "string"},
        "line": {"type": "string"},
        "stage": {"type": "string", "enum": list(STAGES)},
        "tags": {"type": "array", "items": {"type": "string", "enum": list(TAGS)}},
    },
    "required": ["skip"],
}

SYSTEM = """\
You turn a moment from a Dota 2 coaching video into a lesson card. You get \
two frames from that moment and what the coach said over them. Write what \
the coach teaches, in your own short words: the situation on screen, the \
point the coach makes, why it matters, and what to do. In "line", write \
what a coach would say about it to the player afterwards, in the past tense, \
casually, at most 30 words (for example: "There you stayed at half health \
with three of them missing. Backing off would have saved that death."). \
Use only what the \
coach said and what the frames show; never add your own advice. If the \
coach says nothing about how to play (an intro, a joke, a sponsor), answer \
{"skip": true}. Answer as JSON only."""


@dataclass
class Lesson:
    situation: str
    point: str
    why: str
    advice: str
    stage: str = "laning"
    tags: list[str] = field(default_factory=list)
    source: str = ""  # "video name at 12:34"
    said: str = ""  # the coach's own words
    line: str = ""  # the past-tense line a coach would say (the training answer)
    frames: list[str] = field(default_factory=list)  # saved frame files, oldest first

    def text(self) -> str:
        return f"{self.situation} {self.point} Why: {self.why} Better: {self.advice}"


@dataclass
class Chunk:
    start: float
    end: float
    text: str


def chunks(segments: Iterable[tuple[float, float, str]], seconds: float = CHUNK_SECONDS) -> Iterator[Chunk]:
    """Speech segments joined into stretches of about `seconds`."""
    current: Chunk | None = None
    for start, end, text in segments:
        text = text.strip()
        if not text:
            continue
        if current is None:
            current = Chunk(start, end, text)
        elif end - current.start > seconds:
            yield current
            current = Chunk(start, end, text)
        else:
            current.end, current.text = end, current.text + " " + text
    if current is not None:
        yield current


def transcribe(video: Path, model: str = "small", language: str | None = None) -> list[tuple[float, float, str]]:
    from faster_whisper import WhisperModel

    whisper = WhisperModel(model, device="auto", compute_type="int8")
    segments, _ = whisper.transcribe(str(video), language=language, vad_filter=True)
    return [(s.start, s.end, s.text) for s in segments]


def frames_at(video: Path, times: list[float], max_width: int = MAX_WIDTH) -> list[Frame]:
    """JPEG frames at these times (seconds), read with PyAV."""
    import av

    out: list[Frame] = []
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        for t in times:
            container.seek(int(t / stream.time_base), stream=stream, any_frame=False, backward=True)
            for frame in container.decode(stream):
                if frame.time is not None and frame.time >= t - 0.05:
                    image = frame.to_image()
                    if image.width > max_width:
                        image = image.resize((max_width, round(image.height * max_width / image.width)))
                    buf = io.BytesIO()
                    image.convert("RGB").save(buf, "JPEG", quality=80)
                    out.append(buf.getvalue())
                    break
    return out


def card(reply: str | None, chunk: Chunk, source: str) -> Lesson | None:
    """A Lesson from the model's JSON, or None to skip."""
    try:
        data = json.loads(reply or "")
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("skip") or not data.get("point"):
        return None
    stage = data.get("stage") if data.get("stage") in STAGES else "laning"
    tags = [t for t in data.get("tags") or [] if t in TAGS]
    minutes, seconds = divmod(int(chunk.start), 60)
    return Lesson(
        situation=str(data.get("situation", "")), point=str(data["point"]), why=str(data.get("why", "")),
        advice=str(data.get("advice", "")), stage=stage, tags=tags,
        source=f"{source} at {minutes}:{seconds:02d}", said=chunk.text, line=str(data.get("line", "")),
    )


def learn(
    video: Path,
    app_dir: Path,
    ask: Callable[[str, list[Frame]], str | None],
    segments: list[tuple[float, float, str]] | None = None,
    grab: Callable[[Path, list[float]], list[Frame]] = frames_at,
    say: Callable[[str], None] = print,
) -> list[Lesson]:
    """Writes lesson cards for one video; returns them."""
    folder = app_dir / FOLDER / _slug(video.stem)
    folder.mkdir(parents=True, exist_ok=True)
    if segments is None:
        say("Writing down what the coach says (a few minutes for a long video)...")
        segments = transcribe(video)
    stretches = list(chunks(segments))
    lessons = []
    for n, chunk in enumerate(stretches, 1):
        # The start, middle and end of the moment, like replay review's looks.
        frames = grab(video, [chunk.start + 1, (chunk.start + chunk.end) / 2, max(chunk.end - 1, chunk.start + 1)])
        if not frames:
            continue
        lesson = card(ask(f'The coach said: "{chunk.text}"', frames), chunk, video.stem)
        if lesson is None:
            continue
        for k, frame in enumerate(frames):
            (folder / f"{n:03d}-{k}.jpg").write_bytes(frame)
            lesson.frames.append(f"{n:03d}-{k}.jpg")
        (folder / f"{n:03d}.json").write_text(json.dumps(asdict(lesson), indent=2, ensure_ascii=False), encoding="utf-8")
        lessons.append(lesson)
        say(f"{n}/{len(stretches)} {lesson.source}: {lesson.point}")
    say(f"Saved {len(lessons)} lessons from {len(stretches)} stretches in {folder}")
    return lessons


VIDEO_TYPES = {".mp4", ".mkv", ".webm", ".mov", ".avi"}


def videos(path: Path) -> list[Path]:
    """The video, or every video in a folder."""
    if path.is_dir():
        return sorted(p for p in path.iterdir() if p.suffix.lower() in VIDEO_TYPES)
    return [path]


def load(app_dir: Path, with_paths: bool = False) -> list:
    """Every saved lesson; with_paths gives (lesson, its folder) pairs."""
    out = []
    for path in sorted((app_dir / FOLDER).glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            lesson = Lesson(**{k: v for k, v in data.items() if k in Lesson.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            log.warning("Skipped a lesson card that isn't valid: %s", path)
            continue
        out.append((lesson, path.parent) if with_paths else lesson)
    return out


# Training data ---------------------------------------------------------------

TRAIN_PROMPT = "Talk this moment of my replay over with me: what did I do wrong, and what would have been better?"


def answer(lesson: Lesson) -> str:
    """What the trained model should say: the coach-style line, else the card."""
    if lesson.line:
        return lesson.line
    return " ".join(x for x in (lesson.point, lesson.why, lesson.advice) if x)


def export(app_dir: Path, out_dir: Path, holdout: float = 0.1, system: str = "") -> tuple[int, int]:
    """Writes train.jsonl and test.jsonl (chat format with images, as
    Unsloth, TRL and most vision fine-tuning tools read it) plus the images.
    Every tenth lesson of each video goes to test, to check the model on
    moments it never saw. Returns (train, test) counts."""
    import shutil

    images = out_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    every = max(2, round(1 / holdout)) if holdout > 0 else 0
    counts = {"train": 0, "test": 0}
    files = {name: (out_dir / f"{name}.jsonl").open("w", encoding="utf-8") for name in counts}
    try:
        seen: dict[Path, int] = {}
        for lesson, folder in load(app_dir, with_paths=True):
            if not lesson.frames:
                continue
            seen[folder] = seen.get(folder, 0) + 1
            split = "test" if every and seen[folder] % every == 0 else "train"
            content = []
            for name in lesson.frames:
                target = images / f"{folder.name}-{name}"
                shutil.copyfile(folder / name, target)
                content.append({"type": "image", "image": f"images/{target.name}"})
            content.append({"type": "text", "text": TRAIN_PROMPT})
            messages = ([{"role": "system", "content": [{"type": "text", "text": system}]}] if system else []) + [
                {"role": "user", "content": content},
                {"role": "assistant", "content": [{"type": "text", "text": answer(lesson)}]},
            ]
            files[split].write(json.dumps({"messages": messages, "source": lesson.source}, ensure_ascii=False) + "\n")
            counts[split] += 1
    finally:
        for f in files.values():
            f.close()
    return counts["train"], counts["test"]


# Which tags fit each kind of moment in replay review.
MOMENT_TAGS = {
    "died": {"death", "fight", "escape", "positioning", "map awareness", "vision"},
    "hurt": {"fight", "trading", "escape", "positioning"},
    "paused": set(),
    "regular": {"laning", "last hits", "creep equilibrium", "farming", "positioning", "map awareness"},
}


def matching(lessons: list[Lesson], reason: str, stage: str, n: int = 2) -> list[Lesson]:
    """The lessons that fit this moment best: same stage first, then tags."""
    wanted = MOMENT_TAGS.get(reason, set())

    def score(lesson: Lesson) -> int:
        return (3 if lesson.stage == stage else 0) + len(wanted & set(lesson.tags))

    ranked = sorted((ls for ls in lessons if score(ls) >= 3), key=score, reverse=True)
    return ranked[:n]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "video"
