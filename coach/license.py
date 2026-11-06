"""The licence key that unlocks the paid app (Lemon Squeezy License API).

A buyer gets a key in the Lemon Squeezy receipt email. The app window asks
for it once, activates it for this PC, and then checks it at most once a
day. Offline, the app keeps working for GRACE_DAYS after the last good check,
so a flaky connection never stops a match. When the subscription is cancelled
or unpaid, Lemon Squeezy marks the key expired or disabled and the window
asks the player to renew.

Only the public License API is used: no secret key ships in the app. Nothing
is sent but the key, a name for this PC and the instance id Lemon Squeezy
gave back. Licensing stays off until STORE_ID and PRODUCT_ID are filled in
(docs/product/paid-app.md), so builds before launch run as they do today.
"""

from __future__ import annotations

import json
import platform
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

API = "https://api.lemonsqueezy.com/v1/licenses"
# Filled in once Castien's Lemon Squeezy store and product exist.
STORE_ID: int | None = None
PRODUCT_ID: int | None = None
STORE_URL = ""  # the hosted store page, for "Buy" and "Renew"

CHECK_EVERY = 24 * 3600
GRACE_DAYS = 7
FILE_NAME = "license.json"

Post = Callable[[str, dict], dict]


def required() -> bool:
    return STORE_ID is not None and PRODUCT_ID is not None


@dataclass(frozen=True)
class Result:
    ok: bool
    message: str = ""


def post(url: str, fields: dict, timeout: float = 10.0) -> dict:
    """POSTs a form to the License API and returns its JSON, errors included.

    Raises OSError when Lemon Squeezy can't be reached at all."""
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # 400/404 carry a JSON "error"
        try:
            return json.loads(exc.read().decode("utf-8"))
        except (ValueError, OSError):
            raise OSError(f"Lemon Squeezy answered {exc.code}") from exc
    except ValueError as exc:
        raise OSError("Lemon Squeezy sent an answer the app can't read") from exc


def _ours(answer: dict) -> bool:
    meta = answer.get("meta") or {}
    return meta.get("store_id") == STORE_ID and meta.get("product_id") == PRODUCT_ID


def _why(answer: dict) -> str:
    status = (answer.get("license_key") or {}).get("status")
    if status == "expired":
        return "Your subscription has ended. Renew it to keep using the coach."
    if status == "disabled":
        return "This key was turned off. Check your subscription, or contact support."
    error = answer.get("error") or ""
    if "activation limit" in error.lower():
        return "This key is already used on another PC. Deactivate it there first."
    return "That key doesn't work. Copy it from your receipt email and try again."


class License:
    def __init__(self, app_dir: Path, post: Post = post, clock: Callable[[], float] = time.time) -> None:
        self.file = app_dir / FILE_NAME
        self._post, self._clock = post, clock

    def _load(self) -> dict:
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(json.dumps(data), encoding="utf-8")

    def activate(self, key: str) -> Result:
        """Activates a key for this PC; the window calls it from "Activate"."""
        key = key.strip()
        if not key:
            return Result(False, "Paste the licence key from your receipt email.")
        try:
            answer = self._post(f"{API}/activate", {"license_key": key, "instance_name": platform.node() or "PC"})
        except OSError:
            return Result(False, "Can't reach the licence server. Check your internet connection and try again.")
        if not answer.get("activated") or not _ours(answer):
            return Result(False, _why(answer) if answer.get("activated") is False else _why({}))
        self._save({"key": key, "instance_id": (answer.get("instance") or {}).get("id"), "last_ok": self._clock()})
        return Result(True, "Thanks! The coach is unlocked.")

    def check(self) -> Result:
        """Whether the app may run now; asks Lemon Squeezy at most once a day."""
        if not required():
            return Result(True)
        data = self._load()
        if not data.get("key"):
            return Result(False, "Enter your licence key to start.")
        now, last_ok = self._clock(), float(data.get("last_ok") or 0)
        if now - last_ok < CHECK_EVERY:
            return Result(True)
        fields = {"license_key": data["key"]}
        if data.get("instance_id"):
            fields["instance_id"] = data["instance_id"]
        try:
            answer = self._post(f"{API}/validate", fields)
        except OSError:
            if now - last_ok < GRACE_DAYS * 24 * 3600:
                return Result(True)
            return Result(False, f"The coach couldn't check your key for {GRACE_DAYS} days. Connect to the internet.")
        if answer.get("valid") and _ours(answer):
            self._save({**data, "last_ok": now})
            return Result(True)
        return Result(False, _why(answer))

    def forget(self) -> None:
        """Removes the saved key, e.g. to enter a different one."""
        try:
            self.file.unlink()
        except OSError:
            pass
