More information here https://ozzmaker.com/build-a-pixel-art-led-matrix-clock-3d-printed-diffuser-and-a-web-app/

# Negative-style LED matrix clock

A digital clock for **four OzzMaker 16×16 RGB LED panels** chained into one
**64 × 16** display, driven by a Raspberry Pi. The time (`HH:MM`) is shown as a
**negative image**: the digits are unlit (off) while the rest of the field is lit.
The lit background **cycles through a pastel palette** with an animated transition,
and a small **web control panel** lets you tune everything live.


![OzzMaker 16x16 RGB LED matrix ]( https://ozzmaker.com/wp-content/uploads/2026/07/clockFeature2.jpg "OzzMaker 16x16 RGB LED matrix")


## What it does

- 64×16 canvas (4 × 16×16 panels chained left→right).
- Negative rendering: background fully lit, digits/colon drawn black (off).
- Colon blinks once per second (toggleable).
- Optional **seconds bar**: a thin dark bar along the bottom edge that sweeps across once
  per minute. While it's on, the digits shrink slightly so the bar stays clearly separated.
- Background cycles through an editable pastel palette, **once an hour** by default
  (per-minute also available).
- Transitions between colors: **fade** (default), **instant**, **diagonal swipe
  (left→right)**, **vertical wipe (top→bottom)**, or **random**. The swipe/wipe
  boundary blends old→new across a soft gradient band.
- Selectable **animated backgrounds** (panel dropdown): solid cycling color, **plasma**,
  **aurora**, **lava lamp**, **clouds**, **twinkle**, **ripples**, **spiral**, **scanner**
  (a single-hue comet that fades on both sides, sweeping edge to edge on black) — all
  colored by your palette, with the negative time drawn on top.
- Optional **flourishes** (combine with any background): **breathing** (slow brightness
  pulse), **minute sparkle** (shimmer when the minute changes), and **time-of-day tint**
  (warmer in the evening, cooler in the morning).
- Web control panel at `http://<pi-ip>:8080` (open on the LAN, no login) with a
  live preview. All changes persist to `settings.json` and survive reboots.
- Time format is display-only (12/24h, leading zero, colon blink); the Pi keeps
  accurate time itself via NTP.

## Files

| File | Purpose |
|------|---------|
| `clock.py` | Entry point: starts the render thread + web server. |
| `renderer.py` | Matrix setup, 7-segment digits, background cycling + transitions, render loop. |
| `settings_store.py` | Thread-safe, validated, persisted settings + live status. |
| `webapp.py` | Flask routes / JSON API. |
| `templates/index.html` | The web control panel (HTML + vanilla JS). |
| `settings.json` | Created at runtime; your saved settings. |
| `clock.service` | Optional systemd unit for auto-start on boot. |

## Wiring

Raspberry Pi → OzzMaker LED Connector HAT → first panel's **IN**. Then chain panel
**OUT → IN** for all four, left to right. Power the panels per OzzMaker's guide.

## One-time Raspberry Pi setup

```bash
# 1. Disable onboard sound (it conflicts with the matrix timing)
echo "blacklist snd_bcm2835" | sudo tee /etc/modprobe.d/blacklist-rgb-matrix.conf
sudo update-initramfs -u
sudo reboot

# 2. Build hzeller's rpi-rgb-led-matrix library (Python bindings)
sudo apt-get update && sudo apt-get install -y python3-dev cython3
curl -L https://github.com/hzeller/rpi-rgb-led-matrix/archive/7a503494378a67f3baa4ac680cecbae2703cc58f.zip -o rpi-rgb-led-matrix.zip
unzip rpi-rgb-led-matrix.zip
mv rpi-rgb-led-matrix-7a503494378a67f3baa4ac680cecbae2703cc58f rpi-rgb-led-matrix
cd rpi-rgb-led-matrix && make build-python && sudo make install-python && cd ..

# 3. Install Flask for the web control panel
sudo pip3 install flask
```

## Run

```bash
sudo python3 clock.py          # GPIO access needs root
```

Find the Pi's IP (`hostname -I`) and open `http://<pi-ip>:8080` from any device on
your network.

**Flicker on a Pi 4?** Uncomment `options.gpio_slowdown = 2` in `renderer.py`
(`_make_matrix`); try 2–4.

**A panel looks mirrored / upside-down?** The chain direction is reversed — flip
the physical order, or add a pixel-mapper rotation in `_make_matrix`.


## Auto-start on boot (optional)

Edit the paths in `clock.service` if your checkout isn't at `/home/pi/clock`, then:

```bash
sudo cp clock.service /etc/systemd/system/clock.service
sudo systemctl enable --now clock.service
```

## Controls / settings reference

All live-editable from the panel and stored in `settings.json`:

| Setting | Values | Default |
|---------|--------|---------|
| `brightness` | 0–100 | 60 |
| `display_on` | true/false | true |
| `time_format` | `24h` / `12h` | `24h` |
| `leading_zero` | true/false | true |
| `colon_blink` | true/false | true |
| `seconds_bar` | true/false — dark progress bar along the bottom showing seconds | true |
| `background_mode` | `color` / `plasma` / `aurora` / `metaballs` / `clouds` / `twinkle` / `ripples` / `spiral` / `scanner` | `color` |
| `breathing` | true/false (slow brightness pulse) | false |
| `sparkle` | true/false (shimmer on minute change) | false |
| `tod_tint` | true/false (warm/cool by time of day) | false |
| `palette` | list of `#rrggbb` (≥1) | 8 pastels |
| `color_order` | `sequential` / `random` | `sequential` |
| `change_rate` | `hour` / `minute` | `hour` |
| `fast` | true/false — cycle colors every few seconds (preview transitions) | false |
| `transition` | `fade`/`instant`/`swipe_diagonal`/`wipe_vertical`/`random` | `fade` |
| `transition_duration` | seconds (0–10) | 1.2 |
