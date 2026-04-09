from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class HoleResult:
    round_number: int
    hole_number: int
    score_type: str
    strokes: int
    par: int


@dataclass(slots=True)
class PlayerRound:
    round_number: int
    to_par: int
    holes: list[HoleResult] = field(default_factory=list)


@dataclass(slots=True)
class PlayerSnapshot:
    player_id: int
    player_name: str
    status: str
    rounds: dict[int, PlayerRound]
    total_to_par: int | None

