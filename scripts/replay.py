from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.scoring import score_participants
from app.storage import read_ledger_entries, snapshot_from_dict


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay standings from immutable ledger.")
    parser.add_argument(
        "--at",
        required=True,
        help="ISO timestamp. Replays using last snapshot entry at or before this time.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    target = datetime.fromisoformat(args.at.replace("Z", "+00:00"))

    base_dir = Path(__file__).resolve().parents[1]
    config_path = base_dir / "data" / "pool_config.json"
    if not config_path.exists():
        config_path = base_dir / "data" / "pool_config.example.json"

    config = load_config(config_path)
    entries = read_ledger_entries(base_dir / "data" / "ledger")

    snapshot_payload = None
    winning_to_par = None
    for entry in entries:
        entry_time = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
        if entry_time > target:
            break
        if entry["entry_type"] == "snapshot":
            snapshot_payload = entry["payload"]
        elif entry["entry_type"] == "state":
            winning_to_par = entry["payload"].get("winningToPar")

    if snapshot_payload is None:
        raise SystemExit("No snapshot found at or before requested timestamp.")

    snapshots = snapshot_from_dict(snapshot_payload)
    standings = score_participants(config=config, snapshots=snapshots, winning_to_par=winning_to_par)
    print(json.dumps(standings, indent=2))


if __name__ == "__main__":
    main()

