from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests

from app.models import HoleResult, PlayerRound, PlayerSnapshot
from app.scoring import is_penalty_status

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
COMPETITOR_STATUS_URL = (
    "https://sports.core.api.espn.com/v2/sports/golf/leagues/pga/events/"
    "{event_id}/competitions/{event_id}/competitors/{player_id}/status"
)

_PHOENIX_TZ = ZoneInfo("America/Phoenix")
_ESPN_TEE_DATETIME_RE = re.compile(
    r"^[A-Za-z]{3}\s+"
    r"(?P<mon>[A-Za-z]{3})\s+"
    r"(?P<day>\d{1,2})\s+"
    r"(?P<hms>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<tz>[A-Z]{2,5})\s+"
    r"(?P<year>\d{4})$"
)
_MONTH_ABBREV_TO_NUM = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_ABBREV_TZ_TO_ZONE: dict[str, ZoneInfo] = {
    "PDT": ZoneInfo("America/Los_Angeles"),
    "PST": ZoneInfo("America/Los_Angeles"),
    "EDT": ZoneInfo("America/New_York"),
    "EST": ZoneInfo("America/New_York"),
    "CDT": ZoneInfo("America/Chicago"),
    "CST": ZoneInfo("America/Chicago"),
    "MDT": ZoneInfo("America/Denver"),
    "MST": ZoneInfo("America/Denver"),
    "UTC": ZoneInfo("UTC"),
    "GMT": ZoneInfo("GMT"),
}


def status_blob_from_core_status(status: dict[str, Any]) -> str:
    parts: list[str] = []
    dv = status.get("displayValue")
    if dv:
        parts.append(str(dv))
    stype = status.get("type") or {}
    for key in ("description", "detail", "shortDetail", "name"):
        v = stype.get(key)
        if v:
            parts.append(str(v))
    return " ".join(parts).strip().upper()


def merge_player_statuses_with_core(
    client: EspnClient,
    event_id: str,
    base_statuses: dict[int, str],
    player_ids: Iterable[int],
    *,
    max_workers: int = 8,
) -> dict[int, str]:
    """
    Overlay ESPN core /competitors/{id}/status for selected players.
    Fills empty scoreboard status blobs and upgrades to penalty states (MC/WD/DQ).
    """
    out: dict[int, str] = dict(base_statuses)
    ids = sorted({int(pid) for pid in player_ids})

    def fetch_one(pid: int) -> tuple[int, str | None]:
        payload = client.get_competitor_status(event_id, pid)
        if not payload:
            return pid, None
        return pid, status_blob_from_core_status(payload)

    if not ids:
        return out

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_one, pid): pid for pid in ids}
        for fut in as_completed(futures):
            pid, core_blob = fut.result()
            if not core_blob:
                continue
            existing = str(out.get(pid, "") or "").strip()
            if is_penalty_status(core_blob):
                out[pid] = core_blob
            elif not existing:
                out[pid] = core_blob
    return out


def format_tee_time_phoenix_from_stat_display(raw: str) -> str | None:
    """
    Parse ESPN statistics displayValue like 'Sat Apr 11 14:50:00 PDT 2026' and format in America/Phoenix.
    """
    s = str(raw or "").strip()
    m = _ESPN_TEE_DATETIME_RE.match(s)
    if not m:
        return None
    mon = _MONTH_ABBREV_TO_NUM.get(m.group("mon").upper())
    if mon is None:
        return None
    tz_name = m.group("tz").upper()
    src_zone = _ABBREV_TZ_TO_ZONE.get(tz_name)
    if src_zone is None:
        return None
    try:
        year = int(m.group("year"))
        day = int(m.group("day"))
        hh, mm, ss = m.group("hms").split(":")
        dt_src = datetime(
            year,
            mon,
            day,
            int(hh),
            int(mm),
            int(ss),
            tzinfo=src_zone,
        )
    except (TypeError, ValueError):
        return None
    dt_phx = dt_src.astimezone(_PHOENIX_TZ)
    weekday = dt_phx.strftime("%a")
    hour12 = dt_phx.hour % 12 or 12
    clock = f"{hour12}:{dt_phx.minute:02d} {dt_phx.strftime('%p').strip()}"
    # Arizona (Phoenix); label AZ (Masters local convention).
    return f"{weekday} {clock} AZ"


def _round_statistics_tee_raw(round_obj: dict[str, Any]) -> str | None:
    stats = round_obj.get("statistics") or {}
    for cat in stats.get("categories") or []:
        for st in cat.get("stats") or []:
            dv = str(st.get("displayValue") or "").strip()
            if _ESPN_TEE_DATETIME_RE.match(dv):
                return dv
    return None


def _competitor_active_round_tee_phoenix(item: dict[str, Any], meta: dict[str, Any]) -> str | None:
    active_period = meta.get("period")
    if not isinstance(active_period, int) or not (1 <= active_period <= 4):
        return None
    for rnd in item.get("linescores") or []:
        try:
            p = int(rnd.get("period", 0) or 0)
        except (TypeError, ValueError):
            continue
        if p != active_period:
            continue
        raw = _round_statistics_tee_raw(rnd)
        if raw:
            return format_tee_time_phoenix_from_stat_display(raw)
        return None
    return None


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

    def get_competitor_status(self, event_id: str, player_id: int) -> dict[str, Any] | None:
        try:
            response = self._session.get(
                COMPETITOR_STATUS_URL.format(event_id=event_id, player_id=player_id),
                params={"lang": "en", "region": "us"},
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception:  # noqa: BLE001
            LOGGER.debug("competitor_status_failed event=%s player_id=%s", event_id, player_id, exc_info=True)
            return None

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
        status_blob = _competitor_status_blob(item)
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


def extract_competition_meta(scoreboard_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort tournament stage from ESPN scoreboard: current period (round 1–4),
    type state (e.g. pre / in / post), and display detail.
    """
    meta: dict[str, Any] = {"period": None, "typeState": None, "typeName": None, "detail": None}
    events = scoreboard_payload.get("events") or []
    if not events:
        return meta
    comp = (events[0].get("competitions") or [{}])[0]
    st = comp.get("status") or {}
    tu = st.get("type") or {}
    meta["typeState"] = str(tu.get("state") or "").strip().lower() or None
    meta["typeName"] = str(tu.get("name") or "").strip().upper() or None
    meta["detail"] = str(tu.get("detail") or st.get("detail") or "").strip() or None
    try:
        ip = int(st.get("period", 0) or 0)
        if 1 <= ip <= 4:
            meta["period"] = ip
    except (TypeError, ValueError):
        pass
    if meta["period"] is None:
        inferred = _infer_max_period_with_hole_data(scoreboard_payload)
        if inferred is not None:
            meta["period"] = inferred
    return meta


def map_player_tee_times_phoenix_current_period(
    scoreboard_payload: dict[str, Any],
    player_ids: Iterable[int],
    status_overrides: dict[int, str] | None = None,
) -> dict[int, str]:
    """
    For the competition's current period, return tee times (America/Phoenix) keyed by player id
    when ESPN exposes them on the scoreboard round statistics.
    """
    meta = extract_competition_meta(scoreboard_payload)
    events = scoreboard_payload.get("events") or []
    if not events:
        return {}
    competitors = events[0].get("competitions", [{}])[0].get("competitors", [])
    want = {int(pid) for pid in player_ids}
    out: dict[int, str] = {}
    for item in competitors:
        try:
            pid = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if pid not in want:
            continue
        if _competitor_penalty_thru_label(item, status_overrides):
            continue
        tee = _competitor_active_round_tee_phoenix(item, meta)
        if tee:
            out[pid] = tee
    return out


def _infer_max_period_with_hole_data(scoreboard_payload: dict[str, Any]) -> int | None:
    events = scoreboard_payload.get("events") or []
    if not events:
        return None
    competitors = events[0].get("competitions", [{}])[0].get("competitors", [])
    best = 0
    for item in competitors:
        for rnd in item.get("linescores") or []:
            try:
                p = int(rnd.get("period", 0) or 0)
            except (TypeError, ValueError):
                continue
            if p < 1 or p > 4:
                continue
            inner = rnd.get("linescores") or []
            if not inner:
                continue
            if any(_hole_line_has_score(h) for h in inner):
                best = max(best, p)
    return best if best > 0 else None


def _hole_line_has_score(hole: dict[str, Any]) -> bool:
    dv = str(hole.get("displayValue", "")).strip()
    if dv not in ("", "-", "--", "—"):
        return True
    val = hole.get("value")
    if val is None:
        return False
    try:
        return float(val) > 0
    except (TypeError, ValueError):
        return False


def _competitor_status_blob(item: dict[str, Any]) -> str:
    parts: list[str] = []
    st = item.get("status") or {}
    ty = st.get("type") or {}
    for key in ("description", "detail", "shortDetail", "name"):
        v = ty.get(key) or st.get(key)
        if v:
            parts.append(str(v))
    athlete = item.get("athlete") or {}
    ast = athlete.get("status") or {}
    aty = ast.get("type") or {}
    for key in ("description", "detail", "shortDetail", "name"):
        v = aty.get(key) or ast.get(key)
        if v:
            parts.append(str(v))
    return " ".join(parts).upper()


def _merged_status_blob(item: dict[str, Any], status_overrides: dict[int, str] | None = None) -> str:
    base = _competitor_status_blob(item)
    if not status_overrides:
        return base
    try:
        pid = int(item["id"])
    except (KeyError, TypeError, ValueError):
        return base
    extra = str(status_overrides.get(pid, "") or "").strip()
    if not extra:
        return base
    return f"{base} {extra}".strip().upper()


def _competitor_penalty_thru_label(item: dict[str, Any], status_overrides: dict[int, str] | None = None) -> str | None:
    blob = _merged_status_blob(item, status_overrides)
    if not is_penalty_status(blob):
        return None
    t = blob
    if "DISQUAL" in t or " DQ" in f" {t}":
        return "DQ"
    if "WITHDRAW" in t or " W/D" in t or "W/D" in t:
        return "WD"
    return "MC"


def _leaderboard_score_display(score_raw: Any, to_par: int | None) -> str:
    if isinstance(score_raw, str) and score_raw.strip() not in {"", "-", "--", "—"}:
        return score_raw.strip()
    if to_par is None:
        return "--"
    if to_par == 0:
        return "E"
    return f"+{to_par}" if to_par > 0 else str(to_par)


def _thru_display_with_tee_fallback(
    display: str,
    item: dict[str, Any],
    meta: dict[str, Any],
) -> str:
    if display != "--":
        return display
    tee = _competitor_active_round_tee_phoenix(item, meta)
    return tee if tee else "--"


def _competitor_thru_display(
    item: dict[str, Any],
    meta: dict[str, Any] | None = None,
    status_overrides: dict[int, str] | None = None,
) -> str:
    """
    Thru / final for the **tournament's current period** (round), not the last completed round.
    Shows \"--\" when that round has not started yet (e.g. Saturday morning before tee times).
    When ESPN embeds a tee time in round statistics, shows that time in America/Phoenix instead of \"--\".
    """
    pen = _competitor_penalty_thru_label(item, status_overrides)
    if pen:
        return pen
    meta = meta or {}
    active_period = meta.get("period")
    linescores = item.get("linescores") or []
    if not linescores:
        return _thru_display_with_tee_fallback("--", item, meta)

    def played_count(inner: list[dict[str, Any]]) -> int:
        return sum(1 for h in inner if _hole_line_has_score(h))

    if active_period is not None:
        rnd = next((r for r in linescores if int(r.get("period", 0) or 0) == int(active_period)), None)
        if rnd is None:
            return _thru_display_with_tee_fallback("--", item, meta)
        inner = rnd.get("linescores") or []
        if not inner:
            return _thru_display_with_tee_fallback("--", item, meta)
        played = played_count(inner)
        if played <= 0:
            return _thru_display_with_tee_fallback("--", item, meta)
        if played >= 18:
            return "F"
        return f"Thru {played}"

    # Legacy fallback when competition period is unknown.
    for rnd in reversed(linescores):
        dv = rnd.get("displayValue")
        if dv is None or str(dv).strip() in {"", "-", "--", "—"}:
            continue
        inner = rnd.get("linescores") or []
        if inner:
            played = played_count(inner)
            if played >= 18:
                return "F"
            if played > 0:
                return f"Thru {played}"
        return str(dv).strip()[:14]
    return _thru_display_with_tee_fallback("--", item, meta)


def _extract_field_scorecard_from_competitor(item: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build an 18-hole stroke scorecard for the competitor's latest round that has hole rows.
    Shape matches pool UI expectations (holes, holeTypes, out, in, total, round).
    """
    rounds = item.get("linescores") or []
    for rnd in reversed(rounds):
        inner = rnd.get("linescores") or []
        if not inner:
            continue
        period = int(rnd.get("period", 0) or 0)
        if period <= 0:
            continue
        sorted_holes = sorted(inner, key=lambda h: int(h.get("period", 0) or 0))
        scores: list[int] = []
        types: list[str] = []
        for h in sorted_holes[:18]:
            dv_raw = h.get("displayValue")
            dv = str(dv_raw).strip() if dv_raw is not None else ""
            val = h.get("value")
            strokes = 0
            if val is not None and str(val).strip() not in ("", "-", "--", "—"):
                try:
                    strokes = int(float(val))
                except (TypeError, ValueError):
                    strokes = 0
            if strokes <= 0 and dv not in ("", "-", "--", "—"):
                try:
                    strokes = int(float(dv))
                except (TypeError, ValueError):
                    strokes = 0
            st = str((h.get("scoreType") or {}).get("name", "") or "UNKNOWN").upper()
            scores.append(strokes)
            types.append(st)
        while len(scores) < 18:
            scores.append(0)
        while len(types) < 18:
            types.append("")
        scores = scores[:18]
        types = types[:18]
        if not any(s > 0 for s in scores):
            continue
        out_total = sum(v for v in scores[:9] if v > 0)
        in_total = sum(v for v in scores[9:] if v > 0)
        return {
            "round": period,
            "holes": scores,
            "holeTypes": types,
            "out": out_total,
            "in": in_total,
            "total": out_total + in_total,
        }
    return None


def extract_masters_field_leaderboard_top(
    scoreboard_payload: dict[str, Any],
    *,
    limit: int = 10,
    status_overrides: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Full tournament (field) leaders from ESPN scoreboard — not pool participants.
    Sorted by total strokes vs par (lower better). Respects ties (T1, etc.).
    """
    events = scoreboard_payload.get("events", [])
    if not events:
        return []
    competitors = events[0].get("competitions", [{}])[0].get("competitors", [])
    meta = extract_competition_meta(scoreboard_payload)
    rows: list[dict[str, Any]] = []
    competitor_by_id: dict[int, dict[str, Any]] = {}
    for item in competitors:
        try:
            pid = int(item["id"])
        except (KeyError, TypeError, ValueError):
            continue
        competitor_by_id[pid] = item
        name = item.get("athlete", {}).get("displayName") or item.get("athlete", {}).get("fullName") or str(pid)
        score_raw = item.get("score")
        to_par = _parse_to_par(score_raw)
        rows.append(
            {
                "playerId": pid,
                "name": name,
                "toPar": to_par,
                "scoreDisplay": _leaderboard_score_display(score_raw, to_par),
                "thru": _competitor_thru_display(item, meta, status_overrides),
            }
        )

    scored = [r for r in rows if r["toPar"] is not None]
    if not scored:
        return []

    scored.sort(key=lambda r: (r["toPar"], r["name"]))
    score_counts: dict[int, int] = {}
    for r in scored:
        tp = r["toPar"]
        if tp is None:
            continue
        score_counts[tp] = score_counts.get(tp, 0) + 1

    score_to_rank: dict[int, int] = {}
    next_rank = 1
    for score_val in sorted(score_counts.keys()):
        score_to_rank[score_val] = next_rank
        next_rank += score_counts[score_val]

    out: list[dict[str, Any]] = []
    for r in scored[:limit]:
        tp = r["toPar"]
        if tp is None:
            continue
        rank = score_to_rank[tp]
        tied = score_counts[tp] > 1
        pos = f"T{rank}" if tied else str(rank)
        entry: dict[str, Any] = {
            "pos": pos,
            "name": r["name"],
            "playerId": r["playerId"],
            "scoreDisplay": r["scoreDisplay"],
            "toPar": tp,
            "thru": r["thru"],
        }
        raw_item = competitor_by_id.get(r["playerId"])
        if raw_item is not None:
            sc = _extract_field_scorecard_from_competitor(raw_item)
            if sc is not None:
                entry["scorecard"] = sc
        out.append(entry)
    return out


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

