from __future__ import annotations

import os
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from app.config import load_runtime_config
from app.scoring import DAILY_WINNER_BONUS_DOLLARS
from app.service import PoolService


def create_app(base_dir: Path) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates"),
        static_folder=str(base_dir / "static"),
    )
    config = load_runtime_config(base_dir)
    service = PoolService(base_dir=base_dir, config=config)
    cron_secret = os.getenv("MASTERS_POOL_CRON_SECRET", "").strip() or os.getenv("CRON_SECRET", "").strip()
    # Throttle ESPN polls triggered by browser /api/state (matches 5-minute client refresh).
    _api_state_poll_interval_sec = 300.0
    _last_api_state_poll_mono: list[float] = [-1e18]

    @app.get("/")
    def index() -> str:
        state = service.get_state()
        if not state:
            try:
                state = service.poll_once()
            except Exception:  # noqa: BLE001
                state = {}
        return render_template(
            "index.html",
            state=state,
            config=config,
            daily_winner_bonus_dollars=DAILY_WINNER_BONUS_DOLLARS,
        )

    @app.get("/api/state")
    def api_state():
        now = time.monotonic()
        if now - _last_api_state_poll_mono[0] >= _api_state_poll_interval_sec:
            _last_api_state_poll_mono[0] = now
            try:
                service.poll_once()
            except Exception:  # noqa: BLE001
                pass
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

