"""Entry point — initialize SQLite, load config, launch the Tk main window."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))

    from sorter import appenv, paths
    from sorter.config import Config
    from sorter.db import Database
    from sorter.ui.app import MainWindow

    # Developer overrides (community API base URL / TLS trust). Silent unless
    # something is actually configured — see sorter/appenv.py and .env.example.
    for line in appenv.startup_report(appenv.load_dotenv()):
        print(f"[casesorter] {line}")

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
