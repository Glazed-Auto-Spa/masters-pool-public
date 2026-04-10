from __future__ import annotations

import unittest

from app.config import ParticipantConfig, PoolConfig
from app.models import HoleResult, PlayerRound, PlayerSnapshot
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

    def test_daily_winner_bonus_awards_and_flows_into_side_net(self) -> None:
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="A", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
                ParticipantConfig(name="B", predicted_winning_to_par=5, picks=[9, 10, 11, 12, 13, 14, 15, 16]),
            ],
        )

        snapshots: dict[int, PlayerSnapshot] = {}
        for player_id in range(1, 9):
            snapshots[player_id] = PlayerSnapshot(
                player_id=player_id,
                player_name=f"A{player_id}",
                status="OK",
                rounds={
                    1: PlayerRound(round_number=1, to_par=0, holes=[HoleResult(1, 1, "PAR", 4, 4)]),
                    2: PlayerRound(round_number=2, to_par=0, holes=[HoleResult(2, 1, "PAR", 4, 4)]),
                    3: PlayerRound(round_number=3, to_par=0, holes=[HoleResult(3, 1, "PAR", 4, 4)]),
                    4: PlayerRound(round_number=4, to_par=0, holes=[HoleResult(4, 1, "PAR", 4, 4)]),
                },
                total_to_par=0,
            )
        for player_id in range(9, 17):
            snapshots[player_id] = PlayerSnapshot(
                player_id=player_id,
                player_name=f"B{player_id}",
                status="OK",
                rounds={
                    1: PlayerRound(round_number=1, to_par=1, holes=[HoleResult(1, 1, "PAR", 5, 4)]),
                    2: PlayerRound(round_number=2, to_par=1, holes=[HoleResult(2, 1, "PAR", 5, 4)]),
                    3: PlayerRound(round_number=3, to_par=1, holes=[HoleResult(3, 1, "PAR", 5, 4)]),
                    4: PlayerRound(round_number=4, to_par=1, holes=[HoleResult(4, 1, "PAR", 5, 4)]),
                },
                total_to_par=4,
            )

        scored = score_participants(config=config, snapshots=snapshots, winning_to_par=0)
        leaderboard = scored["leaderboard"]

        self.assertEqual(leaderboard[0]["name"], "A")
        self.assertEqual(leaderboard[0]["dailyWinnerBonusDollars"], 200)
        self.assertEqual(leaderboard[0]["dailyWinnerDays"], [1, 2, 3, 4])
        self.assertEqual(leaderboard[1]["dailyWinnerBonusDollars"], 0)
        self.assertEqual(leaderboard[1]["dailyWinnerDays"], [])
        self.assertAlmostEqual(sum(row["netPayoutDollars"] for row in leaderboard), 0.0, places=6)

    def test_daily_winner_bonus_does_not_include_future_days(self) -> None:
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="A", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
                ParticipantConfig(name="B", predicted_winning_to_par=5, picks=[9, 10, 11, 12, 13, 14, 15, 16]),
            ],
        )

        snapshots: dict[int, PlayerSnapshot] = {}
        for player_id in range(1, 9):
            snapshots[player_id] = PlayerSnapshot(
                player_id=player_id,
                player_name=f"A{player_id}",
                status="OK",
                rounds={
                    1: PlayerRound(round_number=1, to_par=0, holes=[]),
                },
                total_to_par=0,
            )
        for player_id in range(9, 17):
            snapshots[player_id] = PlayerSnapshot(
                player_id=player_id,
                player_name=f"B{player_id}",
                status="OK",
                rounds={
                    1: PlayerRound(round_number=1, to_par=1, holes=[]),
                },
                total_to_par=1,
            )

        # Mark round 1 as started for one player using hole-level data.
        snapshots[1].rounds[1].holes = [
            HoleResult(
                round_number=1,
                hole_number=1,
                score_type="PAR",
                strokes=4,
                par=4,
            )
        ]

        scored = score_participants(config=config, snapshots=snapshots, winning_to_par=0)
        leaderboard = scored["leaderboard"]

        self.assertEqual(leaderboard[0]["name"], "A")
        self.assertEqual(leaderboard[0]["dailyWinnerBonusDollars"], 50)
        self.assertEqual(leaderboard[0]["dailyWinnerDays"], [1])

    def test_holes_remaining_rolls_up_by_participant_for_active_round(self) -> None:
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="A", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
                ParticipantConfig(name="B", predicted_winning_to_par=5, picks=[9, 10, 11, 12, 13, 14, 15, 16]),
            ],
        )

        snapshots: dict[int, PlayerSnapshot] = {}
        # Team A: one player through 3 holes, one player through 18 holes, six players not started.
        snapshots[1] = PlayerSnapshot(
            player_id=1,
            player_name="A1",
            status="OK",
            rounds={1: PlayerRound(1, 0, [HoleResult(1, 1, "PAR", 4, 4), HoleResult(1, 2, "PAR", 4, 4), HoleResult(1, 3, "PAR", 4, 4)])},
            total_to_par=0,
        )
        snapshots[2] = PlayerSnapshot(
            player_id=2,
            player_name="A2",
            status="OK",
            rounds={1: PlayerRound(1, 0, [HoleResult(1, hole, "PAR", 4, 4) for hole in range(1, 19)])},
            total_to_par=0,
        )
        for player_id in range(3, 9):
            snapshots[player_id] = PlayerSnapshot(
                player_id=player_id,
                player_name=f"A{player_id}",
                status="OK",
                rounds={1: PlayerRound(1, 0, [])},
                total_to_par=0,
            )

        # Team B: all players not started except one WD (counts as 0 holes remaining).
        for player_id in range(9, 16):
            snapshots[player_id] = PlayerSnapshot(
                player_id=player_id,
                player_name=f"B{player_id}",
                status="OK",
                rounds={1: PlayerRound(1, 0, [])},
                total_to_par=0,
            )
        snapshots[16] = PlayerSnapshot(
            player_id=16,
            player_name="B16",
            status="WD",
            rounds={},
            total_to_par=0,
        )

        scored = score_participants(config=config, snapshots=snapshots, winning_to_par=0)
        by_name = {row["name"]: row for row in scored["leaderboard"]}

        # A: (18-3) + (18-18) + 6*18 = 123
        self.assertEqual(by_name["A"]["holesRemaining"], 123)
        self.assertEqual(by_name["A"]["holesRemainingByDay"], {1: 123, 2: 144, 3: 144, 4: 144})
        # B: 7*18 + 0 (WD) = 126
        self.assertEqual(by_name["B"]["holesRemaining"], 126)
        self.assertEqual(by_name["B"]["holesRemainingByDay"], {1: 126, 2: 126, 3: 126, 4: 126})


if __name__ == "__main__":
    unittest.main()
