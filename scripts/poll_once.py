from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import load_config
from app.service import PoolService


def main() -> None:
    base_dir = Path(__file__).resolve().parents[1]
    config_path = base_dir / "data" / "pool_config.json"
    if not config_path.exists():
        config_path = base_dir / "data" / "pool_config.example.json"
    config = load_config(config_path)
    service = PoolService(base_dir=base_dir, config=config)
    state = service.poll_once()
    print(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()

