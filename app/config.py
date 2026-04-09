from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EXPECTED_PICKS_PER_PARTICIPANT = 8


@dataclass(slots=True)
class ParticipantConfig:
    name: str
    predicted_winning_to_par: int
    picks: list[int]


@dataclass(slots=True)
class PoolConfig:
    event_id: str
    poll_interval_seconds_live: int
    poll_interval_seconds_idle: int
    timezone: str
    humor_mode: str
    poll_api_token: str | None
    participants: list[ParticipantConfig]


def load_config(path: Path) -> PoolConfig:
    raw: dict[str, Any] = json.loads(path.read_text())
    participants = [
        ParticipantConfig(
            name=item["name"],
            predicted_winning_to_par=int(item["predictedWinningToPar"]),
            picks=[int(player_id) for player_id in item["picks"]],
        )
        for item in raw["participants"]
    ]
    config = PoolConfig(
        event_id=str(raw["event_id"]),
        poll_interval_seconds_live=int(raw.get("poll_interval_seconds_live", 300)),
        poll_interval_seconds_idle=int(raw.get("poll_interval_seconds_idle", 1800)),
        timezone=str(raw.get("timezone", "America/New_York")),
        humor_mode=str(raw.get("humor_mode", "dry")),
        poll_api_token=_parse_optional_token(raw.get("poll_api_token")),
        participants=participants,
    )
    _validate_config(config)
    return config


def _parse_optional_token(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    token = str(raw_value).strip()
    return token if token else None


def _validate_config(config: PoolConfig) -> None:
    if not config.event_id.strip():
        raise ValueError("event_id must be non-empty")
    if config.poll_interval_seconds_live <= 0 or config.poll_interval_seconds_idle <= 0:
        raise ValueError("poll intervals must be positive")
    if not config.participants:
        raise ValueError("participants must not be empty")

    seen_names: set[str] = set()
    for participant in config.participants:
        name = participant.name.strip()
        if not name:
            raise ValueError("participant names must be non-empty")
        if name in seen_names:
            raise ValueError(f"duplicate participant name: {name}")
        seen_names.add(name)
        if len(participant.picks) != EXPECTED_PICKS_PER_PARTICIPANT:
            raise ValueError(
                f"{name} must have exactly {EXPECTED_PICKS_PER_PARTICIPANT} picks; got {len(participant.picks)}"
            )
        if len(set(participant.picks)) != len(participant.picks):
            raise ValueError(f"{name} has duplicate player IDs in picks")

