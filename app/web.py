from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from app.config import load_config
from app.service import PoolService


def create_app(base_dir: Path) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    config_path = base_dir / "data" / "pool_config.json"
    if not config_path.exists():
        config_path = base_dir / "data" / "pool_config.example.json"
    config = load_config(config_path)
    service = PoolService(base_dir=base_dir, config=config)
    cron_secret = os.getenv("MASTERS_POOL_CRON_SECRET", "").strip() or os.getenv("CRON_SECRET", "").strip()

    @app.get("/")
    def index() -> str:
        state = service.get_state()
        if not state:
            try:
                state = service.poll_once()
            except Exception:  # noqa: BLE001
                state = {}
        return render_template("index.html", state=state, config=config)

    @app.get("/api/state")
    def api_state():
        state = service.get_state()
        if not state:
            try:
                state = service.poll_once()
            except Exception:  # noqa: BLE001
                state = {}
        return jsonify(state)

    @app.get("/api/cron/poll")
    def api_cron_poll():
        if cron_secret:
            auth_header = request.headers.get("Authorization", "")
            expected = f"Bearer {cron_secret}"
            if auth_header != expected:
                return jsonify({"error": "unauthorized"}), 401
        try:
            state = service.poll_once()
            return jsonify({"ok": True, "updatedAt": state.get("updatedAt")})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 500

    return app

