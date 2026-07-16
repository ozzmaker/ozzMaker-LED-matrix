"""Rendering for the negative-style LED clock.

Everything is drawn into a plain in-memory ``Frame`` (a 64x16 list of RGB tuples),
then pushed to the panels on the Raspberry Pi.

Feel free to do whatever you like with this code.
Distributed as-is; no warranty is given.

OzzMaker.com


"""

import math
import random
import time
from datetime import datetime

from settings_store import WIDTH, HEIGHT, hex_to_rgb, rgb_to_hex

OFF = (0, 0, 0)           # an unlit pixel -> the negative digits/colon
DIGIT_W = 11              # width of a 7-segment digit cell
_GAP = 3                  # gap between adjacent digits
_COLON_W = 2              # width of the colon dots
_COLON_GAP = 3            # gap on each side of the colon

# x-positions of the five slots in "HH:MM", centered on the display width.
# Derived from WIDTH so the layout recenters automatically if the panel count changes.
_CONTENT_W = 4 * DIGIT_W + 2 * _GAP + 2 * _COLON_GAP + _COLON_W
_LEFT = (WIDTH - _CONTENT_W) // 2
POS_H_TENS = _LEFT
POS_H_ONES = POS_H_TENS + DIGIT_W + _GAP
POS_COLON = POS_H_ONES + DIGIT_W + _COLON_GAP
POS_M_TENS = POS_COLON + _COLON_W + _COLON_GAP
POS_M_ONES = POS_M_TENS + DIGIT_W + _GAP

# Each 7-segment rectangle, relative to the digit's left x: (dx, y, w, h).
# Full height: rows 1-14 (14 px tall).
_SEG_RECTS = {
    "a": (2, 1, 7, 2),    # top
    "b": (9, 2, 2, 6),    # upper right
    "c": (9, 8, 2, 6),    # lower right
    "d": (2, 13, 7, 2),   # bottom
    "e": (0, 8, 2, 6),    # lower left
    "f": (0, 2, 2, 6),    # upper left
    "g": (2, 7, 7, 2),    # middle
}
# Compact: rows 1-12 (12 px tall), used when the seconds bar needs the bottom rows.
_SEG_RECTS_SHORT = {
    "a": (2, 1, 7, 2),
    "b": (9, 2, 2, 5),
    "c": (9, 7, 2, 5),
    "d": (2, 11, 7, 2),
    "e": (0, 7, 2, 5),
    "f": (0, 2, 2, 5),
    "g": (2, 6, 7, 2),
}
_SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}

_STYLES = ("fade", "instant", "swipe_diagonal", "wipe_vertical")
_SWIPE_BAND = 4           # width (px) of the soft gradient at a swipe/wipe boundary
_PLASMA_SPEED = 1.2       # plasma animation speed (multiplier on elapsed time)
_PLASMA2_CYCLE = 0.06     # plasma-2: how fast the colors cycle through the palette
_PLASMA2_FADE = 0.5       # plasma-2: speed of the moving fade-to-black regions
_AURORA_SPEED = 0.5
_META_SPEED = 0.55
_META_STRENGTH = 14.0
_CLOUDS_SPEED = 2.2
_TWINKLE_SPEED = 2.2
_TWINKLE_WASH_SPEED = 0.6
_RIPPLE_SPEED = 2.2
_RIPPLE_FREQ = 0.55
_SPIRAL_SPEED = 1.5
_SPIRAL_ARMS = 2.0
_SPIRAL_FREQ = 0.4        # lower = thicker spiral arms
_SPIRAL_GAP = 50          # 0-100, higher = wider dark space between arms
_SPIRAL_HUE_DRIFT = 0.01  # how slowly the single spiral hue drifts through the palette
_SCANNER_SPEED = 1.6      # sweep speed (edge to edge ~0.6 s)
_SCANNER_TRAIL = 14       # length (columns) of the fading trail behind the head
_SCANNER_LEAD = 5         # length (columns) of the shorter fade ahead of the head
_SCANNER_HUE_DRIFT = 0.05 # how fast the bar's single hue drifts over time
_SCANNER_GAMMA = 2.2      # >1 makes the trail fade perceptually smoothly to black
_BREATHE_SPEED = 0.5
_BREATHE_MIN = 0.20       # dimmest point of the breathing pulse (fraction of brightness)
_SPARKLE_DUR = 1.3        # seconds the minute-sparkle burst lasts
_SPARKLE_COUNT = 28       # sparkle pixels drawn per frame during the burst


class Frame:
    """An 80x16 RGB pixel buffer, indexed as buf[y * WIDTH + x]."""

    __slots__ = ("buf",)

    def __init__(self):
        self.buf = [OFF] * (WIDTH * HEIGHT)

    def fill(self, color):
        self.buf = [color] * (WIDTH * HEIGHT)

    def fill_rows(self, y0, y1, color):
        """Fill whole rows in the half-open range [y0, y1)."""
        y0 = max(0, y0)
        y1 = min(HEIGHT, y1)
        span = [color] * WIDTH
        for y in range(y0, y1):
            base = y * WIDTH
            self.buf[base:base + WIDTH] = span

    def fill_rect(self, x, y, w, h, color):
        xs = max(0, x)
        xe = min(WIDTH, x + w)
        if xe <= xs:
            return
        span = [color] * (xe - xs)
        for yy in range(max(0, y), min(HEIGHT, y + h)):
            base = yy * WIDTH
            self.buf[base + xs:base + xe] = span


def scale(color, brightness):
    """Dim a color by brightness (0-100). Black stays black."""
    if brightness >= 100:
        return color
    if brightness <= 0:
        return OFF
    f = brightness / 100.0
    return (int(color[0] * f), int(color[1] * f), int(color[2] * f))


def lerp(c1, c2, p):
    return (
        round(c1[0] + (c2[0] - c1[0]) * p),
        round(c1[1] + (c2[1] - c1[1]) * p),
        round(c1[2] + (c2[2] - c1[2]) * p),
    )


def _paint_sweep(frame, from_raw, to_raw, p, brightness, u_max, u_of):
    """Paint a moving color boundary with a soft gradient band.

    ``u_of(x, y)`` is each pixel's position along the sweep direction; the
    boundary ``edge`` travels from just before 0 to just past ``u_max`` as ``p``
    goes 0 -> 1. Within ``_SWIPE_BAND`` pixels of the edge the old and new colors
    are blended, so the transition has a small gradient instead of a hard line.
    """
    band = _SWIPE_BAND
    half = band / 2.0
    edge = p * (u_max + band) - half
    from_c = scale(from_raw, brightness)
    to_c = scale(to_raw, brightness)
    buf = frame.buf
    for y in range(HEIGHT):
        base = y * WIDTH
        for x in range(WIDTH):
            d = edge - u_of(x, y)          # > 0 once the edge has passed (new color)
            if d >= half:
                buf[base + x] = to_c
            elif d <= -half:
                buf[base + x] = from_c
            else:
                buf[base + x] = scale(lerp(from_raw, to_raw, 0.5 + d / band), brightness)


_GRAD_SIZE = 256
_grad_cache = {}


def palette_gradient(palette, size=_GRAD_SIZE):
    """A smooth, cyclic color ramp built from the palette. Cached by palette."""
    key = (size, tuple(palette))
    lut = _grad_cache.get(key)
    if lut is None:
        cols = [hex_to_rgb(c) for c in palette]
        n = len(cols)
        lut = []
        for k in range(size):
            f = (k / size) * n
            i0 = int(f) % n
            lut.append(lerp(cols[i0], cols[(i0 + 1) % n], f - int(f)))
        if len(_grad_cache) > 16:
            _grad_cache.clear()
        _grad_cache[key] = lut
    return lut


def _breathe(t):
    """Smooth, eased brightness multiplier in [_BREATHE_MIN, 1.0] for a slow, deep pulse."""
    raw = 0.5 + 0.5 * math.sin(t * _BREATHE_SPEED)   # 0..1
    eased = raw * raw * (3.0 - 2.0 * raw)            # smoothstep: linger at the extremes
    return _BREATHE_MIN + (1.0 - _BREATHE_MIN) * eased


def _tod_factor(now):
    """Per-channel RGB tint: warm in the evening, cool in the early morning."""
    h = now.hour + now.minute / 60.0
    warmth = math.sin((h - 14.0) * (math.pi / 12.0))   # +1 ~20:00, -1 ~08:00
    return (1.0 + 0.12 * warmth, 1.0 + 0.02 * warmth, 1.0 - 0.12 * warmth)


def _apply_tint(frame, factor):
    """Multiply every (non-black) pixel by a per-channel tint."""
    tr, tg, tb = factor
    if abs(tr - 1.0) < 0.01 and abs(tb - 1.0) < 0.01:
        return
    buf = frame.buf
    for i in range(WIDTH * HEIGHT):
        r, g, b = buf[i]
        if r or g or b:
            nr = int(r * tr); ng = int(g * tg); nb = int(b * tb)
            buf[i] = (nr if nr < 255 else 255, ng if ng < 255 else 255, nb if nb < 255 else 255)


def _draw_sparkle(frame, intensity, brightness):
    """Scatter a few bright pixels that fade out — a shimmer when the minute rolls over."""
    buf = frame.buf
    w = int(255 * (brightness / 100.0))
    rnd = random.random
    rri = random.randrange
    n = WIDTH * HEIGHT
    for _ in range(_SPARKLE_COUNT):
        i = rri(n)
        a = intensity * rnd()
        px = buf[i]
        buf[i] = (int(px[0] + (w - px[0]) * a),
                  int(px[1] + (w - px[1]) * a),
                  int(px[2] + (w - px[2]) * a))


# 4x4 ordered (Bayer) dither offsets in (0, 1). Adding these before truncating spreads
# a brightness ramp across a fine spatial pattern instead of stepping in whole levels.
_DITHER = [(v + 0.5) / 16.0 for v in (
    0, 8, 2, 10,
    12, 4, 14, 6,
    3, 11, 1, 9,
    15, 7, 13, 5,
)]


def _apply_breath(frame, factor):
    """Dim the whole frame by ``factor``, ordered-dithered so the slow ramp looks smooth
    instead of banding into visible steps (the field is mostly flat, so plain rounding
    makes every pixel jump a level at the same instant)."""
    buf = frame.buf
    dither = _DITHER
    for y in range(HEIGHT):
        brow = y * WIDTH
        drow = (y & 3) * 4
        for x in range(WIDTH):
            i = brow + x
            r, g, b = buf[i]
            if r or g or b:
                d = dither[drow + (x & 3)]
                buf[i] = (int(r * factor + d), int(g * factor + d), int(b * factor + d))


class BackgroundManager:
    """Owns the current background color and any in-progress transition."""

    def __init__(self, palette):
        self.index = 0
        self.current = hex_to_rgb(palette[0]) if palette else OFF
        self.transition = None  # dict(from, to, style, start, dur) while animating

    @property
    def current_hex(self):
        return rgb_to_hex(self.current)

    def advance(self, s):
        """Pick the next palette color and start a transition toward it."""
        palette = s.palette
        n = len(palette)
        if n == 0:
            return
        if s.color_order == "random" and n > 1:
            self.index = random.choice([i for i in range(n) if i != self.index])
        else:
            self.index = (self.index + 1) % n
        to_color = hex_to_rgb(palette[self.index])

        style = random.choice(_STYLES) if s.transition == "random" else s.transition
        if style == "instant" or s.transition_duration <= 0:
            self.current = to_color
            self.transition = None
        else:
            self.transition = {
                "from": self.current,
                "to": to_color,
                "style": style,
                "start": time.monotonic(),
                "dur": s.transition_duration,
            }

    def paint(self, frame, brightness, now_mono=None):
        """Paint the background into ``frame`` for the current moment."""
        t = self.transition
        if t is None:
            frame.fill(scale(self.current, brightness))
            return

        if now_mono is None:
            now_mono = time.monotonic()
        p = (now_mono - t["start"]) / t["dur"]
        if p >= 1.0:
            self.current = t["to"]
            self.transition = None
            frame.fill(scale(self.current, brightness))
            return
        if p < 0.0:
            p = 0.0

        style = t["style"]
        if style == "fade":
            frame.fill(scale(lerp(t["from"], t["to"], p), brightness))
        elif style == "wipe_vertical":
            _paint_sweep(frame, t["from"], t["to"], p, brightness,
                         HEIGHT - 1, lambda x, y: y)
        elif style == "swipe_diagonal":
            _paint_sweep(frame, t["from"], t["to"], p, brightness,
                         (WIDTH - 1) + (HEIGHT - 1), lambda x, y: x + y)
        else:  # defensive fallback
            frame.fill(scale(t["to"], brightness))


class PlasmaField:
    """Animated plasma, colored by the palette as a cyclic gradient. Spatial phase
    tables are precomputed; each frame adds the time offset and a few sines per pixel."""

    def __init__(self):
        cx = (WIDTH - 1) / 2.0
        cy = (HEIGHT - 1) / 2.0
        n = WIDTH * HEIGHT
        self._a = [0.0] * n
        self._b = [0.0] * n
        self._d = [0.0] * n
        for y in range(HEIGHT):
            for x in range(WIDTH):
                i = y * WIDTH + x
                self._a[i] = x * 0.18
                self._b[i] = y * 0.30
                self._d[i] = math.hypot(x - cx, y - cy) * 0.22

    def paint(self, frame, t, palette, brightness):
        t *= _PLASMA_SPEED
        lut = palette_gradient(palette)
        size = len(lut)
        a, b, d = self._a, self._b, self._d
        buf = frame.buf
        sin = math.sin
        t2 = t * 0.85
        t3 = t * 0.60
        span = (size - 1) / 6.0                 # map v in [-3, 3] -> [0, size-1]
        f = brightness / 100.0
        full = brightness >= 100
        for i in range(WIDTH * HEIGHT):
            v = sin(a[i] + t) + sin(b[i] + t2) + sin(d[i] + t3)
            idx = int((v + 3.0) * span)
            if idx < 0:
                idx = 0
            elif idx >= size:
                idx = size - 1
            c = lut[idx]
            buf[i] = c if full else (int(c[0] * f), int(c[1] * f), int(c[2] * f))


class PlasmaFadeField(PlasmaField):
    """Plasma variant: the colors cycle through the palette over time, and moving
    regions fade to black (a second, slower layer drives the darkness)."""

    def paint(self, frame, t, palette, brightness):
        t *= _PLASMA_SPEED
        lut = palette_gradient(palette)
        span = len(lut) - 1
        a, b, d = self._a, self._b, self._d
        buf = frame.buf
        sin = math.sin
        t2 = t * 0.85
        t3 = t * 0.60
        cyc = t * _PLASMA2_CYCLE
        fade_t = t * _PLASMA2_FADE
        f = brightness / 100.0
        for i in range(WIDTH * HEIGHT):
            v = sin(a[i] + t) + sin(b[i] + t2) + sin(d[i] + t3)
            ci = (((v + 3.0) / 6.0) + cyc) % 1.0             # hue cycles over time
            c = lut[int(ci * span)]
            m = 0.5 + 0.5 * sin(a[i] * 0.6 + d[i] * 0.8 - fade_t)
            bri = m * m * f                                   # squared: fades to black
            buf[i] = (int(c[0] * bri), int(c[1] * bri), int(c[2] * bri))


class AuroraField:
    """Soft palette bands drifting sideways with a gentle vertical wave (northern lights)."""

    def __init__(self):
        n = WIDTH * HEIGHT
        self._px = [0.0] * n
        self._py = [0.0] * n
        for y in range(HEIGHT):
            for x in range(WIDTH):
                i = y * WIDTH + x
                self._px[i] = x * 0.10
                self._py[i] = y * 0.40

    def paint(self, frame, t, palette, brightness):
        t *= _AURORA_SPEED
        lut = palette_gradient(palette)
        size = len(lut)
        px, py = self._px, self._py
        buf = frame.buf
        sin = math.sin
        span = size - 1
        f = brightness / 100.0
        full = brightness >= 100
        for i in range(WIDTH * HEIGHT):
            v = 0.5 + 0.5 * sin(px[i] + t + sin(py[i] + t * 0.6))
            idx = int(v * span)
            c = lut[idx]
            buf[i] = c if full else (int(c[0] * f), int(c[1] * f), int(c[2] * f))


class MetaballsField:
    """A few soft blobs floating and merging — a lava-lamp look."""

    def __init__(self):
        n = WIDTH * HEIGHT
        self._x = [0.0] * n
        self._y = [0.0] * n
        for y in range(HEIGHT):
            for x in range(WIDTH):
                i = y * WIDTH + x
                self._x[i] = float(x)
                self._y[i] = float(y)

    def paint(self, frame, t, palette, brightness):
        t *= _META_SPEED
        lut = palette_gradient(palette)
        size = len(lut)
        xs, ys = self._x, self._y
        buf = frame.buf
        sin = math.sin
        s = _META_STRENGTH
        cx0 = WIDTH * (0.5 + 0.35 * sin(t * 0.70)); cy0 = HEIGHT * (0.5 + 0.40 * sin(t * 0.90 + 1.0))
        cx1 = WIDTH * (0.5 + 0.40 * sin(t * 0.50 + 2.0)); cy1 = HEIGHT * (0.5 + 0.40 * sin(t * 1.10 + 0.5))
        cx2 = WIDTH * (0.5 + 0.30 * sin(t * 0.90 + 4.0)); cy2 = HEIGHT * (0.5 + 0.40 * sin(t * 0.60 + 3.0))
        span = size - 1
        f = brightness / 100.0
        full = brightness >= 100
        for i in range(WIDTH * HEIGHT):
            X = xs[i]; Y = ys[i]
            field = (s / ((X - cx0) * (X - cx0) + (Y - cy0) * (Y - cy0) + 1.0)
                     + s / ((X - cx1) * (X - cx1) + (Y - cy1) * (Y - cy1) + 1.0)
                     + s / ((X - cx2) * (X - cx2) + (Y - cy2) * (Y - cy2) + 1.0))
            v = field if field < 1.0 else 1.0
            c = lut[int(v * span)]
            buf[i] = c if full else (int(c[0] * f), int(c[1] * f), int(c[2] * f))


class CloudsField:
    """Drifting, morphing soft noise — like slow clouds. Uses a precomputed smooth texture."""

    _TW = 128

    def __init__(self):
        tw, th = self._TW, HEIGHT
        tex = [random.random() for _ in range(tw * th)]
        for _ in range(4):
            tex = self._blur(tex, tw, th)
        lo = min(tex); hi = max(tex); rng = (hi - lo) or 1.0
        self._tex = [(v - lo) / rng for v in tex]
        self._tw = tw

    @staticmethod
    def _blur(tex, tw, th):
        out = [0.0] * (tw * th)
        for y in range(th):
            for x in range(tw):
                total = 0.0; count = 0
                for dy in (-1, 0, 1):
                    yy = y + dy
                    if 0 <= yy < th:
                        base = yy * tw
                        for dx in (-1, 0, 1):
                            total += tex[base + ((x + dx) % tw)]
                            count += 1
                out[y * tw + x] = total / count
        return out

    def paint(self, frame, t, palette, brightness):
        t *= _CLOUDS_SPEED
        lut = palette_gradient(palette)
        size = len(lut)
        tex, tw = self._tex, self._tw
        buf = frame.buf
        span = size - 1
        f = brightness / 100.0
        full = brightness >= 100
        i0 = int(t); xf = t - i0
        s2 = t * 0.6; j0 = int(s2); xf2 = s2 - j0
        for y in range(HEIGHT):
            row = y * tw
            brow = y * WIDTH
            for x in range(WIDTH):
                a = (x + i0) % tw
                v1 = tex[row + a] * (1.0 - xf) + tex[row + (a + 1) % tw] * xf
                b = (x + j0) % tw
                v2 = tex[row + b] * (1.0 - xf2) + tex[row + (b + 1) % tw] * xf2
                v = 0.5 * v1 + 0.5 * v2
                c = lut[int(v * span)]
                buf[brow + x] = c if full else (int(c[0] * f), int(c[1] * f), int(c[2] * f))


class TwinkleField:
    """A calm, slowly drifting palette wash with sparse twinkling stars."""

    def __init__(self):
        n = WIDTH * HEIGHT
        self._g = [0.0] * n
        for y in range(HEIGHT):
            for x in range(WIDTH):
                self._g[y * WIDTH + x] = x / (WIDTH - 1)
        self._stars = []
        for _ in range(int(n * 0.06)):
            i = random.randrange(n)
            self._stars.append((i, random.random() * 6.283, 0.5 + random.random() * 1.6))

    def paint(self, frame, t, palette, brightness):
        lut = palette_gradient(palette)
        size = len(lut)
        g = self._g
        buf = frame.buf
        sin = math.sin
        span = size - 1
        f = brightness / 100.0
        drift = t * _TWINKLE_WASH_SPEED * 0.05
        bf = f * 0.45
        for i in range(WIDTH * HEIGHT):
            v = (g[i] + drift) % 1.0
            c = lut[int(v * span)]
            buf[i] = (int(c[0] * bf), int(c[1] * bf), int(c[2] * bf))
        tt = t * _TWINKLE_SPEED
        for (i, phase, speed) in self._stars:
            b = 0.5 + 0.5 * sin(tt * speed + phase)
            if b <= 0.05:
                continue
            w = int(255 * f * b)
            px = buf[i]
            buf[i] = (px[0] if px[0] > w else w,
                      px[1] if px[1] > w else w,
                      px[2] if px[2] > w else w)


class RippleField:
    """Concentric water ripples from two emitters, interfering."""

    def __init__(self):
        n = WIDTH * HEIGHT
        sources = ((WIDTH * 0.5, HEIGHT * 0.5), (WIDTH * 0.18, HEIGHT * 0.5))
        self._d = []
        for (sx, sy) in sources:
            arr = [0.0] * n
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    arr[y * WIDTH + x] = math.hypot(x - sx, y - sy)
            self._d.append(arr)

    def paint(self, frame, t, palette, brightness):
        t *= _RIPPLE_SPEED
        lut = palette_gradient(palette)
        size = len(lut)
        d0, d1 = self._d[0], self._d[1]
        buf = frame.buf
        sin = math.sin
        k = _RIPPLE_FREQ
        span = size - 1
        f = brightness / 100.0
        full = brightness >= 100
        for i in range(WIDTH * HEIGHT):
            v = 0.5 + 0.25 * sin(d0[i] * k - t) + 0.25 * sin(d1[i] * k - t * 1.3)
            if v < 0.0:
                v = 0.0
            elif v > 1.0:
                v = 1.0
            c = lut[int(v * span)]
            buf[i] = c if full else (int(c[0] * f), int(c[1] * f), int(c[2] * f))


class SpiralField:
    """A spinning spiral: arms that wind out from the center and rotate over time."""

    def __init__(self):
        cx = (WIDTH - 1) / 2.0
        cy = (HEIGHT - 1) / 2.0
        n = WIDTH * HEIGHT
        self._ang = [0.0] * n
        self._rad = [0.0] * n
        for y in range(HEIGHT):
            for x in range(WIDTH):
                i = y * WIDTH + x
                self._ang[i] = math.atan2(y - cy, x - cx)
                self._rad[i] = math.hypot(x - cx, y - cy)

    def paint(self, frame, t, palette, brightness):
        t *= _SPIRAL_SPEED
        lut = palette_gradient(palette)
        size = len(lut)
        ang, rad = self._ang, self._rad
        buf = frame.buf
        sin = math.sin
        arms, freq = _SPIRAL_ARMS, _SPIRAL_FREQ
        # one slowly-drifting hue (less colorful); arms are bright bands of it
        base = lut[int(((t * _SPIRAL_HUE_DRIFT) % 1.0) * (size - 1))]
        br, bg, bb = base
        f = brightness / 100.0
        exp = 1.0 + (_SPIRAL_GAP / 100.0) * 5.0   # higher = narrower arms, wider dark gaps
        for i in range(WIDTH * HEIGHT):
            v = 0.5 + 0.5 * sin(arms * ang[i] - freq * rad[i] + t)
            s = (0.08 + 0.92 * v ** exp) * f    # bright arms, darker space between
            buf[i] = (int(br * s), int(bg * s), int(bb * s))


class ScannerField:
    """A single-hue bar with a fading trail (a comet) sweeping edge to edge, bouncing
    back and forth, on an otherwise black field."""

    def paint(self, frame, t, palette, brightness):
        t *= _SCANNER_SPEED
        lut = palette_gradient(palette)
        size = len(lut)
        f = brightness / 100.0
        frame.fill(OFF)                       # everything else black
        cycle = t % 2.0                       # ping-pong: 0 -> 1 -> 0
        moving_right = cycle <= 1.0
        tri = cycle if moving_right else 2.0 - cycle
        head = tri * (WIDTH - 1)              # bright head position
        base = lut[int(((t * _SCANNER_HUE_DRIFT) % 1.0) * (size - 1))]  # one drifting hue
        trail = _SCANNER_TRAIL
        lead = _SCANNER_LEAD
        buf = frame.buf
        for x in range(WIDTH):
            d = (head - x) if moving_right else (x - head)   # >0 behind head, <0 ahead
            if 0.0 <= d <= trail:
                b = 1.0 - d / trail            # long fading tail behind the head
            elif -lead <= d < 0.0:
                b = 1.0 + d / lead             # shorter fade ahead of the head
            else:
                continue
            b = (b ** _SCANNER_GAMMA) * f      # gamma curve -> smooth fade to black
            col = (int(base[0] * b), int(base[1] * b), int(base[2] * b))
            for y in range(HEIGHT):
                buf[y * WIDTH + x] = col


def _draw_digit(frame, x, char, color, rects=_SEG_RECTS):
    segments = _SEGMENTS.get(char)
    if not segments:
        return
    for name in segments:
        dx, dy, w, h = rects[name]
        frame.fill_rect(x + dx, dy, w, h, color)


def draw_time(frame, now, s, color=None):
    """Draw HH:MM (plus the colon and seconds bar) on top of the background.

    Normally the segments are OFF (black), reading as unlit cut-outs (the negative look);
    with ``white_segments`` they're drawn lit white (scaled by brightness) instead. When
    the seconds bar is shown, the digits use the shorter 12px variant so the bar stays
    clearly separated; otherwise they're full height.
    """
    if color is None:
        if getattr(s, "white_segments", False):
            w = int(255 * s.brightness / 100.0)
            color = (w, w, w)
        else:
            color = OFF
    show_bar = getattr(s, "seconds_bar", False)
    rects = _SEG_RECTS_SHORT if show_bar else _SEG_RECTS
    colon_top, colon_bot = (3, 8) if show_bar else (4, 10)

    hour = ((now.hour + 11) % 12) + 1 if s.time_format == "12h" else now.hour
    hh = "%02d" % hour if s.leading_zero else str(hour)
    mm = "%02d" % now.minute

    if len(hh) >= 2:
        _draw_digit(frame, POS_H_TENS, hh[-2], color, rects)
        _draw_digit(frame, POS_H_ONES, hh[-1], color, rects)
    else:
        _draw_digit(frame, POS_H_ONES, hh[-1], color, rects)  # blank the tens slot

    _draw_digit(frame, POS_M_TENS, mm[0], color, rects)
    _draw_digit(frame, POS_M_ONES, mm[1], color, rects)

    colon_on = (not s.colon_blink) or (now.microsecond < 500000)
    if colon_on:
        frame.fill_rect(POS_COLON, colon_top, 2, 2, color)
        frame.fill_rect(POS_COLON, colon_bot, 2, 2, color)

    if show_bar:   # bottom-row progress bar sweeping once per minute
        progress = (now.second + now.microsecond / 1000000.0) / 60.0
        filled = int(progress * WIDTH)
        if filled > 0:
            frame.fill_rect(0, HEIGHT - 1, filled, 1, color)


def compose(bg, s, now, brightness=None, now_mono=None):
    """Build a single complete frame (background + negative digits)."""
    frame = Frame()
    if not s.display_on:
        return frame  # all OFF
    b = s.brightness if brightness is None else brightness
    bg.paint(frame, b, now_mono)
    draw_time(frame, now, s)
    return frame


def frame_to_ascii(frame):
    """Render the frame as '#' (off/digit) vs '.' (lit) for quick checks."""
    buf = frame.buf
    lines = []
    for y in range(HEIGHT):
        base = y * WIDTH
        lines.append("".join("#" if buf[base + x] == OFF else "." for x in range(WIDTH)))
    return "\n".join(lines)


def _make_matrix():
    """Build the real RGBMatrix (imported lazily; Pi-only)."""
    from rgbmatrix import RGBMatrix, RGBMatrixOptions

    options = RGBMatrixOptions()
    options.rows = HEIGHT
    options.cols = 16
    options.chain_length = WIDTH // 16   # number of chained 16x16 panels (4 -> 64 wide)
    options.parallel = 1
    options.hardware_mapping = "regular"  # OzzMaker LED Connector
    options.brightness = 100              # we dim in software so changes are live
    options.gpio_slowdown = 2           # uncomment on a Pi 4 if the display flickers
    options.show_refresh_rate = True
    # Stay root after init: the library drops privileges to "daemon" by default,
    # which would break Flask (can't read templates/ or write settings.json under
    # /home, and crashes load_dotenv). We run under sudo on purpose.
    options.drop_privileges = False
    return RGBMatrix(options=options)


def run(settings, status, control, fast=False, stop_event=None):
    """Render loop: ~20 fps, blinking colon, hourly/per-minute color cycling."""
    bg = BackgroundManager(settings.snapshot().palette)
    generators = {
        "plasma": PlasmaField(),
        "plasma_fade": PlasmaFadeField(),
        "aurora": AuroraField(),
        "metaballs": MetaballsField(),
        "clouds": CloudsField(),
        "twinkle": TwinkleField(),
        "ripples": RippleField(),
        "spiral": SpiralField(),
        "scanner": ScannerField(),
    }

    matrix = _make_matrix()
    canvas = matrix.CreateFrameCanvas()

    last_field = None
    last_minute = datetime.now().minute
    sparkle_until = 0.0
    fast_interval = 3.0  # seconds per color when --fast

    while stop_event is None or not stop_event.is_set():
        s = settings.snapshot()
        now = datetime.now()
        mono = time.monotonic()

        if control.consume_next():
            bg.advance(s)

        if fast or s.fast:              # CLI --fast or the panel toggle
            field = int(mono // fast_interval)
        elif s.change_rate == "minute":
            field = now.minute
        else:
            field = now.hour
        if last_field is None:
            last_field = field
        elif field != last_field:
            bg.advance(s)
            last_field = field

        # the minute-sparkle window opens whenever the minute changes
        if now.minute != last_minute:
            last_minute = now.minute
            sparkle_until = mono + _SPARKLE_DUR

        frame = Frame()
        if s.display_on:
            generator = generators.get(s.background_mode)
            if generator is not None:
                generator.paint(frame, mono, s.palette, s.brightness)
            else:  # "color" (and any unknown mode): the cycling solid background
                bg.paint(frame, s.brightness, mono)
            if s.tod_tint:
                _apply_tint(frame, _tod_factor(now))
            if s.sparkle and mono < sparkle_until:
                _draw_sparkle(frame, (sparkle_until - mono) / _SPARKLE_DUR, s.brightness)
            if s.breathing:
                _apply_breath(frame, _breathe(mono))   # dithered: smooth, no banding
            draw_time(frame, now, s)

        status.publish(frame.buf, bg.current_hex, bg.index, len(s.palette),
                       now.strftime("%H:%M:%S"), s.display_on)

        buf = frame.buf
        for y in range(HEIGHT):
            base = y * WIDTH
            for x in range(WIDTH):
                r, g, b = buf[base + x]
                canvas.SetPixel(x, y, r, g, b)
        canvas = matrix.SwapOnVSync(canvas)

#        time.sleep(0.05)
