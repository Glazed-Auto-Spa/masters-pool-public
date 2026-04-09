from __future__ import annotations

import logging
from typing import Any

import requests

from app.models import HoleResult, PlayerRound, PlayerSnapshot

LOGGER = logging.getLogger(__name__)

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/pga/scoreboard"
COMPETITORS_URL = (
    "https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/"
    "{event_id}/competitions/{event_id}/competitors?limit=200"
)
LINESCORES_URL = (
    "https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/"
    "{event_id}/competitions/{event_id}/competitors/{player_id}/linescores"
)


def _parse_to_par(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip().upper()
    if value in {"", "-", "--", "—"}:
        return None
    if value in {"E", "EVEN"}:
        return 0
    if value.startswith("+") or value.startswith("-"):
        return int(value)
    try:
        return int(value)
    except ValueError:
        return None


class EspnClient:
    def __init__(self, timeout_seconds: int = 12) -> None:
        self._session = requests.Session()
        self._timeout = timeout_seconds

    def get_scoreboard(self, event_id: str) -> dict[str, Any]:
        response = self._session.get(
            SCOREBOARD_URL,
            params={"event": event_id},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_competitors(self, event_id: str) -> dict[str, Any]:
        response = self._session.get(
            COMPETITORS_URL.format(event_id=event_id),
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_player_linescores(self, event_id: str, player_id: int) -> dict[str, Any]:
        response = self._session.get(
            LINESCORES_URL.format(event_id=event_id, player_id=player_id),
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def build_snapshot(
        self,
        event_id: str,
        players: dict[int, str],
        statuses: dict[int, str],
        fallback_round_scores: dict[int, dict[int, int]] | None = None,
    ) -> tuple[dict[int, PlayerSnapshot], list[str]]:
        snapshots: dict[int, PlayerSnapshot] = {}
        errors: list[str] = []
        fallback_round_scores = fallback_round_scores or {}
        for player_id, player_name in players.items():
            try:
                payload = self.get_player_linescores(event_id=event_id, player_id=player_id)
                rounds = _parse_rounds(payload)
                total = _sum_total_to_par(rounds)
                snapshots[player_id] = PlayerSnapshot(
                    player_id=player_id,
                    player_name=player_name,
                    status=statuses.get(player_id, ""),
                    rounds=rounds,
                    total_to_par=total,
                )
            except Exception as exc:  # noqa: BLE001
                message = f"linescores_failed player_id={player_id} name={player_name}: {exc}"
                LOGGER.warning(message)
                errors.append(message)
                fallback_rounds = {
                    round_number: PlayerRound(round_number=round_number, to_par=to_par, holes=[])
                    for round_number, to_par in fallback_round_scores.get(player_id, {}).items()
                }
                snapshots[player_id] = PlayerSnapshot(
                    player_id=player_id,
                    player_name=player_name,
                    status=statuses.get(player_id, ""),
                    rounds=fallback_rounds,
                    total_to_par=_sum_total_to_par(fallback_rounds),
                )
        return snapshots, errors


def extract_players_and_status(
    scoreboard_payload: dict[str, Any]
) -> tuple[dict[int, str], dict[int, str], int | None, dict[int, dict[int, int]], dict[int, str]]:
    players: dict[int, str] = {}
    statuses: dict[int, str] = {}
    round_scores: dict[int, dict[int, int]] = {}
    field_positions: dict[int, str] = {}
    leader_to_par: int | None = None

    events = scoreboard_payload.get("events", [])
    if not events:
        return players, statuses, None, round_scores, field_positions

    competitors = events[0].get("competitions", [{}])[0].get("competitors", [])
    raw_scores: list[tuple[int, int]] = []
    for idx, item in enumerate(competitors):
        pid = int(item["id"])
        name = item.get("athlete", {}).get("displayName", item.get("athlete", {}).get("fullName", str(pid)))
        score = item.get("score")
        status_detail = item.get("status", {}).get("type", {}).get("description", "")
        status_short = item.get("status", {}).get("type", {}).get("name", "")
        status_blob = f"{status_detail} {status_short} {item.get('status', {}).get('type', {}).get('shortDetail', '')}".upper()
        players[pid] = name
        statuses[pid] = status_blob
        round_scores[pid] = _extract_round_scores(item)
        parsed_score = _parse_to_par(score)
        if parsed_score is not None:
            raw_scores.append((pid, parsed_score))
        if idx == 0:
            leader_to_par = _parse_to_par(score)

    if raw_scores:
        score_counts: dict[int, int] = {}
        for _, score_val in raw_scores:
            score_counts[score_val] = score_counts.get(score_val, 0) + 1

        score_to_rank: dict[int, int] = {}
        next_rank = 1
        for score_val in sorted(score_counts.keys()):
            score_to_rank[score_val] = next_rank
            next_rank += score_counts[score_val]

        for pid, score_val in raw_scores:
            rank = score_to_rank[score_val]
            tied = score_counts[score_val] > 1
            field_positions[pid] = f"T{rank}" if tied else str(rank)

    return players, statuses, leader_to_par, round_scores, field_positions


def _parse_rounds(linescore_payload: dict[str, Any]) -> dict[int, PlayerRound]:
    rounds: dict[int, PlayerRound] = {}
    for item in linescore_payload.get("items", []):
        round_number = int(item.get("period", 0))
        round_to_par = _parse_to_par(item.get("displayValue", "0")) or 0
        hole_entries = []
        for hole in item.get("linescores", []):
            score_type = str(hole.get("scoreType", {}).get("name", "UNKNOWN")).upper()
            hole_entries.append(
                HoleResult(
                    round_number=round_number,
                    hole_number=int(hole.get("period", 0)),
                    score_type=score_type,
                    strokes=int(hole.get("value", 0)),
                    par=int(hole.get("par", 0)),
                )
            )
        hole_entries.sort(key=lambda h: h.hole_number)
        rounds[round_number] = PlayerRound(round_number=round_number, to_par=round_to_par, holes=hole_entries)
    return rounds


def _sum_total_to_par(rounds: dict[int, PlayerRound]) -> int | None:
    if not rounds:
        return None
    return sum(round_data.to_par for round_data in rounds.values())


def _extract_round_scores(competitor_item: dict[str, Any]) -> dict[int, int]:
    output: dict[int, int] = {}
    for item in competitor_item.get("linescores", []):
        round_number = int(item.get("period", 0))
        if round_number <= 0:
            continue
        # ESPN payload variants may expose "displayValue", "score", or "value".
        score_val = item.get("displayValue")
        if score_val is None:
            score_val = item.get("score")
        if score_val is None and item.get("value") is not None:
            score_val = str(item.get("value"))
        parsed = _parse_to_par(str(score_val)) if score_val is not None else None
        if parsed is not None:
            output[round_number] = parsed
    return output

