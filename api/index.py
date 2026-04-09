from __future__ import annotations

from pathlib import Path

from app.web import create_app

BASE_DIR = Path(__file__).resolve().parents[1]
app = create_app(base_dir=BASE_DIR)
