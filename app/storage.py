from __future__ import annotations

import fcntl
import hashlib
import json
from datetime import UTC, datetime
import os
from pathlib import Path
import tempfile
from typing import Any
from contextlib import contextmanager

from app.models import HoleResult, PlayerRound, PlayerSnapshot


def iso_now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_runtime_paths(base_dir: Path) -> dict[str, Path]:
    ledger_dir = base_dir / "data" / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    state_path = base_dir / "data" / "state.json"
    poll_lock_path = base_dir / "data" / "poll.lock"
    loop_lock_path = base_dir / "data" / "poll_loop.lock"
    return {
        "ledger_dir": ledger_dir,
        "state_path": state_path,
        "poll_lock_path": poll_lock_path,
        "loop_lock_path": loop_lock_path,
    }


def snapshot_to_dict(snapshots: dict[int, PlayerSnapshot]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for player_id, player in snapshots.items():
        output[str(player_id)] = {
            "player_id": player.player_id,
            "player_name": player.player_name,
            "status": player.status,
            "total_to_par": player.total_to_par,
            "rounds": {
                str(round_number): {
                    "round_number": round_data.round_number,
                    "to_par": round_data.to_par,
                    "holes": [
                        {
                            "round_number": hole.round_number,
                            "hole_number": hole.hole_number,
                            "score_type": hole.score_type,
                            "strokes": hole.strokes,
                            "par": hole.par,
                        }
                        for hole in round_data.holes
                    ],
                }
                for round_number, round_data in player.rounds.items()
            },
        }
    return output


def snapshot_from_dict(raw: dict[str, Any]) -> dict[int, PlayerSnapshot]:
    snapshots: dict[int, PlayerSnapshot] = {}
    for player_id_str, player in raw.items():
        rounds = {}
        for round_number_str, round_data in player["rounds"].items():
            holes = [
                HoleResult(
                    round_number=int(hole["round_number"]),
                    hole_number=int(hole["hole_number"]),
                    score_type=str(hole["score_type"]),
                    strokes=int(hole["strokes"]),
                    par=int(hole["par"]),
                )
                for hole in round_data["holes"]
            ]
            rounds[int(round_number_str)] = PlayerRound(
                round_number=int(round_data["round_number"]),
                to_par=int(round_data["to_par"]),
                holes=holes,
            )
        snapshots[int(player_id_str)] = PlayerSnapshot(
            player_id=int(player["player_id"]),
            player_name=str(player["player_name"]),
            status=str(player["status"]),
            rounds=rounds,
            total_to_par=player["total_to_par"],
        )
    return snapshots


def write_ledger_entry(
    ledger_dir: Path,
    entry_type: str,
    payload: dict[str, Any],
) -> Path:
    timestamp = datetime.now(UTC)
    filename = timestamp.strftime("%Y%m%d") + ".jsonl"
    file_path = ledger_dir / filename
    payload_json = json.dumps(payload, sort_keys=True)
    entry = {
        "timestamp": timestamp.isoformat(),
        "entry_type": entry_type,
        "payload_hash": hashlib.sha256(payload_json.encode()).hexdigest(),
        "payload": payload,
    }
    lock_path = ledger_dir / ".ledger.lock"
    with acquire_file_lock(lock_path):
        with file_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
    return file_path


def write_state(state_path: Path, state: dict[str, Any]) -> None:
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    with acquire_file_lock(lock_path):
        _write_text_atomic(
            target_path=state_path,
            content=json.dumps(state, indent=2, sort_keys=True),
        )


def read_state(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {}
    raw = state_path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fail closed to empty state so callers can repopulate via a fresh poll.
        return {}


def read_ledger_entries(ledger_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ledger_file in sorted(ledger_dir.glob("*.jsonl")):
        for line in ledger_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            entries.append(json.loads(line))
    return entries


@contextmanager
def acquire_file_lock(lock_path: Path, *, blocking: bool = True):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        lock_mode = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            fcntl.flock(lock_file.fileno(), lock_mode)
        except BlockingIOError as exc:
            raise RuntimeError(f"Lock already held: {lock_path}") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_text_atomic(target_path: Path, content: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(target_path.parent),
        delete=False,
    ) as tmp_file:
        tmp_file.write(content)
        tmp_name = tmp_file.name
    os.replace(tmp_name, target_path)

