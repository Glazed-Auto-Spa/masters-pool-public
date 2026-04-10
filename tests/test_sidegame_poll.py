from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.config import ParticipantConfig, PoolConfig
from app.service import (
    START_DAY_POLICY_KEY,
    SIDEGAME_POLL_THRESHOLD,
    PoolService,
    _with_sidegame_poll_summary,
)
from app.state_store import STATE_SCHEMA_VERSION


class TestSideGamePoll(unittest.TestCase):
    def test_poll_summary_marks_majority_after_threshold(self) -> None:
        state = {
            "stateSchemaVersion": STATE_SCHEMA_VERSION,
            "sideGamePoll": {
                "active": True,
                "threshold": SIDEGAME_POLL_THRESHOLD,
                "games": {
                    "eagles": {
                        "votes": {
                            "A": "keep",
                            "B": "keep",
                            "C": "keep",
                            "D": "remove",
                            "E": "remove",
                        }
                    }
                },
            },
        }
        out = _with_sidegame_poll_summary(state=state, participant_names=["A", "B", "C", "D", "E", "F"])
        summary = out["sideGamePoll"]["summaries"]["eagles"]
        self.assertEqual(summary["totalVotes"], 5)
        self.assertTrue(summary["hasMajority"])
        self.assertEqual(summary["decidedOption"], "keep")

    def test_submit_vote_allows_once_per_game_per_voter(self) -> None:
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="A", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
                ParticipantConfig(name="B", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = PoolService(base_dir=Path(tmp), config=config)
            service.store.write_state(
                {
                    "stateSchemaVersion": STATE_SCHEMA_VERSION,
                    "leaderboard": [],
                    "participantDetails": [],
                    "sideGameLeaders": {},
                }
            )

            updated = service.submit_sidegame_poll_vote(voter="A", game="eagles", vote="keep")
            self.assertEqual(updated["sideGamePoll"]["summaries"]["eagles"]["keepCount"], 1)

            with self.assertRaises(ValueError):
                service.submit_sidegame_poll_vote(voter="A", game="eagles", vote="remove")

            updated = service.submit_sidegame_poll_vote(voter="A", game="aces", vote="remove")
            self.assertEqual(updated["sideGamePoll"]["summaries"]["aces"]["removeCount"], 1)

    def test_start_day_policy_vote_and_reset(self) -> None:
        config = PoolConfig(
            event_id="evt",
            poll_interval_seconds_live=300,
            poll_interval_seconds_idle=1800,
            timezone="America/New_York",
            humor_mode="dry",
            poll_api_token=None,
            participants=[
                ParticipantConfig(name="A", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
                ParticipantConfig(name="B", predicted_winning_to_par=0, picks=[1, 2, 3, 4, 5, 6, 7, 8]),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            service = PoolService(base_dir=Path(tmp), config=config)
            service.store.write_state(
                {
                    "stateSchemaVersion": STATE_SCHEMA_VERSION,
                    "leaderboard": [],
                    "participantDetails": [],
                    "sideGameLeaders": {},
                }
            )

            updated = service.submit_sidegame_poll_vote(voter="A", game=START_DAY_POLICY_KEY, vote="day2")
            summary = updated["sideGamePoll"]["summaries"][START_DAY_POLICY_KEY]
            self.assertEqual(summary["day2Count"], 1)
            with self.assertRaises(ValueError):
                service.submit_sidegame_poll_vote(voter="A", game=START_DAY_POLICY_KEY, vote="day1")

            reset = service.reset_sidegame_poll_tallies()
            self.assertEqual(reset["sideGamePoll"]["summaries"]["eagles"]["totalVotes"], 0)
            self.assertEqual(reset["sideGamePoll"]["summaries"][START_DAY_POLICY_KEY]["totalVotes"], 0)


if __name__ == "__main__":
    unittest.main()
