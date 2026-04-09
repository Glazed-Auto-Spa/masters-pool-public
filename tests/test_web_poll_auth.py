from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.service import PoolService
from app.web import create_app


class TestWebRoutes(unittest.TestCase):
    def test_poll_endpoint_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            data_dir = base / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            config = {
                "event_id": "401811941",
                "participants": [
                    {
                        "name": "Tester",
                        "predictedWinningToPar": -10,
                        "picks": [1, 2, 3, 4, 5, 6, 7, 8],
                    }
                ],
            }
            (data_dir / "pool_config.json").write_text(json.dumps(config), encoding="utf-8")

            app = create_app(base_dir=base)
            client = app.test_client()
            response = client.post("/api/poll")

            self.assertEqual(response.status_code, 404)

    def test_cron_endpoint_requires_secret_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            data_dir = base / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            config = {
                "event_id": "401811941",
                "participants": [
                    {
                        "name": "Tester",
                        "predictedWinningToPar": -10,
                        "picks": [1, 2, 3, 4, 5, 6, 7, 8],
                    }
                ],
            }
            (data_dir / "pool_config.json").write_text(json.dumps(config), encoding="utf-8")

            original_secret = os.environ.get("MASTERS_POOL_CRON_SECRET")
            os.environ["MASTERS_POOL_CRON_SECRET"] = "secret123"
            try:
                app = create_app(base_dir=base)
                client = app.test_client()
                response = client.get("/api/cron/poll")
                self.assertEqual(response.status_code, 401)
            finally:
                if original_secret is None:
                    os.environ.pop("MASTERS_POOL_CRON_SECRET", None)
                else:
                    os.environ["MASTERS_POOL_CRON_SECRET"] = original_secret

    def test_cron_endpoint_runs_poll_when_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            data_dir = base / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            config = {
                "event_id": "401811941",
                "participants": [
                    {
                        "name": "Tester",
                        "predictedWinningToPar": -10,
                        "picks": [1, 2, 3, 4, 5, 6, 7, 8],
                    }
                ],
            }
            (data_dir / "pool_config.json").write_text(json.dumps(config), encoding="utf-8")

            original_secret = os.environ.get("MASTERS_POOL_CRON_SECRET")
            os.environ["MASTERS_POOL_CRON_SECRET"] = "secret123"
            try:
                app = create_app(base_dir=base)
                client = app.test_client()
                with patch.object(PoolService, "poll_once", return_value={"updatedAt": "now"}):
                    response = client.get(
                        "/api/cron/poll",
                        headers={"Authorization": "Bearer secret123"},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"ok": True, "updatedAt": "now"})
            finally:
                if original_secret is None:
                    os.environ.pop("MASTERS_POOL_CRON_SECRET", None)
                else:
                    os.environ["MASTERS_POOL_CRON_SECRET"] = original_secret


if __name__ == "__main__":
    unittest.main()
