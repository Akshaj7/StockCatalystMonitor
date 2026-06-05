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


# ─────────────────────────────────────────────────────────────────────────────
# Shared email footer — appended to every outgoing email
# ─────────────────────────────────────────────────────────────────────────────

COMMAND_FOOTER_HTML = """
<div style="margin-top:24px;border-top:1px solid #E0E0E0;padding-top:16px;">
  <div style="font-size:11px;font-weight:bold;color:#888;letter-spacing:1px;
              text-transform:uppercase;margin-bottom:10px;">
    Quick Commands &mdash; Email yourself with subject <span style="color:#3498DB;">"MONITOR COMMAND"</span>
  </div>
  <table style="width:100%;border-collapse:collapse;font-size:12px;font-family:monospace;">
    <tr>
      <td style="padding:3px 8px;width:50%;vertical-align:top;">
        <span style="color:#27AE60;font-weight:bold;">UPDATE</span><br>
        <code>set target_exit = 90</code><br>
        <code>set stop_loss = 45</code><br>
        <code>set shares = 20</code><br>
        <code>set entry_price = 10.50</code><br>
        <code>set AAPL target_exit = 200</code>
      </td>
      <td style="padding:3px 8px;width:50%;vertical-align:top;">
        <span style="color:#3498DB;font-weight:bold;">MANAGE</span><br>
        <code>add AAPL entry=182 shares=5 target=220 stop=160</code><br>
        <code>remove AAPL</code><br><br>
        <span style="color:#8E44AD;font-weight:bold;">INFO</span><br>
        <code>status</code> &nbsp;&middot;&nbsp;
        <code>list</code> &nbsp;&middot;&nbsp;
        <code>help</code>
      </td>
    </tr>
  </table>
</div>"""
