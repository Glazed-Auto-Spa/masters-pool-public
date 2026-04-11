from __future__ import annotations

import unittest

from app.espn_client import (
    extract_competition_meta,
    extract_masters_field_leaderboard_top,
    format_tee_time_phoenix_from_stat_display,
)
from app.scoring import format_pick_status_display, is_penalty_status


class TestTeeTimePhoenix(unittest.TestCase):
    def test_parses_pdt_to_az_suffix(self) -> None:
        out = format_tee_time_phoenix_from_stat_display("Sat Apr 11 14:50:00 PDT 2026")
        self.assertIsNotNone(out)
        self.assertIn("AZ", out or "")
        self.assertIn("2:50", out or "")


class TestMastersThruWithTee(unittest.TestCase):
    def test_shows_tee_when_current_round_not_started(self) -> None:
        inner18 = [{"period": i, "displayValue": "4", "value": 4.0} for i in range(1, 19)]
        tee_raw = "Sat Apr 11 14:50:00 PDT 2026"
        stats = {"categories": [{"stats": [{"displayValue": "0"}, {"displayValue": tee_raw}]}]}
        payload = {
            "events": [
                {
                    "competitions": [
                        {
                            "status": {
                                "period": 3,
                                "type": {"state": "pre", "name": "STATUS_SCHEDULED", "detail": "Round 3"},
                            },
                            "competitors": [
                                {
                                    "id": "99",
                                    "score": "-8",
                                    "athlete": {"displayName": "Leader"},
                                    "linescores": [
                                        {"period": 1, "displayValue": "-4", "linescores": inner18},
                                        {"period": 2, "displayValue": "-4", "linescores": inner18},
                                        {
                                            "period": 3,
                                            "displayValue": "-",
                                            "linescores": [],
                                            "statistics": stats,
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        meta = extract_competition_meta(payload)
        self.assertEqual(meta.get("period"), 3)
        rows = extract_masters_field_leaderboard_top(payload, limit=10)
        self.assertNotEqual(rows[0]["thru"], "--")
        self.assertIn("AZ", rows[0]["thru"])


class TestStatusCutAndDisplay(unittest.TestCase):
    def test_status_cut_is_penalty(self) -> None:
        self.assertTrue(is_penalty_status("STATUS_CUT MISSED CUT"))

    def test_format_pick_status_display_short(self) -> None:
        self.assertEqual(format_pick_status_display("MISSED CUT CUT STATUS_CUT"), "MC")
        self.assertEqual(format_pick_status_display(""), "—")
        self.assertEqual(format_pick_status_display("IN PROGRESS"), "Live")


if __name__ == "__main__":
    unittest.main()
