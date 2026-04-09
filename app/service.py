from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import PoolConfig
from app.espn_client import EspnClient, extract_players_and_status
from app.scoring import score_participants
from app.state_store import STATE_SCHEMA_VERSION, StateStore, create_state_store
from app.storage import snapshot_to_dict


class PoolService:
    def __init__(self, base_dir: Path, config: PoolConfig) -> None:
        self.base_dir = base_dir
        self.config = config
        self.client = EspnClient()
        self.store: StateStore = create_state_store(base_dir=base_dir)

    def poll_once(self) -> dict[str, Any]:
        with self.store.acquire_poll_lock(blocking=True):
            previous_state = self.get_state()
            scoreboard = self.client.get_scoreboard(event_id=self.config.event_id)
            players, statuses, winning_to_par, round_scores, field_positions = extract_players_and_status(scoreboard)
            self.store.append_ledger("scoreboard", scoreboard)

            tracked_players = self._tracked_players(players)
            tracked_statuses = {player_id: statuses.get(player_id, "") for player_id in tracked_players.keys()}
            snapshots, errors = self.client.build_snapshot(
                event_id=self.config.event_id,
                players=tracked_players,
                statuses=tracked_statuses,
                fallback_round_scores=round_scores,
            )

            snapshot_dict = snapshot_to_dict(snapshots)
            self.store.append_ledger("snapshot", snapshot_dict)
            standings = score_participants(self.config, snapshots=snapshots, winning_to_par=winning_to_par)
            _annotate_rank_movement(
                leaderboard=standings.get("leaderboard", []),
                previous_leaderboard=previous_state.get("leaderboard", []) if isinstance(previous_state, dict) else [],
            )

            state = {
                "stateSchemaVersion": STATE_SCHEMA_VERSION,
                "eventId": self.config.event_id,
                "updatedAt": datetime.now(UTC).isoformat(),
                "winningToPar": winning_to_par,
                "degradedMode": bool(errors),
                "errors": errors,
                **standings,
            }
            payout_ok, payout_reason = _validate_payout_state(
                leaderboard=state.get("leaderboard", []),
                participant_count=len(self.config.participants),
            )
            state["payoutIntegrityOk"] = payout_ok
            state["payoutIntegrityReason"] = payout_reason
            if not payout_ok:
                for row in state.get("leaderboard", []):
                    row["mainEventPayoutDollars"] = None
                    row["netPayoutDollars"] = None
            state["playerPulse"] = _build_player_pulse(snapshots)
            _annotate_pick_live_state(
                participant_details=state.get("participantDetails", []),
                player_pulse=state["playerPulse"],
                field_positions=field_positions,
            )
            cycle_feed = _build_event_feed(previous_state=previous_state, current_state=state)
            historical_feed = previous_state.get("eventFeed", []) if isinstance(previous_state, dict) else []
            if isinstance(historical_feed, list):
                historical_feed = [
                    entry
                    for entry in historical_feed
                    if isinstance(entry, dict) and entry.get("type") == "movement" and entry.get("causal") is True
                ]
            else:
                historical_feed = []
            state["eventFeed"] = (cycle_feed + historical_feed)[:300]
            self.store.write_state(state)
            self.store.append_ledger("state", state)
            return state

    def get_state(self) -> dict[str, Any]:
        state = self.store.read_state()
        if not isinstance(state, dict):
            return {}
        if state.get("stateSchemaVersion") != STATE_SCHEMA_VERSION:
            return {}
        return state

    def _tracked_players(self, all_players: dict[int, str]) -> dict[int, str]:
        needed: set[int] = set()
        for participant in self.config.participants:
            needed.update(participant.picks)
        output: dict[int, str] = {}
        unresolved = []
        for player_id in sorted(needed):
            if player_id in all_players:
                output[player_id] = all_players[player_id]
            else:
                unresolved.append(player_id)
        if unresolved:
            raise RuntimeError(f"Unresolved player IDs in config: {unresolved}")
        return output


def _build_event_feed(previous_state: dict[str, Any], current_state: dict[str, Any]) -> list[dict[str, str]]:
    now = current_state.get("updatedAt", datetime.now(UTC).isoformat())
    prev_rows = {
        row.get("name"): row
        for row in previous_state.get("leaderboard", [])
        if row.get("name")
    }
    events: list[dict[str, str]] = []
    for row in current_state.get("leaderboard", []):
        name = row.get("name")
        if not name:
            continue
        prev = prev_rows.get(name)
        if prev is None:
            continue

        rank_now = int(row.get("rank", 0))
        rank_prev = int(prev.get("rank", 0))
        score_now = row.get("eventScore")
        score_prev = prev.get("eventScore")
        own_score_changed = isinstance(score_now, int) and isinstance(score_prev, int) and score_now != score_prev
        # Movement-only, causality-first feed:
        # include rank changes only when this participant's own score changed.
        if rank_now and rank_prev and rank_now != rank_prev and own_score_changed:
            direction = "up" if rank_now < rank_prev else "down"
            delta = abs(rank_prev - rank_now)
            reason = _rank_move_reason(
                participant_name=name,
                direction=direction,
                previous_state=previous_state,
                current_state=current_state,
            )
            verb = _movement_verb(direction=direction, delta=delta)
            reason_text = reason if reason else " Scoring swing shifts the board."
            events.append(
                {
                    "time": now,
                    "message": (
                        f"{name} {verb} {direction} {delta} spot{'s' if delta != 1 else ''} to #{rank_now}."
                        f"{reason_text}"
                    ),
                    "type": "movement",
                    "causal": True,
                }
            )
    return events[:40]


def _build_player_pulse(snapshots: dict[int, Any]) -> dict[str, dict[str, Any]]:
    pulse: dict[str, dict[str, Any]] = {}
    for player_id, snapshot in snapshots.items():
        latest_round = 0
        latest_hole = 0
        latest_score_type = ""
        latest_strokes = 0
        for round_number, round_data in snapshot.rounds.items():
            for hole in round_data.holes:
                if hole.strokes <= 0:
                    continue
                if round_number > latest_round or (round_number == latest_round and hole.hole_number > latest_hole):
                    latest_round = round_number
                    latest_hole = hole.hole_number
                    latest_score_type = hole.score_type
                    latest_strokes = hole.strokes
        pulse[str(player_id)] = {
            "playerId": player_id,
            "playerName": snapshot.player_name,
            "round": latest_round if latest_round > 0 else None,
            "hole": latest_hole if latest_hole > 0 else None,
            "scoreType": latest_score_type,
            "strokes": latest_strokes if latest_strokes > 0 else None,
            "totalToPar": snapshot.total_to_par,
        }
    return pulse


def _rank_move_reason(
    participant_name: str,
    direction: str,
    previous_state: dict[str, Any],
    current_state: dict[str, Any],
) -> str:
    prev_pulse = previous_state.get("playerPulse", {}) if isinstance(previous_state, dict) else {}
    curr_pulse = current_state.get("playerPulse", {}) if isinstance(current_state, dict) else {}
    if not isinstance(prev_pulse, dict) or not isinstance(curr_pulse, dict):
        return ""

    details = current_state.get("participantDetails", [])
    participant = next((row for row in details if row.get("name") == participant_name), None)
    if not participant:
        return ""

    picks = participant.get("picks", [])
    favored_types = (
        {"ACE", "EAGLE", "BIRDIE"} if direction == "up" else {"BOGEY", "DOUBLE_BOGEY", "TRIPLE_BOGEY", "WORSE"}
    )
    fallback_reason = ""

    for pick in picks:
        player_id = pick.get("playerId")
        if player_id is None:
            continue
        player_key = str(player_id)
        before = prev_pulse.get(player_key)
        after = curr_pulse.get(player_key)
        if not isinstance(after, dict):
            continue
        if before == after:
            continue

        score_type = str(after.get("scoreType", "") or "")
        score_label = score_type.replace("_", " ").title() if score_type else "Score"
        hole = after.get("hole")
        rnd = after.get("round")
        player_name = after.get("playerName", pick.get("playerName", f"Player {player_id}"))
        if hole and rnd:
            candidate = f" {player_name} {score_label} on hole {hole} (R{rnd})."
        else:
            candidate = f" {player_name} posts a scoring update."

        if score_type in favored_types:
            return candidate
        if not fallback_reason:
            fallback_reason = candidate

    return fallback_reason


def _movement_verb(direction: str, delta: int) -> str:
    if direction == "up":
        if delta >= 3:
            return "surges"
        return "climbs"
    if delta >= 3:
        return "plunges"
    return "slides"


def _annotate_rank_movement(leaderboard: list[dict[str, Any]], previous_leaderboard: list[dict[str, Any]]) -> None:
    prev_rows_by_name: dict[str, dict[str, Any]] = {}
    prev_ranks: dict[str, int] = {}
    for row in previous_leaderboard:
        name = row.get("name")
        rank = row.get("rank")
        if isinstance(name, str):
            prev_rows_by_name[name] = row
            if isinstance(rank, int):
                prev_ranks[name] = rank

    for row in leaderboard:
        name = row.get("name")
        rank_now = row.get("rank")
        if not isinstance(name, str) or not isinstance(rank_now, int):
            row["moveDirection"] = "flat"
            row["moveDelta"] = 0
            row["previousRank"] = None
            row["movedThisCycle"] = False
            continue

        prev_row = prev_rows_by_name.get(name, {})
        rank_prev = prev_ranks.get(name)
        row["previousRank"] = rank_prev
        if rank_prev is None:
            row["moveDirection"] = "new"
            row["moveDelta"] = 0
            row["movedThisCycle"] = False
            continue

        delta = rank_prev - rank_now
        if delta > 0:
            row["moveDelta"] = abs(delta)
            row["moveDirection"] = "up"
            row["movedThisCycle"] = True
        elif delta < 0:
            row["moveDelta"] = abs(delta)
            row["moveDirection"] = "down"
            row["movedThisCycle"] = True
        else:
            prev_dir = prev_row.get("moveDirection")
            prev_delta = prev_row.get("moveDelta", 0)
            if prev_dir in {"up", "down"} and isinstance(prev_delta, int) and prev_delta > 0:
                # Sticky arrows: keep the most recent non-flat marker
                # until a new movement occurs.
                row["moveDirection"] = prev_dir
                row["moveDelta"] = prev_delta
            else:
                row["moveDirection"] = "flat"
                row["moveDelta"] = 0
            row["movedThisCycle"] = False


def _annotate_pick_live_state(
    participant_details: list[dict[str, Any]],
    player_pulse: dict[str, dict[str, Any]],
    field_positions: dict[int, str],
) -> None:
    for participant in participant_details:
        picks = participant.get("picks", [])
        if not isinstance(picks, list):
            continue
        for pick in picks:
            player_id = pick.get("playerId")
            if not isinstance(player_id, int):
                pick["fieldPosition"] = "-"
                pick["throughDisplay"] = "-"
                pick["scoreToPar"] = None
                continue
            pulse = player_pulse.get(str(player_id), {})
            pick["fieldPosition"] = field_positions.get(player_id, "-")
            pick["scoreToPar"] = pulse.get("totalToPar")
            pick["throughDisplay"] = _through_display(
                round_number=pulse.get("round"),
                hole=pulse.get("hole"),
                status=str(pick.get("status", "") or ""),
            )


def _through_display(round_number: Any, hole: Any, status: str) -> str:
    status_upper = status.upper()
    if "WITHDRAW" in status_upper or " WD" in f" {status_upper}":
        return "WD"
    if "MISSED CUT" in status_upper or " MC" in f" {status_upper}":
        return "MC"

    if not isinstance(round_number, int) or not isinstance(hole, int):
        return "-"
    if round_number <= 0 or hole <= 0:
        return "-"
    if hole >= 18:
        return "F"
    return f"Thru {hole}"


def _validate_payout_state(leaderboard: list[dict[str, Any]], participant_count: int) -> tuple[bool, str]:
    if not leaderboard:
        return False, "no leaderboard rows"
    if participant_count <= 0:
        return False, "invalid participant count"

    main_payout_rows = 0
    main_payout_sum = 0.0
    net_sum = 0.0
    for row in leaderboard:
        main_val = row.get("mainEventPayoutDollars")
        net_val = row.get("netPayoutDollars")
        if main_val is None or net_val is None:
            return False, "missing payout fields"
        main_num = float(main_val)
        net_num = float(net_val)
        if main_num > 0:
            main_payout_rows += 1
        main_payout_sum += main_num
        net_sum += net_num

    expected_pot = participant_count * 25
    if main_payout_rows != 1:
        return False, "main payout assigned to multiple rows"
    if abs(main_payout_sum - expected_pot) > 0.01:
        return False, "main payout sum mismatch"
    # Net payouts should zero-sum in a closed pool.
    if abs(net_sum) > 0.01:
        return False, "net payouts do not sum to zero"
    return True, "ok"

