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
REF_CROPS = (
    (0.13, 0.0, 0.87, 1.0),
    (0.10, 0.0, 0.90, 1.0),
    (0.16, 0.0, 0.84, 1.0),
    (0.13, 0.05, 0.87, 1.0),
    (0.13, 0.0, 0.87, 0.95),
)


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
    def __init__(self, references: dict[int, Image.Image]) -> None:
        ids, rows = [], []
        for hero_id, image in references.items():
            for part in REF_CROPS:
                features = _features(image, part)
                if features is not None:
                    ids.append(hero_id)
                    rows.append(features)
        self.ids = ids
        self.matrix = np.stack(rows) if rows else np.zeros((0, SAMPLE[0] * SAMPLE[1] * 3))

    def match(self, crop: Image.Image) -> tuple[int | None, float]:
        """The best-matching hero id and its similarity (1.0 is identical)."""
        features = _features(crop)
        if features is None or not self.ids:
            return None, 0.0
        scores = self.matrix @ features
        best = int(np.argmax(scores))
        return self.ids[best], float(scores[best])


def read_top_bar(
    strip: Image.Image,
    screen_size: tuple[int, int],
    layout: Layout,
    matcher: PortraitMatcher,
    min_score: float = 0.6,
) -> list[tuple[int | None, float]]:
    """(hero id or None, score) for each of the ten slots in a top-of-screen strip."""
    results = []
    for box in layout.slots(*screen_size):
        hero_id, score = matcher.match(strip.crop(box))
        results.append((hero_id if score >= min_score else None, score))
    return results


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
    min_score = float(settings.get("min_score", 0.6))
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="hero-images")
    matcher = pool.submit(lambda: PortraitMatcher(load_references(heroes, cache_dir)))
    pool.shutdown(wait=False)

    def read() -> list[int | None]:
        strip, size = grab_top_strip(layout)
        results = read_top_bar(strip, size, layout, matcher.result(timeout=60), min_score)
        return [hero_id for hero_id, _ in results]

    return read
