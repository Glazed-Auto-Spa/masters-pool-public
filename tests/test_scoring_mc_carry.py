from __future__ import annotations

import unittest

from app.config import ParticipantConfig, PoolConfig
from app.models import HoleResult, PlayerRound, PlayerSnapshot
from app.scoring import _carry_forward_score, score_participants


def _hole(round_no: int, hole_no: int, strokes: int, par: int = 4) -> HoleResult:
    return HoleResult(round_no, hole_no, "PAR", strokes, par)


class TestMissedCutCarryAverage(unittest.TestCase):
    def test_mc_plus_five_plus_seven_averages_six_each_weekend_day(self) -> None:
        picks_ids = list(range(1, 9))
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="Solo", predicted_winning_to_par=0, picks=picks_ids),
            ],
        )
        snapshots: dict[int, PlayerSnapshot] = {
            1: PlayerSnapshot(
                player_id=1,
                player_name="CutPlayer",
                status="MISSED CUT",
                rounds={
                    1: PlayerRound(round_number=1, to_par=5, holes=[_hole(1, 1, 5, 4)]),
                    2: PlayerRound(round_number=2, to_par=7, holes=[_hole(2, 1, 5, 4)]),
                },
                total_to_par=12,
            ),
        }
        for pid in range(2, 9):
            snapshots[pid] = PlayerSnapshot(
                player_id=pid,
                player_name=f"P{pid}",
                status="OK",
                rounds={
                    d: PlayerRound(round_number=d, to_par=0, holes=[_hole(d, 1, 4, 4)])
                    for d in range(1, 5)
                },
                total_to_par=0,
            )
        out = score_participants(config=config, snapshots=snapshots, winning_to_par=0)
        pick0 = next(p for p in out["participantDetails"][0]["picks"] if p["playerId"] == 1)
        self.assertEqual(pick0["dayScores"][1], 5)
        self.assertEqual(pick0["dayScores"][2], 7)
        self.assertEqual(pick0["dayScores"][3], 6)
        self.assertEqual(pick0["dayScores"][4], 6)
        self.assertEqual(pick0.get("penaltyWeekendAvgToPar"), 6)
        # Other seven picks contribute 0 each day.
        self.assertEqual(out["leaderboard"][0]["eventScore"], 24)
        self.assertEqual(out["leaderboard"][0]["dailyScores"][3], 6)
        self.assertEqual(out["leaderboard"][0]["dailyScores"][4], 6)
        self.assertEqual(pick0["roundScorecards"][3]["toPar"], 6)
        self.assertEqual(pick0["roundScorecards"][4]["toPar"], 6)

    def test_mc_plus_eleven_over_two_rounds_floors_to_five_per_day(self) -> None:
        # +5 and +6 => 11 total; floor(11/2) = 5 for Sat and Sun each.
        p = PlayerSnapshot(
            player_id=1,
            player_name="X",
            status="STATUS_CUT MISSED CUT",
            rounds={
                1: PlayerRound(round_number=1, to_par=5, holes=[]),
                2: PlayerRound(round_number=2, to_par=6, holes=[]),
            },
            total_to_par=11,
        )
        self.assertEqual(_carry_forward_score(p), 5)

    def test_mc_only_total_to_par_splits_by_two(self) -> None:
        p = PlayerSnapshot(
            player_id=1,
            player_name="X",
            status="CUT",
            rounds={},
            total_to_par=11,
        )
        self.assertEqual(_carry_forward_score(p), 5)

    def test_wd_uses_same_floored_average_as_mc_for_weekend_carry(self) -> None:
        p = PlayerSnapshot(
            player_id=1,
            player_name="X",
            status="WITHDRAWN",
            rounds={
                1: PlayerRound(round_number=1, to_par=5, holes=[]),
                2: PlayerRound(round_number=2, to_par=7, holes=[]),
            },
            total_to_par=12,
        )
        self.assertEqual(_carry_forward_score(p), 6)

    def test_wd_five_over_each_day_ten_total_five_each_weekend(self) -> None:
        """+5 Thu and +5 Fri → +10 / 2 → floor 5 for Sat and Sun each."""
        picks_ids = list(range(1, 9))
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="Solo", predicted_winning_to_par=0, picks=picks_ids),
            ],
        )
        snapshots: dict[int, PlayerSnapshot] = {
            1: PlayerSnapshot(
                player_id=1,
                player_name="WdPlayer",
                status="WITHDRAWN",
                rounds={
                    1: PlayerRound(round_number=1, to_par=5, holes=[_hole(1, 1, 5, 4)]),
                    2: PlayerRound(round_number=2, to_par=5, holes=[_hole(2, 1, 5, 4)]),
                },
                total_to_par=10,
            ),
        }
        for pid in range(2, 9):
            snapshots[pid] = PlayerSnapshot(
                player_id=pid,
                player_name=f"P{pid}",
                status="OK",
                rounds={
                    d: PlayerRound(round_number=d, to_par=0, holes=[_hole(d, 1, 4, 4)])
                    for d in range(1, 5)
                },
                total_to_par=0,
            )
        out = score_participants(config=config, snapshots=snapshots, winning_to_par=0)
        pick0 = next(p for p in out["participantDetails"][0]["picks"] if p["playerId"] == 1)
        self.assertEqual(pick0["dayScores"][1], 5)
        self.assertEqual(pick0["dayScores"][2], 5)
        self.assertEqual(pick0["dayScores"][3], 5)
        self.assertEqual(pick0["dayScores"][4], 5)
        self.assertEqual(out["leaderboard"][0]["eventScore"], 20)

    def test_mc_ignores_placeholder_sunday_round_to_par(self) -> None:
        """ESPN may still send R4 with wrong cumulative to_par; Sunday must stay floored average."""
        picks_ids = list(range(1, 9))
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="Solo", predicted_winning_to_par=0, picks=picks_ids),
            ],
        )
        snapshots: dict[int, PlayerSnapshot] = {
            1: PlayerSnapshot(
                player_id=1,
                player_name="CutPlayer",
                status="MISSED CUT",
                rounds={
                    1: PlayerRound(round_number=1, to_par=5, holes=[_hole(1, 1, 5, 4)]),
                    2: PlayerRound(round_number=2, to_par=7, holes=[_hole(2, 1, 5, 4)]),
                    # Bogus weekend rows (cumulative / placeholder) must not replace floored average:
                    3: PlayerRound(round_number=3, to_par=88, holes=[]),
                    4: PlayerRound(round_number=4, to_par=99, holes=[]),
                },
                total_to_par=12,
            ),
        }
        for pid in range(2, 9):
            snapshots[pid] = PlayerSnapshot(
                player_id=pid,
                player_name=f"P{pid}",
                status="OK",
                rounds={
                    d: PlayerRound(round_number=d, to_par=0, holes=[_hole(d, 1, 4, 4)])
                    for d in range(1, 5)
                },
                total_to_par=0,
            )
        out = score_participants(config=config, snapshots=snapshots, winning_to_par=0)
        pick0 = next(p for p in out["participantDetails"][0]["picks"] if p["playerId"] == 1)
        self.assertEqual(pick0["dayScores"][3], 6, "Saturday must use MC average, not placeholder R3 to_par")
        self.assertEqual(pick0["dayScores"][4], 6, "Sunday must use MC average, not placeholder R4 to_par")


if __name__ == "__main__":
    unittest.main()
