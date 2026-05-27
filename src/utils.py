"""Shared helper functions used by all modules."""

import json
import logging
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent


def setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return logging.getLogger(name)


def load_settings() -> dict:
    with open(ROOT / "config" / "settings.json") as f:
        return json.load(f)


def load_positions() -> list:
    with open(ROOT / "config" / "positions.json") as f:
        return json.load(f).get("positions", [])


def load_sent_alerts() -> dict:
    path = ROOT / "state" / "sent_alerts.json"
    if not path.exists():
        return {"sent_alerts": [], "last_updated": None}
    try:
        # Open with utf-8-sig to strip BOM if present
        with open(path, encoding="utf-8-sig") as f:
            content = f.read().strip()
        if not content:
            return {"sent_alerts": [], "last_updated": None}
        return json.loads(content)
    except (json.JSONDecodeError, OSError):
        return {"sent_alerts": [], "last_updated": None}


def save_sent_alerts(data: dict) -> None:
    from datetime import datetime, timezone
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    path = ROOT / "state" / "sent_alerts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def get_env(key: str, required: bool = True) -> str:
    val = os.getenv(key, "")
    if required and not val:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    return val
