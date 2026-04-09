from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.service import PoolService


def _is_active_play_window(now_utc: datetime) -> bool:
    # Approximate daily active window for US Masters coverage (10:00-23:00 UTC).
    return 10 <= now_utc.hour <= 23


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    config_path = base_dir / "data" / "pool_config.json"
    if not config_path.exists():
        config_path = base_dir / "data" / "pool_config.example.json"

    config = load_config(config_path)
    service = PoolService(base_dir=base_dir, config=config)

    try:
        with service.store.acquire_loop_lock(blocking=False):
            while True:
                now = datetime.now(UTC)
                interval = (
                    config.poll_interval_seconds_live
                    if _is_active_play_window(now)
                    else config.poll_interval_seconds_idle
                )
                try:
                    state = service.poll_once()
                    print(
                        f"[{state['updatedAt']}] ok "
                        f"degraded={state.get('degradedMode', False)} "
                        f"errors={len(state.get('errors', []))}"
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[{now.isoformat()}] poll failed: {exc}")
                time.sleep(interval)
    except RuntimeError as exc:
        raise SystemExit(f"poll_loop already running: {exc}")


if __name__ == "__main__":
    main()

