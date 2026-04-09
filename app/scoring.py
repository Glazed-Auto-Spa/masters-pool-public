from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import PoolConfig
from app.models import HoleResult, PlayerSnapshot

QUALIFYING_STREAK_TYPES = {"BIRDIE", "EAGLE", "ACE"}
DAY_TO_ROUND = {1: 1, 2: 2, 3: 3, 4: 4}
MAIN_EVENT_BUY_IN = 25
MASTERS_PARS = [4, 5, 4, 3, 4, 3, 4, 5, 4, 4, 4, 3, 5, 4, 5, 3, 4, 4]
MASTERS_YARDS = [445, 585, 350, 177, 495, 192, 450, 570, 460, 495, 520, 150, 545, 440, 550, 165, 450, 465]
MASTERS_HANDICAP = [9, 1, 13, 15, 5, 17, 11, 3, 7, 6, 8, 16, 4, 12, 2, 18, 14, 10]
MASTERS_HOLE_NAMES = [
    "Tea Olive",
    "Pink Dogwood",
    "Flowering Peach",
    "Flowering Crab Apple",
    "Magnolia",
    "Juniper",
    "Pampas",
    "Yellow Jasmine",
    "Carolina Cherry",
    "Camellia",
    "White Dogwood",
    "Golden Bell",
    "Azalea",
    "Chinese Fir",
    "Firethorn",
    "Redbud",
    "Nandina",
    "Holly",
]
MASTERS_HOLE_SHORT_NAMES = [
    "Tea",
    "Dogwood",
    "Peach",
    "Crab Apple",
    "Magnolia",
    "Juniper",
    "Pampas",
    "Jasmine",
    "Cherry",
    "Camellia",
    "Dogwood",
    "Bell",
    "Azalea",
    "Fir",
    "Firethorn",
    "Redbud",
    "Nandina",
    "Holly",
]


@dataclass(slots=True)
class ParticipantResult:
    name: str
    daily_scores: dict[int, int]
    event_score: int
    eagle_bonus: int
    ace_bonus: int
    streak_bonus: int
    daily_winner_bonus: int
    daily_winner_days: list[int]
    holes_remaining: int
    holes_remaining_by_day: dict[int, int]
    main_event_payout: int
    net_payout: float
    tiebreak_prediction: int
    tiebreak_diff: int | None = None


def is_penalty_status(status_blob: str) -> bool:
    text = status_blob.upper()
    return "WD" in text or "WITHDRAW" in text or "MISSED CUT" in text or "MC" in text


def score_participants(
    config: PoolConfig,
    snapshots: dict[int, PlayerSnapshot],
    winning_to_par: int | None,
) -> dict[str, Any]:
    results: list[ParticipantResult] = []
    participant_details: list[dict[str, Any]] = []
    main_event_pot = len(config.participants) * MAIN_EVENT_BUY_IN
    active_round = _active_live_round(snapshots)
    for participant in config.participants:
        daily_scores: dict[int, int] = {}
        pick_scores_by_day: dict[int, dict[int, int]] = {}
        counted_ids_by_day: dict[int, set[int]] = {}
        eagle_total = 0
        ace_total = 0
        streak_total = 0

        for day in range(1, 5):
            round_number = DAY_TO_ROUND[day]
            scored_picks: list[tuple[int, int]] = []
            pick_scores_by_day[day] = {}
            for player_id in participant.picks:
                player = snapshots.get(player_id)
                score = 0
                if player is None:
                    scored_picks.append((0, player_id))
                    pick_scores_by_day[day][player_id] = 0
                    continue

                round_data = player.rounds.get(round_number)
                if round_data is not None:
                    score = round_data.to_par
                else:
                    # If a player misses the cut or withdraws, carry their cumulative
                    # score to each remaining unplayed day.
                    carried = _carry_forward_score(player)
                    score = carried if carried is not None else 0

                scored_picks.append((score, player_id))
                pick_scores_by_day[day][player_id] = score

            counted_ids_by_day[day] = {player_id for _, player_id in scored_picks}
            daily_scores[day] = sum(score for score, _ in scored_picks) if scored_picks else 0

        for player_id in participant.picks:
            player = snapshots.get(player_id)
            if player is None:
                continue
            eagle_total += _count_score_types(player, {"EAGLE"}) * 10
            ace_total += _count_score_types(player, {"ACE"}) * 20
            streak_total += _streak_bonus(player)

        event_score = sum(daily_scores.values())
        holes_remaining_by_day = {
            day: sum(
                _holes_remaining_for_player_in_round(snapshots.get(player_id), day)
                for player_id in participant.picks
            )
            for day in range(1, 5)
        }
        holes_remaining = sum(
            _holes_remaining_for_player_in_round(snapshots.get(player_id), active_round)
            for player_id in participant.picks
        )
        result = ParticipantResult(
            name=participant.name,
            daily_scores=daily_scores,
            event_score=event_score,
            eagle_bonus=eagle_total,
            ace_bonus=ace_total,
            streak_bonus=streak_total,
            daily_winner_bonus=0,
            daily_winner_days=[],
            holes_remaining=holes_remaining,
            holes_remaining_by_day=holes_remaining_by_day,
            main_event_payout=0,
            net_payout=0.0,
            tiebreak_prediction=participant.predicted_winning_to_par,
        )
        if winning_to_par is not None:
            result.tiebreak_diff = abs(participant.predicted_winning_to_par - winning_to_par)
        results.append(result)
        participant_details.append(
            {
                "name": participant.name,
                "eventScore": event_score,
                "dailyTotals": daily_scores,
                "picks": [
                    _build_pick_detail(
                        player_id=player_id,
                        snapshots=snapshots,
                        pick_scores_by_day=pick_scores_by_day,
                        counted_ids_by_day=counted_ids_by_day,
                    )
                    for player_id in participant.picks
                ],
            }
        )

    active_days = _active_days_for_daily_winner(snapshots)
    _apply_daily_winner_bonuses(results, active_days=active_days)
    results.sort(key=_result_rank_key)
    if results:
        results[0].main_event_payout = main_event_pot

    side_totals = [
        result.eagle_bonus + result.ace_bonus + result.streak_bonus + result.daily_winner_bonus
        for result in results
    ]
    side_nets = _compute_side_nets(side_totals)
    for idx, result in enumerate(results):
        side_net = side_nets[idx] if idx < len(side_nets) else 0.0
        result.net_payout = round(side_net, 2)
    leaderboard = []
    for idx, result in enumerate(results, start=1):
        leaderboard.append(
            {
                "rank": idx,
                "name": result.name,
                "eventScore": result.event_score,
                "holesRemaining": result.holes_remaining,
                "holesRemainingByDay": result.holes_remaining_by_day,
                "dailyScores": result.daily_scores,
                "eagleBonusDollars": result.eagle_bonus,
                "aceBonusDollars": result.ace_bonus,
                "birdieStreakBonusDollars": result.streak_bonus,
                "dailyWinnerBonusDollars": result.daily_winner_bonus,
                "dailyWinnerDays": result.daily_winner_days,
                "mainEventPayoutDollars": result.main_event_payout,
                "netPayoutDollars": result.net_payout,
                "predictedWinningToPar": result.tiebreak_prediction,
                "tiebreakDiff": result.tiebreak_diff,
            }
        )

    side_game_leaders = {
        "eagles": sorted(
            (
                {"name": row["name"], "amount": row["eagleBonusDollars"]}
                for row in leaderboard
            ),
            key=lambda x: x["amount"],
            reverse=True,
        ),
        "aces": sorted(
            (
                {"name": row["name"], "amount": row["aceBonusDollars"]}
                for row in leaderboard
            ),
            key=lambda x: x["amount"],
            reverse=True,
        ),
        "streaks": sorted(
            (
                {"name": row["name"], "amount": row["birdieStreakBonusDollars"]}
                for row in leaderboard
            ),
            key=lambda x: x["amount"],
            reverse=True,
        ),
        "dailyWinners": sorted(
            (
                {"name": row["name"], "amount": row.get("dailyWinnerBonusDollars", 0)}
                for row in leaderboard
            ),
            key=lambda x: x["amount"],
            reverse=True,
        ),
    }

    return {
        "leaderboard": leaderboard,
        "participantDetails": participant_details,
        "sideGameLeaders": side_game_leaders,
        "courseCard": {
            "holes": list(range(1, 19)),
            "holeNames": MASTERS_HOLE_NAMES,
            "holeShortNames": MASTERS_HOLE_SHORT_NAMES,
            "pars": MASTERS_PARS,
            "yards": MASTERS_YARDS,
            "handicap": MASTERS_HANDICAP,
            "outPar": sum(MASTERS_PARS[:9]),
            "inPar": sum(MASTERS_PARS[9:]),
            "totalPar": sum(MASTERS_PARS),
            "outYards": sum(MASTERS_YARDS[:9]),
            "inYards": sum(MASTERS_YARDS[9:]),
            "totalYards": sum(MASTERS_YARDS),
        },
    }


def _build_pick_detail(
    player_id: int,
    snapshots: dict[int, PlayerSnapshot],
    pick_scores_by_day: dict[int, dict[int, int]],
    counted_ids_by_day: dict[int, set[int]],
) -> dict[str, Any]:
    player = snapshots.get(player_id)
    player_name = player.player_name if player else f"Player {player_id}"
    status = player.status if player else "UNKNOWN"
    day_scores = {
        day: pick_scores_by_day.get(day, {}).get(player_id, 0)
        for day in range(1, 5)
    }
    counted = {
        day: player_id in counted_ids_by_day.get(day, set())
        for day in range(1, 5)
    }
    round_scorecards = {
        day: _round_card(player, day)
        for day in range(1, 5)
    }
    return {
        "playerId": player_id,
        "playerName": player_name,
        "status": status,
        "dayScores": day_scores,
        "counted": counted,
        "roundScorecards": round_scorecards,
    }


def _round_card(player: PlayerSnapshot | None, day: int) -> dict[str, Any]:
    if player is None:
        return {"holes": [], "holeTypes": [], "out": 0, "in": 0, "total": 0, "toPar": 0}
    round_data = player.rounds.get(day)
    if round_data is None:
        return {"holes": [], "holeTypes": [], "out": 0, "in": 0, "total": 0, "toPar": 0}
    holes = sorted(round_data.holes, key=lambda h: h.hole_number)
    scores = [hole.strokes for hole in holes]
    hole_types = [hole.score_type for hole in holes]
    if len(scores) < 18:
        scores = scores + [0] * (18 - len(scores))
    if len(hole_types) < 18:
        hole_types = hole_types + [""] * (18 - len(hole_types))
    out_total = sum(value for value in scores[:9] if value > 0)
    in_total = sum(value for value in scores[9:] if value > 0)
    total = out_total + in_total
    return {
        "holes": scores[:18],
        "holeTypes": hole_types[:18],
        "out": out_total,
        "in": in_total,
        "total": total,
        "toPar": round_data.to_par,
    }


def _count_score_types(player: PlayerSnapshot, score_types: set[str]) -> int:
    total = 0
    for round_data in player.rounds.values():
        for hole in round_data.holes:
            if hole.score_type in score_types:
                total += 1
    return total


def _streak_bonus(player: PlayerSnapshot) -> int:
    payout = 0
    for round_number in sorted(player.rounds.keys()):
        streak = 0
        holes: list[HoleResult] = sorted(player.rounds[round_number].holes, key=lambda h: h.hole_number)
        for hole in holes:
            if hole.score_type in QUALIFYING_STREAK_TYPES:
                streak += 1
                if streak >= 3:
                    payout += 10
            else:
                streak = 0
    return payout


def _carry_forward_score(player: PlayerSnapshot) -> int | None:
    if not is_penalty_status(player.status):
        return None
    if player.total_to_par is not None:
        return int(player.total_to_par)
    if not player.rounds:
        return 0
    return sum(round_data.to_par for round_data in player.rounds.values())


def _compute_side_nets(side_totals: list[int]) -> list[float]:
    if not side_totals:
        return []
    participant_count = len(side_totals)
    if participant_count == 1:
        return [0.0]

    side_total_sum = sum(side_totals)
    denominator = participant_count - 1
    # "For everyone" settlement:
    # each participant's side winnings are paid by all other participants equally.
    # net_i = S_i - (sum_{j!=i} S_j)/(N-1) = (N*S_i - sum(S))/(N-1)
    return [
        float((participant_count * total - side_total_sum) / denominator)
        for total in side_totals
    ]


def _result_rank_key(result: ParticipantResult) -> tuple[int, int, str]:
    return (
        result.event_score,
        result.tiebreak_diff if result.tiebreak_diff is not None else 9999,
        result.name,
    )


def _apply_daily_winner_bonuses(results: list[ParticipantResult], active_days: set[int]) -> None:
    if not results:
        return
    for day in sorted(active_days):
        low_score = min(result.daily_scores.get(day, 0) for result in results)
        contenders = [result for result in results if result.daily_scores.get(day, 0) == low_score]
        # Exactly one daily winner: deterministic tie-break by existing leaderboard key.
        winner = sorted(contenders, key=_result_rank_key)[0]
        winner.daily_winner_bonus += 10
        winner.daily_winner_days.append(day)


def _active_days_for_daily_winner(snapshots: dict[int, PlayerSnapshot]) -> set[int]:
    max_started_round = 0
    for snapshot in snapshots.values():
        for round_number, round_data in snapshot.rounds.items():
            if round_number < 1 or round_number > 4:
                continue
            # A round is considered started if ESPN returns hole-level scoring for it.
            if round_data.holes:
                max_started_round = max(max_started_round, round_number)
    if max_started_round <= 0:
        return set()
    return set(range(1, max_started_round + 1))


def _active_live_round(snapshots: dict[int, PlayerSnapshot]) -> int:
    max_started_round = 0
    for snapshot in snapshots.values():
        for round_number, round_data in snapshot.rounds.items():
            if round_number < 1 or round_number > 4:
                continue
            if round_data.holes:
                max_started_round = max(max_started_round, round_number)
    # If no hole-level data is present yet, default to round 1.
    return max_started_round if max_started_round > 0 else 1


def _holes_remaining_for_player_in_round(player: PlayerSnapshot | None, round_number: int) -> int:
    if player is None:
        return 18
    if is_penalty_status(player.status):
        return 0
    round_data = player.rounds.get(round_number)
    if round_data is None:
        return 18
    played_holes = len({hole.hole_number for hole in round_data.holes if hole.strokes > 0 and 1 <= hole.hole_number <= 18})
    return max(0, 18 - played_holes)

