"""Thread-safe, persisted settings plus live status for the LED clock.

This module has no matrix or Flask dependencies so it can be imported and unit
tested anywhere (including off the Raspberry Pi).

Feel free to do whatever you like with this code.
Distributed as-is; no warranty is given.

OzzMaker.com

"""

import copy
import json
import os
import threading
from types import SimpleNamespace

WIDTH = 64   # 16 px per panel x 4 panels chained horizontally (single source of truth)
HEIGHT = 16  # panel height

# Default settings == the settings.json schema.
DEFAULTS = {
    "brightness": 60,            # 0-100, applied in software to the background
    "display_on": True,         # False blanks the panels (all off)
    "time_format": "24h",       # "24h" | "12h"
    "leading_zero": True,       # pad the hour to two digits
    "colon_blink": True,        # blink the colon once per second
    "seconds_bar": True,        # progress bar along the bottom edge showing seconds
    "white_segments": False,    # draw digits/colon/bar lit white instead of unlit (negative)
    # background generator: color | plasma | aurora | metaballs | clouds | twinkle | ripples | spiral
    "background_mode": "color",
    "breathing": False,         # flourish: slow brightness pulse
    "sparkle": False,           # flourish: shimmer when the minute changes
    "tod_tint": False,          # flourish: warm/cool tint by time of day
    "palette": [                # cycling background colors (>= 1, hex strings)
        "#6ca8e0", "#9fe3c5", "#c2b4f0", "#f6c7a8",
        "#f4b8c8", "#f3e4a3", "#a8e0e6", "#a9c0ff",
    ],
    "color_order": "sequential",      # "sequential" | "random"
    "change_rate": "hour",            # "hour" | "minute"
    "fast": False,                    # cycle colors every few seconds (preview transitions)
    "transition": "fade",             # fade|instant|swipe_diagonal|wipe_vertical|random
    "transition_duration": 1.2,       # seconds (ignored for instant)
}

_ENUMS = {
    "time_format": {"24h", "12h"},
    "color_order": {"sequential", "random"},
    "change_rate": {"hour", "minute"},
    "transition": {"fade", "instant", "swipe_diagonal", "wipe_vertical", "random"},
    "background_mode": {"color", "plasma", "plasma_fade", "aurora", "metaballs",
                        "clouds", "twinkle", "ripples", "spiral", "scanner"},
}
_BOOLS = {"display_on", "leading_zero", "colon_blink", "seconds_bar", "white_segments",
          "breathing", "sparkle", "tod_tint", "fast"}


def hex_to_rgb(value):
    """'#rrggbb' -> (r, g, b)."""
    s = value.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % (rgb[0], rgb[1], rgb[2])


def is_valid_hex(value):
    if not isinstance(value, str):
        return False
    s = value.strip()
    if not s.startswith("#") or len(s) != 7:
        return False
    try:
        int(s[1:], 16)
        return True
    except ValueError:
        return False


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def validate_patch(patch):
    """Validate/coerce a settings patch.

    Returns (clean, errors): ``clean`` holds only the valid, coerced entries;
    ``errors`` lists human-readable problems for anything rejected.
    """
    clean = {}
    errors = []
    if not isinstance(patch, dict):
        return clean, ["payload must be a JSON object"]
    for key, val in patch.items():
        if key not in DEFAULTS:
            errors.append("unknown setting: %s" % key)
            continue
        try:
            if key == "brightness":
                clean[key] = _clamp(int(val), 0, 100)
            elif key == "transition_duration":
                clean[key] = round(_clamp(float(val), 0.0, 10.0), 2)
            elif key in _BOOLS:
                clean[key] = bool(val)
            elif key in _ENUMS:
                if val in _ENUMS[key]:
                    clean[key] = val
                else:
                    errors.append("%s: invalid value %r" % (key, val))
            elif key == "palette":
                if not isinstance(val, list) or not val:
                    errors.append("palette: must be a non-empty list")
                    continue
                good = [rgb_to_hex(hex_to_rgb(c)) for c in val if is_valid_hex(c)]
                bad = [c for c in val if not is_valid_hex(c)]
                if bad:
                    errors.append("palette: invalid colors %r" % bad)
                if good:
                    clean[key] = good
                else:
                    errors.append("palette: no valid colors")
        except (ValueError, TypeError):
            errors.append("%s: invalid value %r" % (key, val))
    return clean, errors


class Settings:
    """Thread-safe settings backed by a JSON file."""

    def __init__(self, path):
        self.path = path
        self._lock = threading.Lock()
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                stored = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return
        clean, _ = validate_patch(stored)
        with self._lock:
            self._data.update(clean)

    def _save_locked(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def as_dict(self):
        with self._lock:
            return copy.deepcopy(self._data)

    def snapshot(self):
        """A read-only attribute view of the current settings."""
        with self._lock:
            return SimpleNamespace(**copy.deepcopy(self._data))

    def update(self, patch):
        """Apply a validated patch and persist. Returns a list of errors."""
        clean, errors = validate_patch(patch)
        if clean:
            with self._lock:
                self._data.update(clean)
                self._save_locked()
        return errors

    def reset(self):
        with self._lock:
            self._data = copy.deepcopy(DEFAULTS)
            self._save_locked()


class Status:
    """Latest rendered frame + summary, published by the render thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._frame = [(0, 0, 0)] * (WIDTH * HEIGHT)
        self._color_hex = "#000000"
        self._color_index = 0
        self._palette_size = 1
        self._time = "--:--:--"
        self._display_on = True

    def publish(self, frame_buf, color_hex, color_index, palette_size,
                time_str, display_on):
        with self._lock:
            self._frame = list(frame_buf)  # copy: the render loop reuses its buffer
            self._color_hex = color_hex
            self._color_index = color_index
            self._palette_size = palette_size
            self._time = time_str
            self._display_on = display_on

    def status(self):
        with self._lock:
            return {
                "color_hex": self._color_hex,
                "color_index": self._color_index,
                "palette_size": self._palette_size,
                "time": self._time,
                "display_on": self._display_on,
            }

    def frame(self):
        with self._lock:
            buf = self._frame
        pixels = []
        for (r, g, b) in buf:
            pixels.extend((r, g, b))
        return {"w": WIDTH, "h": HEIGHT, "pixels": pixels}


class Control:
    """One-shot cross-thread signals from the web side to the render loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self._next = False

    def request_next(self):
        with self._lock:
            self._next = True

    def consume_next(self):
        with self._lock:
            value = self._next
            self._next = False
            return value
