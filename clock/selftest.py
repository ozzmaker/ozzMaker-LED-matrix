"""Off-hardware sanity checks for the rendering and settings logic.

Run on any machine (no panels, no Flask, no root):

    python3 selftest.py

Prints sample clock frames as ASCII ('#' = unlit digit/colon, '.' = lit field)
so the digit shapes can be eyeballed, and asserts a few invariants.
"""

from datetime import datetime
from types import SimpleNamespace

import renderer
from settings_store import DEFAULTS, WIDTH, HEIGHT, validate_patch


def snap(**overrides):
    data = dict(DEFAULTS)
    data.update(overrides)
    return SimpleNamespace(**data)


def show(label, now, **overrides):
    s = snap(**overrides)
    bg = renderer.BackgroundManager(s.palette)
    frame = renderer.compose(bg, s, now, brightness=100)
    print("\n%s  (%s, leading_zero=%s)" % (label, s.time_format, s.leading_zero))
    print(renderer.frame_to_ascii(frame))
    return frame


def main():
    assert len(renderer.Frame().buf) == WIDTH * HEIGHT

    show("06:19", datetime(2026, 6, 19, 6, 19, 0))
    show("23:59", datetime(2026, 6, 19, 23, 59, 0))
    show("00:00", datetime(2026, 1, 1, 0, 0, 0))
    show("12h 9:05", datetime(2026, 6, 19, 9, 5, 0), time_format="12h", leading_zero=False)

    # Colon blinks: the two half-seconds must differ.
    s = snap()
    bg = renderer.BackgroundManager(s.palette)
    on = renderer.frame_to_ascii(renderer.compose(bg, s, datetime(2026, 6, 19, 6, 19, 0, 100000), brightness=100))
    off = renderer.frame_to_ascii(renderer.compose(bg, s, datetime(2026, 6, 19, 6, 19, 0, 800000), brightness=100))
    assert on != off, "colon should differ between the two half-seconds"
    assert on.count("#") > off.count("#"), "colon present in the first half-second"

    # Every transition style paints a full frame without error, mid-animation.
    for style in ("fade", "instant", "swipe_diagonal", "wipe_vertical"):
        s2 = snap(transition=style, transition_duration=1.0)
        bg2 = renderer.BackgroundManager(s2.palette)
        bg2.advance(s2)
        frame = renderer.Frame()
        mid = bg2.transition["start"] + 0.5 if bg2.transition else None
        bg2.paint(frame, 100, now_mono=mid)
        assert len(frame.buf) == WIDTH * HEIGHT
        # The swipe/wipe boundary should be a soft gradient, not a hard 2-color edge.
        if style in ("swipe_diagonal", "wipe_vertical"):
            distinct = len(set(frame.buf))
            assert distinct > 2, "%s should blend a gradient band, got %d colors" % (style, distinct)

    # The clock is centered: "00:00" (symmetric digits) renders left/right symmetric.
    bgc = renderer.BackgroundManager(snap().palette)
    zeros = renderer.compose(bgc, snap(), datetime(2026, 6, 19, 0, 0, 0, 100000), brightness=100)
    assert all(zeros.buf[y * WIDTH + x] == zeros.buf[y * WIDTH + (WIDTH - 1 - x)]
               for y in range(HEIGHT) for x in range(WIDTH)), "00:00 should render centered/symmetric"

    # Every background generator renders varied colors and animates over time.
    pal = snap().palette
    generators = [
        ("plasma", renderer.PlasmaField()),
        ("aurora", renderer.AuroraField()),
        ("metaballs", renderer.MetaballsField()),
        ("clouds", renderer.CloudsField()),
        ("twinkle", renderer.TwinkleField()),
        ("ripples", renderer.RippleField()),
        ("spiral", renderer.SpiralField()),
    ]

    # Scanner: a single-hue comet with a fading trail on an otherwise-black field.
    sc = renderer.ScannerField()
    sa = renderer.Frame(); sc.paint(sa, 0.2, pal, 100)
    sb = renderer.Frame(); sc.paint(sb, 0.6, pal, 100)
    lit_a = [i for i, px in enumerate(sa.buf) if px != (0, 0, 0)]
    assert 0 < len(lit_a) < WIDTH * HEIGHT // 2, "scanner should be a comet on a mostly-black field"
    assert len({sa.buf[i] for i in lit_a}) > 3, "the trail should fade (a gradient of one hue)"
    cols_a = {i % WIDTH for i in lit_a}
    cols_b = {i % WIDTH for i, px in enumerate(sb.buf) if px != (0, 0, 0)}
    assert cols_a and cols_b and cols_a != cols_b, "scanner comet should sweep across over time"
    # fades on both sides of the head (leading glow + trailing tail)
    hx = max(lit_a, key=lambda i: sum(sa.buf[i])) % WIDTH
    assert any(c < hx for c in cols_a) and any(c > hx for c in cols_a), \
        "scanner should fade on both sides of the head"

    # Seconds bar: a bottom-row progress bar that grows through the minute.
    bgs = renderer.BackgroundManager(snap().palette)
    base = (HEIGHT - 1) * WIDTH

    def bottom_dark(sec, on=True):
        fr = renderer.compose(bgs, snap(seconds_bar=on), datetime(2026, 6, 19, 0, 0, sec, 0), brightness=100)
        return sum(1 for x in range(WIDTH) if fr.buf[base + x] == (0, 0, 0))
    assert bottom_dark(2) < bottom_dark(50), "seconds bar should grow as seconds increase"
    assert bottom_dark(50, on=False) == 0, "no bottom-row bar when seconds_bar is off"

    # With the bar on, digits shrink so rows 13-14 stay clear above it.
    when0 = datetime(2026, 6, 19, 0, 0, 0, 0)
    full = renderer.compose(bgs, snap(seconds_bar=False), when0, brightness=100)
    short = renderer.compose(bgs, snap(seconds_bar=True), when0, brightness=100)

    def dark_in(fr, rows):
        return any(fr.buf[y * WIDTH + x] == (0, 0, 0) for y in rows for x in range(WIDTH))
    assert dark_in(full, (13, 14)), "full-size digits should reach rows 13-14"
    assert not dark_in(short, (13, 14)), "compact digits should leave rows 13-14 clear above the bar"
    for name, gen in generators:
        a1 = renderer.Frame(); gen.paint(a1, 0.0, pal, 100)
        a2 = renderer.Frame(); gen.paint(a2, 1.7, pal, 100)
        assert len(set(a1.buf)) > 4, "%s should render several colors" % name
        assert a1.buf != a2.buf, "%s should animate over time" % name

    # Flourishes: breathing brightness, time-of-day tint, minute sparkle.
    breaths = [renderer._breathe(x * 0.3) for x in range(80)]
    assert min(breaths) < 0.3 and max(breaths) > 0.9, "breathing should swing wide and deep"
    dithered = renderer.Frame(); dithered.buf = [(101, 150, 200)] * (WIDTH * HEIGHT)
    renderer._apply_breath(dithered, 0.5)
    assert len(set(dithered.buf)) >= 2, "breathing should dither to avoid banding"
    warm = renderer._tod_factor(datetime(2026, 6, 19, 20, 0, 0))   # evening
    cool = renderer._tod_factor(datetime(2026, 6, 19, 8, 0, 0))    # morning
    assert warm[0] > warm[2], "evening tint should be warmer (more red than blue)"
    assert cool[2] > cool[0], "morning tint should be cooler (more blue than red)"
    tinted = renderer.Frame(); tinted.buf = [(100, 100, 100)] * (WIDTH * HEIGHT)
    renderer._apply_tint(tinted, (1.2, 1.0, 0.8))
    assert tinted.buf[0] == (120, 100, 80)
    sparkly = renderer.Frame()  # starts all black
    renderer._draw_sparkle(sparkly, 1.0, 100)
    assert any(px != (0, 0, 0) for px in sparkly.buf), "sparkle should brighten some pixels"

    # Sequential cycling wraps around the palette.
    s3 = snap()
    bg3 = renderer.BackgroundManager(s3.palette)
    seen = [bg3.index]
    for _ in range(len(s3.palette)):
        bg3.advance(s3)
        seen.append(bg3.index)
    assert seen[-1] == 0, "sequential order should wrap back to the start"

    # Settings validation: clamp, reject bad enums/colors.
    clean, errors = validate_patch({"brightness": 999, "transition": "nope",
                                    "palette": ["#fff", "zzz"]})
    assert clean["brightness"] == 100
    assert "palette" not in clean, "no valid colors -> palette rejected"
    assert any("transition" in e for e in errors)

    clean2, _ = validate_patch({"palette": ["#FFFFFF", "#000000"]})
    assert clean2["palette"] == ["#ffffff", "#000000"], "hex normalized to lowercase"

    print("\nALL CHECKS PASSED")


if __name__ == "__main__":
    main()
