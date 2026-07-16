"""Flask control panel + JSON API for the LED clock.

The web side only reads/writes the shared Settings (and reads Status); it never
touches the matrix, which is owned solely by the render thread.

Feel free to do whatever you like with this code.
Distributed as-is; no warranty is given.

OzzMaker.com
"""

import logging

from flask import Flask, jsonify, render_template, request


def create_app(settings, status, control):
    app = Flask(__name__)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # keep the console quiet

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/api/settings")
    def get_settings():
        return jsonify(settings.as_dict())

    @app.post("/api/settings")
    def post_settings():
        patch = request.get_json(force=True, silent=True) or {}
        errors = settings.update(patch)
        return jsonify({"ok": not errors, "errors": errors, "settings": settings.as_dict()})

    @app.get("/api/status")
    def get_status():
        return jsonify(status.status())

    @app.get("/api/frame")
    def get_frame():
        return jsonify(status.frame())

    @app.post("/api/next-color")
    def next_color():
        control.request_next()
        return jsonify({"ok": True})

    @app.post("/api/reset")
    def reset():
        settings.reset()
        return jsonify({"ok": True, "settings": settings.as_dict()})

    return app
