from __future__ import annotations

import unittest

from app.espn_client import extract_competition_meta, extract_masters_field_leaderboard_top


class TestCompetitionThru(unittest.TestCase):
    def test_thru_dash_when_current_period_not_started(self) -> None:
        """Round 3 is official period but no hole scores yet → not \"F\" from yesterday's 18."""
        inner18 = [{"period": i, "displayValue": "4", "value": 4.0} for i in range(1, 19)]
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
        self.assertEqual(rows[0]["thru"], "--")

    def test_thru_final_when_current_period_complete(self) -> None:
        inner18 = [{"period": i, "displayValue": "4", "value": 4.0} for i in range(1, 19)]
        payload = {
            "events": [
                {
                    "competitions": [
                        {
                            "status": {
                                "period": 2,
                                "type": {"state": "in", "name": "STATUS_IN_PROGRESS"},
                            },
                            "competitors": [
                                {
                                    "id": "7",
                                    "score": "-4",
                                    "athlete": {"displayName": "P2"},
                                    "linescores": [
                                        {"period": 1, "displayValue": "-2", "linescores": inner18},
                                        {"period": 2, "displayValue": "-2", "linescores": inner18},
                                    ],
                                }
                            ],
                        }
                    ]
                }
            ]
        }
        rows = extract_masters_field_leaderboard_top(payload, limit=10)
        self.assertEqual(rows[0]["thru"], "F")


class TestPoolThroughDisplay(unittest.TestCase):
    def test_shows_dash_when_pulse_on_prior_round(self) -> None:
        from app.service import _through_display

        self.assertEqual(
            _through_display(2, 18, "IN PROGRESS", {"period": 3, "typeState": "pre"}),
            "--",
        )


class TestPenaltyStatus(unittest.TestCase):
    def test_is_penalty_status_cut_and_made_cut(self) -> None:
        from app.scoring import is_penalty_status

        self.assertTrue(is_penalty_status("CUT"))
        self.assertTrue(is_penalty_status("MISSED CUT"))
        self.assertFalse(is_penalty_status("MADE CUT"))
        self.assertFalse(is_penalty_status("PROJECTED CUT"))

