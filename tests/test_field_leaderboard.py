from __future__ import annotations

import unittest

from app.espn_client import extract_masters_field_leaderboard_top


class TestFieldLeaderboard(unittest.TestCase):
    def test_top_ten_sorted_and_ties(self) -> None:
        payload = {
            "events": [
                {
                    "competitions": [
                        {
                            "competitors": [
                                {
                                    "id": "3",
                                    "score": "-4",
                                    "athlete": {"displayName": "Leader"},
                                    "linescores": [
                                        {
                                            "period": 1,
                                            "displayValue": "-4",
                                            "linescores": [
                                                {"period": i, "displayValue": "4", "value": 4.0} for i in range(1, 19)
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "id": "2",
                                    "score": "-4",
                                    "athlete": {"displayName": "Tied"},
                                    "linescores": [
                                        {
                                            "period": 1,
                                            "displayValue": "-4",
                                            "linescores": [
                                                {"period": i, "displayValue": "4", "value": 4.0} for i in range(1, 19)
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "id": "1",
                                    "score": "E",
                                    "athlete": {"displayName": "Even"},
                                    "linescores": [
                                        {
                                            "period": 1,
                                            "displayValue": "E",
                                            "linescores": [{"period": 1, "displayValue": "4", "value": 4.0}],
                                        }
                                    ],
                                },
                            ]
                        }
                    ]
                }
            ]
        }
        rows = extract_masters_field_leaderboard_top(payload, limit=10)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["pos"], "T1")
        self.assertEqual(rows[1]["pos"], "T1")
        self.assertEqual(rows[0]["toPar"], -4)
        self.assertEqual(rows[2]["pos"], "3")
        self.assertEqual(rows[2]["name"], "Even")
        self.assertEqual(rows[2]["scoreDisplay"], "E")
        sc0 = rows[0].get("scorecard")
        self.assertIsNotNone(sc0)
        self.assertEqual(sc0.get("round"), 1)
        self.assertEqual(len(sc0.get("holes", [])), 18)
        self.assertEqual(sc0.get("total"), 18 * 4)
        sc2 = rows[2].get("scorecard")
        self.assertIsNotNone(sc2)
        self.assertEqual(sc2.get("total"), 4)

    def test_empty_events(self) -> None:
        self.assertEqual(extract_masters_field_leaderboard_top({}, limit=10), [])
        self.assertEqual(extract_masters_field_leaderboard_top({"events": []}, limit=10), [])
