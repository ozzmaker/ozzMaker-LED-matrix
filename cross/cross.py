"""
LED Cross Animation Suite
Five 16x16 HUB75 RGB panels in a cross formation on Raspberry Pi.

Layout:
         [TOP]
  [LEFT][CENTRE][RIGHT]
        [BOTTOM]

Feel free to do whatever you like with this code.
Distributed as-is; no warranty is given.

Ozzmaker.com

"""

import time
import math
import random
import colorsys
import numpy as np
from PIL import Image

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions
    REAL_HARDWARE = True
except ImportError:
    print("rgbmatrix not found — running in simulation mode.")
    REAL_HARDWARE = False



# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PANEL_SIZE     = 16
FPS            = 60
CHAIN_LENGTH   = 5
PARALLEL_COUNT = 1
GPIO_SLOWDOWN  = 2       # Increase (1–4) if you see glitches

# Brightness: 0.0 (off) → 1.0 (full). Applied globally to every frame.
# Reduce to 0.3–0.5 for indoor/night use, or to save power.
BRIGHTNESS     = 0.3

# Physical chain order: top first, bottom last.
PANEL_CHAIN_ORDER = ["top", "left", "centre", "right", "bottom"]

# Panels mounted upside-down — pixel data is rotated 180° before being sent.
FLIPPED_PANELS = {"top", "bottom"}


# ---------------------------------------------------------------------------
# Cross canvas
# ---------------------------------------------------------------------------

# Each panel's top-left corner in "cross-space" coordinates.
# Centre panel sits at (0, 0).
PANEL_OFFSETS = {
    "centre": ( 0,          0),
    "top":    ( 0,         -PANEL_SIZE),
    "bottom": ( 0,          PANEL_SIZE),
    "left":   (-PANEL_SIZE, 0),
    "right":  ( PANEL_SIZE, 0),
}

CROSS_MIN_X = -PANEL_SIZE
CROSS_MAX_X =  PANEL_SIZE * 2
CROSS_MIN_Y = -PANEL_SIZE
CROSS_MAX_Y =  PANEL_SIZE * 2
CROSS_W     = CROSS_MAX_X - CROSS_MIN_X   # 48
CROSS_H     = CROSS_MAX_Y - CROSS_MIN_Y   # 48


def _make_cross_mask():
    mask = np.zeros((CROSS_H, CROSS_W), dtype=bool)
    for ox, oy in PANEL_OFFSETS.values():
        px = ox - CROSS_MIN_X
        py = oy - CROSS_MIN_Y
        mask[py:py + PANEL_SIZE, px:px + PANEL_SIZE] = True
    return mask


CROSS_MASK = _make_cross_mask()


class CrossCanvas:
    """
    A 48x48 numpy RGB buffer representing the full cross.
    Only pixels inside CROSS_MASK are physically illuminated.
    """

    def __init__(self):
        self.buf = np.zeros((CROSS_H, CROSS_W, 3), dtype=np.uint8)

    def clear(self):
        self.buf[:] = 0

    def set(self, x, y, r, g, b):
        bx = int(x) - CROSS_MIN_X
        by = int(y) - CROSS_MIN_Y
        if 0 <= bx < CROSS_W and 0 <= by < CROSS_H and CROSS_MASK[by, bx]:
            self.buf[by, bx] = (r, g, b)

    def fill(self, r, g, b):
        self.buf[CROSS_MASK] = (r, g, b)

    def fill_panel(self, panel, r, g, b):
        ox, oy = PANEL_OFFSETS[panel]
        px = ox - CROSS_MIN_X
        py = oy - CROSS_MIN_Y
        self.buf[py:py + PANEL_SIZE, px:px + PANEL_SIZE] = (r, g, b)

    def apply_mask(self):
        """Zero out pixels outside the cross shape, then apply global brightness."""
        self.buf[~CROSS_MASK] = 0
        if BRIGHTNESS < 1.0:
            self.buf[CROSS_MASK] = (
                self.buf[CROSS_MASK].astype(np.float32) * max(0.0, min(1.0, BRIGHTNESS))
            ).astype(np.uint8)


# ---------------------------------------------------------------------------
# Hardware driver
# ---------------------------------------------------------------------------

class MatrixDriver:
    def __init__(self):
        if not REAL_HARDWARE:
            self.matrix = self.offscreen = None
            return

        options = RGBMatrixOptions()
        options.rows             = PANEL_SIZE
        options.cols             = PANEL_SIZE
        options.chain_length     = CHAIN_LENGTH
        options.parallel         = PARALLEL_COUNT
        options.hardware_mapping = "regular"
        options.gpio_slowdown    = GPIO_SLOWDOWN

        self.matrix    = RGBMatrix(options=options)
        self.offscreen = self.matrix.CreateFrameCanvas()

    def show(self, canvas: CrossCanvas):
        if not REAL_HARDWARE:
            return

        fb = self.offscreen
        fb.Clear()

        for chain_idx, panel_name in enumerate(PANEL_CHAIN_ORDER):
            ox, oy = PANEL_OFFSETS[panel_name]
            bx     = ox - CROSS_MIN_X
            by_    = oy - CROSS_MIN_Y
            seg    = canvas.buf[by_:by_ + PANEL_SIZE, bx:bx + PANEL_SIZE]

            # Top and bottom panels are mounted upside-down — rotate 180°.
            if panel_name in FLIPPED_PANELS:
                seg = seg[::-1, ::-1]

            dest_x = chain_idx * PANEL_SIZE

            for py in range(PANEL_SIZE):
                for px in range(PANEL_SIZE):
                    r, g, b = int(seg[py, px, 0]), int(seg[py, px, 1]), int(seg[py, px, 2])
                    fb.SetPixel(dest_x + px, py, r, g, b)

        self.offscreen = self.matrix.SwapOnVSync(fb)


# ---------------------------------------------------------------------------
# Base animation class
# ---------------------------------------------------------------------------

class Animation:
    def __init__(self, canvas: CrossCanvas):
        self.canvas = canvas
        self.frame  = 0
        self.t      = 0.0

    def tick(self, dt: float):
        self.t     += dt
        self.frame += 1
        self.draw()

    def draw(self):
        raise NotImplementedError

    @staticmethod
    def hsv(h, s=1.0, v=1.0):
        r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
        return int(r * 255), int(g * 255), int(b * 255)


# ---------------------------------------------------------------------------
# Rainbow Flow
# ---------------------------------------------------------------------------

class RainbowFlow(Animation):
    """Diagonal hue wave washes across the entire cross."""

    def __init__(self, canvas, speed=0.35, scale=0.05):
        super().__init__(canvas)
        self.speed = speed
        self.scale = scale

    def draw(self):
        c     = self.canvas
        phase = self.t * self.speed
        buf   = c.buf

        for cy in range(CROSS_H):
            for cx in range(CROSS_W):
                if not CROSS_MASK[cy, cx]:
                    continue
                hue = (cx * self.scale + cy * self.scale * 0.6 + phase) % 1.0
                buf[cy, cx] = self.hsv(hue)

# ---------------------------------------------------------------------------
# Old Skool Plasma
# ---------------------------------------------------------------------------

class Plasma(Animation):
    """
    Classic demo-scene plasma effect.
    Four overlapping sine waves — distance rings, diagonal waves, and a
    spinning offset — combine into a continuously morphing hue field.
    Pure maths, no lookup tables needed at this resolution.
    """

    def __init__(self, canvas, speed=0.9, palette_speed=0.15):
        super().__init__(canvas)
        self.speed         = speed
        self.palette_speed = palette_speed

        # Pre-compute pixel coords relative to cross centre
        cx = CROSS_W / 2.0
        cy = CROSS_H / 2.0
        ys, xs = np.mgrid[0:CROSS_H, 0:CROSS_W]
        self._dx = (xs - cx).astype(np.float32)
        self._dy = (ys - cy).astype(np.float32)
        self._dist = np.sqrt(self._dx ** 2 + self._dy ** 2).astype(np.float32)

    def draw(self):
        c  = self.canvas
        t  = self.t * self.speed
        pt = self.t * self.palette_speed

        dx   = self._dx
        dy   = self._dy
        dist = self._dist

        # Four classic plasma functions blended together
        v1 = np.sin(dx * 0.30 + t)
        v2 = np.sin(dy * 0.30 - t * 0.7)
        v3 = np.sin(dist * 0.25 - t * 1.1)
        v4 = np.sin((dx * 0.20 + dy * 0.15) + t * 0.8)

        plasma = (v1 + v2 + v3 + v4) * 0.25   # range roughly -1 .. 1
        plasma = (plasma + 1.0) * 0.5          # normalise to 0 .. 1

        # Map plasma value → hue (shift over time for colour cycling)
        hue_arr = (plasma + pt) % 1.0

        # Vectorised HSV → RGB conversion
        # Use colorsys logic: hue sector + fraction
        h6  = hue_arr * 6.0
        i   = h6.astype(np.int32) % 6
        f   = h6 - np.floor(h6)
        q   = (1.0 - f)
        t_  = f

        r = np.select(
            [i==0, i==1, i==2, i==3, i==4, i==5],
            [np.ones_like(f), q, np.zeros_like(f), np.zeros_like(f), t_, np.ones_like(f)]
        )
        g = np.select(
            [i==0, i==1, i==2, i==3, i==4, i==5],
            [t_, np.ones_like(f), np.ones_like(f), q, np.zeros_like(f), np.zeros_like(f)]
        )
        b = np.select(
            [i==0, i==1, i==2, i==3, i==4, i==5],
            [np.zeros_like(f), np.zeros_like(f), t_, np.ones_like(f), np.ones_like(f), q]
        )

        c.buf[:, :, 0] = (r * 255).astype(np.uint8)
        c.buf[:, :, 1] = (g * 255).astype(np.uint8)
        c.buf[:, :, 2] = (b * 255).astype(np.uint8)

# ---------------------------------------------------------------------------
# Spiral
# ---------------------------------------------------------------------------

class TwisterSpiral(Animation):
    """
    Multiple glowing spiral arms rotate from the centre of the cross.
    Arm colours cycle through a vibrant palette. The arms compress
    toward the edges for a hypnotic vortex pull.
    """
    def __init__(self, canvas, arms=4, speed=8.0, tightness=0.25):
        super().__init__(canvas)
        self.arms      = arms
        self.speed     = speed
        self.tightness = tightness
        self.cx        = CROSS_W / 2.0
        self.cy        = CROSS_H / 2.0

    def draw(self):
        c   = self.canvas
        buf = c.buf
        t   = self.t

        for cy in range(CROSS_H):
            for cx in range(CROSS_W):
                if not CROSS_MASK[cy, cx]:
                    continue

                dx   = cx - self.cx
                dy   = cy - self.cy
                r    = math.sqrt(dx * dx + dy * dy)
                if r < 0.01:
                    buf[cy, cx] = (255, 255, 255)
                    continue

                angle = math.atan2(dy, dx)

                # Spiral: for each arm, how close is this pixel to the arm?
                arm_offset = 2 * math.pi / self.arms
                best_dist  = 2 * math.pi

                for arm_i in range(self.arms):
                    arm_angle = arm_i * arm_offset + t * self.speed + r * self.tightness
                    # Angular distance to the arm (wrapped)
                    diff = ((angle - arm_angle + math.pi) % (2 * math.pi)) - math.pi
                    if abs(diff) < best_dist:
                        best_dist = abs(diff)

                # Width of each arm narrows toward edges
                arm_width = math.pi / (self.arms * 1.5)
                if best_dist < arm_width:
                    closeness = 1.0 - best_dist / arm_width
                    v         = closeness ** 1.8
                    hue       = (r / (CROSS_W / 2.0) * 0.5 + t * 0.08) % 1.0
                    buf[cy, cx] = self.hsv(hue, 0.8, v)
                else:
                    # Dark background with faint glow
                    glow = max(0, 0.06 - best_dist * 0.01)
                    hue  = (t * 0.06) % 1.0
                    buf[cy, cx] = self.hsv(hue, 1.0, glow)

# ---------------------------------------------------------------------------
# Animation — Spinning Zooming Letters A B C
# ---------------------------------------------------------------------------

class SpinningABC(Animation):
    """
    Shows A, B, C, 1, 2, 3 in sequence. Each character gets exactly one
    full zoom-in/zoom-out cycle (zoom out → zoom in → zoom out), then the
    next character takes over. Stops on the last character.
    """

    LETTERS = {
        "A": [
            (-0.5,  1.0,  0.0, -1.0),
            ( 0.5,  1.0,  0.0, -1.0),
            (-0.28, 0.15, 0.28, 0.15),
        ],
        "B": [
            (-0.4, -1.0, -0.4,  1.0),
            (-0.4, -1.0,  0.2, -1.0),
            (-0.4,  0.0,  0.2,  0.0),
            (-0.4,  1.0,  0.2,  1.0),
            ( 0.2, -1.0,  0.48,-0.5),
            ( 0.48,-0.5,  0.2,  0.0),
            ( 0.2,  0.0,  0.52, 0.5),
            ( 0.52, 0.5,  0.2,  1.0),
        ],
        "C": [
            ( 0.38,-0.75,  0.0, -1.0),
            ( 0.0, -1.0,  -0.38,-1.0),
            (-0.38,-1.0,  -0.5, -0.5),
            (-0.5, -0.5,  -0.5,  0.5),
            (-0.5,  0.5,  -0.38, 1.0),
            (-0.38, 1.0,   0.0,  1.0),
            ( 0.0,  1.0,   0.38, 0.75),
        ],
        "1": [
            ( 0.0, -1.0,  0.0,  1.0),   # vertical stroke
            (-0.2, -0.7,  0.0, -1.0),   # top-left serif
            (-0.3,  1.0,  0.3,  1.0),   # base
        ],
        "2": [
            (-0.4, -0.7,  0.0, -1.0),   # top-left arc up
            ( 0.0, -1.0,  0.4, -0.7),   # top arc right
            ( 0.4, -0.7,  0.4, -0.2),   # right side down
            ( 0.4, -0.2, -0.4,  0.7),   # diagonal sweep
            (-0.4,  0.7, -0.4,  1.0),   # bottom-left
            (-0.4,  1.0,  0.4,  1.0),   # base
        ],
        "3": [
            (-0.4, -1.0,  0.4, -1.0),   # top
            ( 0.4, -1.0,  0.4,  0.0),   # right top half
            ( 0.0,  0.0,  0.4,  0.0),   # middle right
            (-0.2,  0.0,  0.4,  0.0),   # middle bar
            ( 0.4,  0.0,  0.4,  1.0),   # right bottom half
            (-0.4,  1.0,  0.4,  1.0),   # bottom
            (-0.4, -1.0, -0.4, -0.8),   # top-left serif
            (-0.4,  0.8, -0.4,  1.0),   # bottom-left serif
        ],
    }
    SEQUENCE   = ["A", "B", "C", "1", "2", "3"]
    SPIN_SPEED = 0.9
    ZOOM_SPEED = 0.55   # one full cycle = 1/ZOOM_SPEED seconds ≈ 1.82 s
    MIN_SCALE  = 4.0
    MAX_SCALE  = 17.0

    def __init__(self, canvas):
        super().__init__(canvas)
        self._cx            = CROSS_MIN_X + CROSS_W / 2.0
        self._cy            = CROSS_MIN_Y + CROSS_H / 2.0
        self._letter_idx    = 0
        self._zoom_cycles   = 0          # completed cycles for current letter
        self._prev_zoom_sin = -1.0       # start at trough so first crossing counts
        self._done          = False

    @staticmethod
    def _line_pixels(x0, y0, x1, y1):
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        while True:
            yield x0, y0
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0  += sx
            if e2 < dx:
                err += dx
                y0  += sy

    def draw(self):
        c = self.canvas
        c.clear()
        if self._done:
            return

        zoom_sin = math.sin(self.t * self.ZOOM_SPEED * 2 * math.pi)

        # Detect trough crossing (negative → positive = one full cycle complete)
        if self._prev_zoom_sin < 0 and zoom_sin >= 0:
            self._zoom_cycles += 1
            if self._zoom_cycles >= 1:
                # One cycle done — advance to next character
                self._zoom_cycles = 0
                self._letter_idx += 1
                if self._letter_idx >= len(self.SEQUENCE):
                    self._done = True
                    return
        self._prev_zoom_sin = zoom_sin

        scale   = self.MIN_SCALE + (self.MAX_SCALE - self.MIN_SCALE) * (0.5 + 0.5 * zoom_sin)
        angle   = self.t * self.SPIN_SPEED
        cos_a   = math.cos(angle)
        sin_a   = math.sin(angle)
        hue     = (self._letter_idx / len(self.SEQUENCE))
        strokes = self.LETTERS[self.SEQUENCE[self._letter_idx]]

        lit = set()
        for sx0, sy0, sx1, sy1 in strokes:
            px0, py0 = sx0 * scale, sy0 * scale
            px1, py1 = sx1 * scale, sy1 * scale
            rx0 = px0 * cos_a - py0 * sin_a + self._cx
            ry0 = px0 * sin_a + py0 * cos_a + self._cy
            rx1 = px1 * cos_a - py1 * sin_a + self._cx
            ry1 = px1 * sin_a + py1 * cos_a + self._cy
            for px, py in self._line_pixels(rx0, ry0, rx1, ry1):
                lit.add((px, py))

        core_col  = self.hsv(hue, 0.5, 1.0)
        inner_col = self.hsv(hue, 0.9, 0.6)

        for (px, py) in lit:
            for dy, dx in ((-1,0),(1,0),(0,-1),(0,1)):
                c.set(px + dx, py + dy, *inner_col)
            c.set(px, py, *core_col)


# ---------------------------------------------------------------------------
# Animation — Expanding Circles
# ---------------------------------------------------------------------------

class ExpandingCircles(Animation):
    """
    Concentric rings spawn at the cross centre and expand outward, fading
    as they grow — like being zoomed into a target, or ripples from a
    stone dropped at the centre.
    Each ring has its own hue; the palette drifts slowly over time.
    """

    EXPAND_SPEED   = 9.0    # pixels per second
    SPAWN_INTERVAL = 0.55   # seconds between new rings

    def __init__(self, canvas):
        super().__init__(canvas)
        self._cx = CROSS_MIN_X + CROSS_W / 2.0
        self._cy = CROSS_MIN_Y + CROSS_H / 2.0

        # Precompute per-pixel distance from cross centre
        dist = np.zeros((CROSS_H, CROSS_W), dtype=np.float32)
        for cy in range(CROSS_H):
            for cx in range(CROSS_W):
                wx = cx + CROSS_MIN_X + 0.5
                wy = cy + CROSS_MIN_Y + 0.5
                dist[cy, cx] = math.sqrt((wx - self._cx) ** 2 + (wy - self._cy) ** 2)
        self._dist     = dist
        self._max_r    = float(dist[CROSS_MASK].max())

        # Rings: [radius, hue]
        self._rings      = []
        self._next_spawn = 0.0
        self._hue_base   = 0.0

    def draw(self):
        c  = self.canvas
        c.clear()
        dt = 1.0 / FPS
        self._hue_base = (self._hue_base + dt * 0.05) % 1.0

        # Spawn new ring
        if self.t >= self._next_spawn:
            hue = (self._hue_base + len(self._rings) * 0.18) % 1.0
            self._rings.append([0.0, hue])
            self._next_spawn = self.t + self.SPAWN_INTERVAL

        buf = c.buf
        for ring in self._rings[:]:
            ring[0] += self.EXPAND_SPEED * dt
            radius, hue = ring

            if radius > self._max_r + 2:
                self._rings.remove(ring)
                continue

            life = max(0.0, 1.0 - radius / self._max_r)
            diff = np.abs(self._dist - radius)

            # Soft ring width: 1.4 px half-width
            mask = (diff < 1.4) & CROSS_MASK
            if not mask.any():
                continue

            v_arr  = np.maximum(0.0, (1.4 - diff) / 1.4 * life)
            hr, hg, hb = colorsys.hsv_to_rgb(hue, 1.0, 1.0)

            r_add = (v_arr * hr * 255).astype(np.uint16)
            g_add = (v_arr * hg * 255).astype(np.uint16)
            b_add = (v_arr * hb * 255).astype(np.uint16)

            buf[:, :, 0] = np.minimum(255, buf[:, :, 0].astype(np.uint16) + r_add)
            buf[:, :, 1] = np.minimum(255, buf[:, :, 1].astype(np.uint16) + g_add)
            buf[:, :, 2] = np.minimum(255, buf[:, :, 2].astype(np.uint16) + b_add)



# ---------------------------------------------------------------------------
# Shared PPM loader
# ---------------------------------------------------------------------------

def _load_ppm(path):
    """Load a PPM (P6 binary or P3 ASCII) file. Returns (pixels, width, height)."""
    with open(path, 'rb') as f:
        raw = f.read()

    def tokens(data):
        i = 0
        while i < len(data):
            if data[i:i+1] == b'#':
                while i < len(data) and data[i:i+1] not in (b'\n', b'\r'):
                    i += 1
            elif data[i:i+1] in (b' ', b'\t', b'\n', b'\r'):
                i += 1
            else:
                j = i
                while j < len(data) and data[j:j+1] not in (b' ', b'\t', b'\n', b'\r'):
                    j += 1
                yield data[i:j], i
                i = j

    tok              = tokens(raw)
    magic,    _      = next(tok)
    width_b,  _      = next(tok)
    height_b, _      = next(tok)
    maxval_b, pos    = next(tok)
    magic  = magic.decode()
    width  = int(width_b)
    height = int(height_b)
    maxval = int(maxval_b)

    if magic == 'P6':
        data_start = pos + len(maxval_b) + 1
        data = raw[data_start:]
        pixels = [(data[i] * 255 // maxval,
                   data[i+1] * 255 // maxval,
                   data[i+2] * 255 // maxval)
                  for i in range(0, width * height * 3, 3)]
    else:
        values = [int(t) for t, _ in tok]
        pixels = [(values[i] * 255 // maxval,
                   values[i+1] * 255 // maxval,
                   values[i+2] * 255 // maxval)
                  for i in range(0, len(values), 3)]
    return pixels, width, height



# ---------------------------------------------------------------------------
# Animation — PPM Horizontal Scroll
# ---------------------------------------------------------------------------

class PPMScrollH(Animation):
    """
    Scrolls a PPM image once right→left across the horizontal panels
    (left / centre / right). The image is scaled to 16 px tall.
    Holds black after the image exits. Speed: --ppm-speed px/s.
    """

    IMAGE_PATH = "image.ppm"
    SPD        = 50.0

    def __init__(self, canvas):
        super().__init__(canvas)
        pixels, w, h = _load_ppm(self.IMAGE_PATH)
        # Scale to PANEL_SIZE tall

        self._px   = pixels
        self._w    = w
        self._hx   = 0.0          # scroll offset: 0 → CROSS_W + w
        self._done = False
        self._row0 = PANEL_SIZE   # top of centre panel row in canvas coords

    def draw(self):
        c   = self.canvas
        c.clear()
        if self._done:
            return
        buf  = c.buf
        self._hx += self.SPD / FPS
        if self._hx >= CROSS_W + self._w:
            self._done = True
            return
        for cy in range(PANEL_SIZE):
            crow = self._row0 + cy
            if crow < 0 or crow >= CROSS_H:
                continue
            for cx in range(CROSS_W):
                if not CROSS_MASK[crow, cx]:
                    continue
                img_x = int(cx + self._hx - CROSS_W)
                if 0 <= img_x < self._w:
                    buf[crow, cx] = self._px[cy * self._w + img_x]



# ---------------------------------------------------------------------------
# Animation — PPM Vertical Scroll
# ---------------------------------------------------------------------------

class PPMScrollV(Animation):
    """
    Scrolls a PPM image once top→bottom down the vertical panels
    (top / centre / bottom). The image is scaled to 16 px wide.
    Holds black after the image exits. Speed: --ppm-speed px/s.
    """

    IMAGE_PATH = "image_v.ppm"
    SPD        = 50.0

    def __init__(self, canvas):
        super().__init__(canvas)
        pixels, w, h = _load_ppm(self.IMAGE_PATH)
        # Scale to PANEL_SIZE wide

        self._px   = pixels
        self._h    = h

        self._vy   = 0.0          # scroll offset: 0 → CROSS_H + h
        self._done = False
        self._col0 = PANEL_SIZE   # left of centre panel column in canvas coords

    def draw(self):
        c   = self.canvas
        c.clear()
        g=0
        if self._done:
            return
        buf  = c.buf
        self._vy += self.SPD / FPS
        if self._vy >= CROSS_H + self._h:
            self._done = True
            return
        for cy in range(CROSS_H):
            # Image top is at canvas row (_vy - _h); as _vy grows the image moves down.
            # At _vy=0 image is fully above screen; visible when 0 <= img_y < _h.
            img_y = int(cy - self._vy + self._h)
            if img_y < 0 or img_y >= self._h:
                continue
            for cx in range(PANEL_SIZE):
                ccol = self._col0 + cx
                if 0 <= ccol < CROSS_W and CROSS_MASK[cy, ccol]:
                    buf[cy, ccol] = self._px[img_y * PANEL_SIZE + cx]

# ===========================================================================
# Meteor Shower
# ===========================================================================

class MeteorShower(Animation):
    """
    Bright meteors streak diagonally across panels, each leaving a
    glowing, fading tail. New meteors spawn at the top of the cross.
    """

    MAX_METEORS = 20
    SPAWN_RATE  = 3.0   # per second

    def __init__(self, canvas):
        super().__init__(canvas)
        self.meteors      = []
        self._next_spawn  = 0.0

    def _spawn(self):
        angle  = random.uniform(math.pi * 0.55, math.pi * 0.95)  # mostly downward-right
        speed  = random.uniform(14, 28)
        length = random.randint(10, 25)
        hue    = random.uniform(0.0, 0.15)   # warm white-yellow-orange
        # Start anywhere along the top edge of the bounding box
        sx = random.uniform(CROSS_MIN_X, CROSS_MIN_X + CROSS_W)
        sy = float(CROSS_MIN_Y)
        self.meteors.append({
            "x": sx, "y": sy,
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "length": length, "hue": hue,
            "trail": [],
        })

    def draw(self):
        c = self.canvas
        c.clear()
        dt = 1.0 / FPS

        if self.t >= self._next_spawn and len(self.meteors) < self.MAX_METEORS:
            self._spawn()
            self._next_spawn = self.t + 1.0 / self.SPAWN_RATE + random.uniform(-0.1, 0.2)

        for m in self.meteors[:]:
            m["x"] += m["vx"] * dt
            m["y"] += m["vy"] * dt
            m["trail"].append((m["x"], m["y"]))
            if len(m["trail"]) > m["length"]:
                m["trail"].pop(0)

            # Remove if fully off canvas
            if (m["x"] > CROSS_MIN_X + CROSS_W + 10 or
                m["y"] > CROSS_MIN_Y + CROSS_H + 10):
                self.meteors.remove(m)
                continue

            hue = m["hue"]
            n   = len(m["trail"])
            for j, (tx, ty) in enumerate(m["trail"]):
                frac = (j + 1) / n
                v    = frac ** 1.4
                sat  = 1.0 - frac * 0.6   # head is whiter
                c.set(tx, ty, *self.hsv(hue, sat, v))

            # Bright head glow
            hx, hy = m["trail"][-1]
            for dy in (-0.5, 0.5):
                for dx in (-0.5, 0.5):
                    c.set(hx + dx, hy + dy, *self.hsv(hue, 0.1, 1.0))


ANIMATIONS = [
    ("Plasma",            Plasma),
    ("Expanding Circles", ExpandingCircles),
    ("Rainbow Flow",      RainbowFlow),
    ("PPM Scroll H",      PPMScrollH),
    ("PPM Scroll V",      PPMScrollV),
    ("SpinningABC",      SpinningABC),
    ("TwisterSpiral",      TwisterSpiral),
    ("MeteorShower",      MeteorShower),

]


class AnimationRunner:
    def __init__(self, cycle_seconds=4):
        self.canvas        = CrossCanvas()
        self.driver        = MatrixDriver()
        self.cycle_seconds = cycle_seconds
        self._anim         = None
        self._anim_idx     = 0

    def _load(self, idx):
        name, cls = ANIMATIONS[idx % len(ANIMATIONS)]
        print(f"  ► {name}")
        self._anim = cls(self.canvas)

    def run(self, animation_name=None):
        if animation_name:
            idx = next((i for i, (n, _) in enumerate(ANIMATIONS)
                        if n.lower() == animation_name.lower()), 0)
            self._load(idx)
            cycle = False
        else:
            self._load(0)
            cycle = True

        dt          = 1.0 / FPS

        last_switch = time.time()
        print("Running — Ctrl+C to exit.\n")

        try:
            while True:
                start = time.time()

                if cycle and (start - last_switch) >= self.cycle_seconds:
                    self._anim_idx += 1
                    self._load(self._anim_idx)
                    last_switch = start

                self._anim.tick(dt)
                self.canvas.apply_mask()
                self.driver.show(self.canvas)

                elapsed = time.time() - start
                time.sleep(max(0.0, dt - elapsed))

        except KeyboardInterrupt:
            print("\nStopped.")
        finally:
            self.canvas.clear()
            self.driver.show(self.canvas)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import os
    import sys

    # Resolve paths relative to the script's own directory, not the CWD.
    # This matters when running under sudo, which may use a different CWD.
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

    names = [n for n, _ in ANIMATIONS]
    parser = argparse.ArgumentParser(description="LED Cross Animation Suite")
    parser.add_argument("--animation", "-a", choices=names, default=None,
                        help="Run one animation. Omit to cycle through all.")
    parser.add_argument("--cycle-seconds", "-c", type=int, default=7,
                        help="Seconds per animation when cycling (default 4).")
    parser.add_argument("--brightness", "-b", type=float, default=BRIGHTNESS,
                        metavar="0.0-1.0",
                        help=f"Global brightness 0.0–1.0 (default {BRIGHTNESS}).")
    parser.add_argument("--image", "-i", default=None,
                        help="Path to horizontal PPM image for 'PPM Scroll H'.")
    parser.add_argument("--image-v", default=None,
                        help="Path to vertical PPM image for 'PPM Scroll V'.")
    parser.add_argument("--ppm-speed", "-s", type=float, default=None,
                        metavar="PIXELS/SEC",
                        help="PPM scroll speed in pixels per second (default 40).")
    args = parser.parse_args()

    _mod = sys.modules[__name__]
    _mod.BRIGHTNESS = max(0.0, min(1.0, args.brightness))
    print(f"Brightness: {_mod.BRIGHTNESS:.0%}")

    if args.ppm_speed is not None:
        PPMScrollH.SPD = args.ppm_speed
        PPMScrollV.SPD = args.ppm_speed

    if args.image:
        PPMScrollH.IMAGE_PATH = args.image if os.path.isabs(args.image) \
                                else os.path.join(SCRIPT_DIR, args.image)
    else:
        #PPMScrollH.IMAGE_PATH = os.path.join(SCRIPT_DIR, "image.ppm")
        PPMScrollH.IMAGE_PATH = "hello.ppm"
    if args.image_v:
        PPMScrollV.IMAGE_PATH = args.image_v if os.path.isabs(args.image_v) \
                                else os.path.join(SCRIPT_DIR, args.image_v)
    else:
        #PPMScrollV.IMAGE_PATH = os.path.join(SCRIPT_DIR, "image_v.ppm")
        PPMScrollV.IMAGE_PATH = "world.ppm"

    if args.animation == "PPM Scroll H" and not os.path.exists(PPMScrollH.IMAGE_PATH):
        print(f"Error: PPM not found at '{PPMScrollH.IMAGE_PATH}'")
        print("Use --image to specify the path.")
        sys.exit(1)

    if args.animation == "PPM Scroll V" and not os.path.exists(PPMScrollV.IMAGE_PATH):
        print(f"Error: PPM not found at '{PPMScrollV.IMAGE_PATH}'")
        print("Use --image-v to specify the path.")
        sys.exit(1)

    runner = AnimationRunner(cycle_seconds=args.cycle_seconds)
    runner.run(animation_name=args.animation)
