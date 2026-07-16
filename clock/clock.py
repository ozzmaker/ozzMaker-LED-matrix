#!/usr/bin/env python3
"""Negative-style digital clock for an OzzMaker 80x16 RGB LED matrix.

Runs the render loop (which owns the panels) and a Flask web control panel in one
process. On the Pi this needs root for GPIO access:

    sudo python3 clock.py
    
Feel free to do whatever you like with this code.
Distributed as-is; no warranty is given.

OzzMaker.com
"""

import argparse
import os
import threading

import renderer
import webapp
from settings_store import Settings, Status, Control

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(HERE, "settings.json")


def main():
    parser = argparse.ArgumentParser(description="LED matrix negative clock + web control")
    parser.add_argument("--fast", action="store_true",
                        help="cycle colors every few seconds (to preview transitions)")
    parser.add_argument("--port", type=int, default=8080,
                        help="web control panel port (default 8080)")
    parser.add_argument("--no-web", action="store_true",
                        help="run the clock only, without the web control panel")
    args = parser.parse_args()

    settings = Settings(SETTINGS_PATH)
    status = Status()
    control = Control()

    render_thread = threading.Thread(
        target=renderer.run,
        args=(settings, status, control),
        kwargs={"fast": args.fast},
        daemon=True,
    )
    render_thread.start()

    if args.no_web:
        render_thread.join()
        return

    app = webapp.create_app(settings, status, control)
    # load_dotenv=False skips Flask's .env lookup (we don't use one, and the lookup
    # can fail depending on the working directory / privileges).
    app.run(host="0.0.0.0", port=args.port, threaded=True, use_reloader=False,
            load_dotenv=False)


if __name__ == "__main__":
    main()
