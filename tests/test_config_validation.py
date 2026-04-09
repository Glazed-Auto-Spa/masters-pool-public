from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.config import load_config


class TestConfigValidation(unittest.TestCase):
    def test_rejects_duplicate_participant_names(self) -> None:
        config_data = {
            "event_id": "401811941",
            "participants": [
                {"name": "Same", "predictedWinningToPar": -10, "picks": [1, 2, 3, 4, 5, 6, 7, 8]},
                {"name": "Same", "predictedWinningToPar": -9, "picks": [9, 10, 11, 12, 13, 14, 15, 16]},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "pool_config.json"
            file_path.write_text(json.dumps(config_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate participant name"):
                load_config(file_path)

    def test_rejects_wrong_pick_count(self) -> None:
        config_data = {
            "event_id": "401811941",
            "participants": [
                {"name": "A", "predictedWinningToPar": -10, "picks": [1, 2, 3]},
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "pool_config.json"
            file_path.write_text(json.dumps(config_data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must have exactly 8 picks"):
                load_config(file_path)


if __name__ == "__main__":
    unittest.main()
