from __future__ import annotations

import unittest

from app.config import ParticipantConfig, PoolConfig
from app.scoring import _compute_side_nets, score_participants


class TestScoringPayouts(unittest.TestCase):
    def test_side_nets_zero_when_all_equal(self) -> None:
        self.assertEqual(_compute_side_nets([10, 10, 10, 10]), [0.0, 0.0, 0.0, 0.0])

    def test_side_nets_split_single_streak_bonus_across_group(self) -> None:
        actual = _compute_side_nets([10, 0, 0, 0, 0, 0])
        self.assertEqual(actual, [10.0, -2.0, -2.0, -2.0, -2.0, -2.0])

    def test_main_event_pot_only_assigned_to_first_place(self) -> None:
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="Leader", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
                ParticipantConfig(name="Second", predicted_winning_to_par=9, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
            ],
        )

        scored = score_participants(config=config, snapshots={}, winning_to_par=0)
        leaderboard = scored["leaderboard"]

        self.assertEqual(leaderboard[0]["name"], "Leader")
        self.assertEqual(leaderboard[0]["mainEventPayoutDollars"], 50)
        self.assertEqual(leaderboard[1]["mainEventPayoutDollars"], 0)
        self.assertAlmostEqual(sum(row["netPayoutDollars"] for row in leaderboard), 0.0, places=6)


if __name__ == "__main__":
    unittest.main()
