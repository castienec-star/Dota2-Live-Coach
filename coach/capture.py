"""Reads the ten hero portraits from the top bar of the game, once per match.

This is the coach's only look at the screen, and it is off unless you turn it
on in coach.toml. When on, it captures one thin strip at the very top of your
main monitor just before the horn (a second try if the first misses heroes),
compares the ten portraits there with Valve's official hero images, and throws
the picture away. It never touches the Dota process, saves nothing, and reads
nothing else on screen.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .heroes import HeroInfo

log = logging.getLogger(__name__)

CDN_URL = "https://cdn.cloudflare.steamstatic.com"
SAMPLE = (24, 14)  # portraits are compared at this size
# The top bar shows each hero's portrait slanted, so the coach reads a box
# inside it. These are the parts of Valve's full portrait (left, top, right,
# bottom, as fractions) that such a box may show; the best one counts.
REF_CROPS = tuple(
    (inset + shift, top, 1 - inset + shift, bottom)
    for inset in (0.13, 0.09, 0.17)
    for shift in (0.0, -0.03, 0.03)
    for top in (0.0, 0.05)
    for bottom in (1.0, 0.95)
)
# A portrait counts as read when its best hero scores at least min_score and
# beats every other hero by MARGIN, or scores SURE whatever the others do.
MARGIN = 0.05
SURE = 0.75


@dataclass(frozen=True)
class Layout:
    """Where the top bar portraits sit. All sizes are fractions of screen height,
    because Dota scales its interface with height and centers the top bar."""

    # Measured on a 1920-wide screenshot at patch 7.41.
    top: float = 0.0046
    height: float = 0.0316
    width: float = 0.0428
    step: float = 0.0576  # from one portrait's left edge to the next
    gap: float = 0.1018  # from the screen's center to the nearest box

    @classmethod
    def from_settings(cls, settings: dict) -> Layout:
        fields = cls.__dataclass_fields__
        return cls(**{k: float(v) for k, v in settings.items() if k in fields})

    def strip_height(self, screen_h: int) -> int:
        return int(round((self.top + self.height) * screen_h)) + 1

    def slots(self, screen_w: int, screen_h: int) -> list[tuple[int, int, int, int]]:
        """(left, top, right, bottom) of the ten portraits: Radiant left to right,
        then Dire left to right."""
        cx = screen_w / 2
        top = self.top * screen_h
        bottom = top + self.height * screen_h
        width, step, gap = self.width * screen_h, self.step * screen_h, self.gap * screen_h
        lefts = [cx - gap - (5 - i) * step + (step - width) for i in range(5)]
        lefts += [cx + gap + i * step for i in range(5)]
        return [(round(x), round(top), round(x + width), round(bottom)) for x in lefts]


def _features(
    image: Image.Image, part: tuple[float, float, float, float] = (0, 0, 1, 1)
) -> np.ndarray | None:
    w, h = image.size
    box = (round(part[0] * w), round(part[1] * h), round(part[2] * w), round(part[3] * h))
    small = image.convert("RGB").crop(box).resize(SAMPLE, Image.BILINEAR)
    values = np.asarray(small, dtype=np.float32).ravel()
    values -= values.mean()
    norm = float(np.linalg.norm(values))
    # A flat crop (black screen, empty slot) can't be matched.
    if norm < 1e-3 or values.std() < 4:
        return None
    return values / norm


class PortraitMatcher:
    def __init__(
        self,
        references: dict[int, Image.Image],
        taught: list[tuple[int, Image.Image]] = (),
    ) -> None:
        ids, rows = [], []
        for hero_id, image in references.items():
            for part in REF_CROPS:
                features = _features(image, part)
                if features is not None:
                    ids.append(hero_id)
                    rows.append(features)
        # Portraits you taught are already top bar boxes, so they are used whole.
        for hero_id, image in taught:
            features = _features(image)
            if features is not None:
                ids.append(hero_id)
                rows.append(features)
        self.ids = ids
        self.matrix = np.stack(rows) if rows else np.zeros((0, SAMPLE[0] * SAMPLE[1] * 3))

    def candidates(self, crop: Image.Image, top: int = 3) -> list[tuple[int, float]]:
        """The best-matching heroes and their similarity (1.0 is identical), best first."""
        features = _features(crop)
        if features is None or not self.ids:
            return []
        best: dict[int, float] = {}
        for hero_id, score in zip(self.ids, (self.matrix @ features).tolist()):
            if score > best.get(hero_id, -1.0):
                best[hero_id] = score
        return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:top]

    def match(self, crop: Image.Image, min_score: float = 0.5) -> tuple[int | None, float]:
        """The hero in a portrait, or None when no hero is a clear match; and its score."""
        found = self.candidates(crop, top=2)
        if not found:
            return None, 0.0
        hero_id, score = found[0]
        runner_up = found[1][1] if len(found) > 1 else -1.0
        clear = score >= SURE or (score >= min_score and score - runner_up >= MARGIN)
        return (hero_id if clear else None), score


def read_top_bar(
    strip: Image.Image,
    screen_size: tuple[int, int],
    layout: Layout,
    matcher: PortraitMatcher,
    min_score: float = 0.5,
) -> list[tuple[int | None, float]]:
    """(hero id or None, score) for each of the ten slots in a top-of-screen strip."""
    return [matcher.match(strip.crop(box), min_score) for box in layout.slots(*screen_size)]


def load_references(
    heroes: dict[int, HeroInfo], cache_dir: Path, cdn_url: str = CDN_URL, timeout: float = 5.0
) -> dict[int, Image.Image]:
    """Official hero portraits, downloaded once from Valve's CDN and kept on disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    images: dict[int, Image.Image] = {}
    failed = 0
    for hero in heroes.values():
        path = cache_dir / f"{hero.key}.png"
        if not path.is_file() and hero.img:
            try:
                with urllib.request.urlopen(cdn_url + hero.img, timeout=timeout) as response:
                    path.write_bytes(response.read())
            except (urllib.error.URLError, TimeoutError, OSError):
                failed += 1
                continue
        try:
            with Image.open(path) as image:
                images[hero.id] = image.convert("RGB")
        except (OSError, ValueError):
            failed += 1
    if failed:
        log.warning("Could not get %d hero pictures; those heroes can't be read", failed)
    return images


def load_taught(heroes: dict[int, HeroInfo], cache_dir: Path) -> list[tuple[int, Image.Image]]:
    """Portraits you taught with draft-test --teach, for heroes the official
    picture doesn't match well (new art, personas)."""
    by_key = {h.key: h.id for h in heroes.values()}
    taught = []
    for path in sorted((cache_dir / "taught").glob("*.png")):
        hero_id = by_key.get(path.stem.rsplit("-", 1)[0])
        if hero_id is None:
            continue
        try:
            with Image.open(path) as image:
                taught.append((hero_id, image.convert("RGB")))
        except (OSError, ValueError):
            log.warning("Could not read taught portrait %s", path.name)
    return taught


def teach(hero: HeroInfo, portrait: Image.Image, cache_dir: Path) -> Path:
    """Keep a top bar portrait as an extra picture of this hero."""
    folder = cache_dir / "taught"
    folder.mkdir(parents=True, exist_ok=True)
    n = 1
    while (folder / f"{hero.key}-{n}.png").exists():
        n += 1
    path = folder / f"{hero.key}-{n}.png"
    portrait.save(path)
    return path


def grab_top_strip(layout: Layout) -> tuple[Image.Image, tuple[int, int]]:
    """Capture only the thin strip at the top of the main monitor (Windows)."""
    import mss

    with mss.mss() as screen:
        monitor = screen.monitors[1]
        size = (monitor["width"], monitor["height"])
        region = {
            "left": monitor["left"],
            "top": monitor["top"],
            "width": monitor["width"],
            "height": layout.strip_height(monitor["height"]),
        }
        shot = screen.grab(region)
    return Image.frombytes("RGB", shot.size, shot.rgb), size


def load_screenshot(path: Path) -> tuple[Image.Image, tuple[int, int]]:
    """A saved full screenshot, as if it had been captured (for calibration)."""
    with Image.open(path) as image:
        rgb = image.convert("RGB")
    return rgb, rgb.size


def make_reader(
    settings: dict, heroes: dict[int, HeroInfo], cache_dir: Path
) -> Callable[[], list[int | None]]:
    """A function that captures the top bar and returns the ten hero ids.

    Hero pictures load in the background at start-up, so the first match
    doesn't wait for them."""
    layout = Layout.from_settings(settings)
    min_score = float(settings.get("min_score", 0.5))
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hero-images")
    matcher = pool.submit(
        lambda: PortraitMatcher(
            load_references(heroes, cache_dir), load_taught(heroes, cache_dir)
        )
    )
    pool.shutdown(wait=False)

    def read() -> list[int | None]:
        strip, size = grab_top_strip(layout)
        results = read_top_bar(strip, size, layout, matcher.result(timeout=60), min_score)
        return [hero_id for hero_id, _ in results]

    return read
