from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.espn_client import EspnClient, extract_players_and_status


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    config_path = base_dir / "data" / "pool_config.json"
    if not config_path.exists():
        config_path = base_dir / "data" / "pool_config.example.json"
    config = load_config(config_path)

    client = EspnClient()
    scoreboard = client.get_scoreboard(config.event_id)
    players, _, _, _ = extract_players_and_status(scoreboard)

    reverse = {name.lower(): player_id for player_id, name in players.items()}
    out = {"eventId": config.event_id, "players": players, "byNameLower": reverse}
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

