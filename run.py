from __future__ import annotations

from pathlib import Path

from app.web import create_app


def main() -> None:
    base_dir = Path(__file__).resolve().parent
    app = create_app(base_dir=base_dir)
    app.run(host="127.0.0.1", port=5055, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

