"""Entry point — initialize SQLite, load config, launch the Tk main window."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))

    from sorter import paths
    from sorter.config import Config
    from sorter.db import Database
    from sorter.ui.app import MainWindow

    paths.ensure_directories()
    legacy_json = here / "data" / "config.json"

    db = Database()
    db.ensure_initialized(legacy_config_json=legacy_json if legacy_json.exists() else None)

    config = Config(db).load()
    MainWindow(config).run()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
