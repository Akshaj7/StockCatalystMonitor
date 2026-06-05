"""
Email Command Processor
Reads your Gmail inbox for self-sent command emails and updates config automatically.
Runs every 30 minutes via GitHub Actions.

╔══════════════════════════════════════════════════════════════════════════╗
║  FULL COMMAND REFERENCE                                                  ║
║                                                                          ║
║  Send an email TO YOURSELF with subject containing "monitor" or         ║
║  "command". One command per line.                                        ║
║                                                                          ║
║  ── UPDATE a field ──────────────────────────────────────────────────── ║
║  set target_exit = 90                                                    ║
║  set stop_loss = 45                                                      ║
║  set shares = 20                                                         ║
║  set entry_price = 10.50                                                 ║
║  set position_value = 500                                                ║
║  set AAPL target_exit = 200       (specify ticker for multi-position)   ║
║                                                                          ║
║  ── ADD a new stock ─────────────────────────────────────────────────── ║
║  add AAPL entry=182.50 shares=5 target=220 stop=160                     ║
║  add TSLA entry=250 shares=3 target=400 stop=200 name=Tesla Inc         ║
║                                                                          ║
║  ── REMOVE a stock ──────────────────────────────────────────────────── ║
║  remove AAPL                                                             ║
║                                                                          ║
║  ── INFO commands ───────────────────────────────────────────────────── ║
║  status          (full positions table with prices)                     ║
║  list            (same as status)                                        ║
║  help            (sends back this full command guide)                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import email as emaillib
import imaplib
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, load_positions, setup_logging
from alert_system import send_report_email

logger = setup_logging("email_command")

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
HEADER_BG = "#0D1B2A"

# ── Fields allowed in "set" commands ──────────────────────────────────────────
ALLOWED_FIELDS = {
    "target_exit":    float,
    "stop_loss":      float,
    "entry_price":    float,
    "shares":         float,
    "position_value": float,
}

# ── Field aliases for "add" command (short form → canonical name) ──────────────
ADD_FIELD_ALIASES = {
    "entry":          "entry_price",
    "entry_price":    "entry_price",
    "target":         "target_exit",
    "target_exit":    "target_exit",
    "stop":           "stop_loss",
    "stop_loss":      "stop_loss",
    "shares":         "shares",
    "name":           "company_name",
    "company":        "company_name",
    "company_name":   "company_name",
    "notes":          "notes",
    "thesis":         "notes",
}

# Required fields when adding a new position
ADD_REQUIRED = {"entry_price", "shares", "target_exit", "stop_loss"}

# Subject must contain one of these to be treated as a command email
SUBJECT_TRIGGERS = ["monitor", "command", "set ", "status", "add ", "remove", "help"]


# ─────────────────────────────────────────────────────────────────────────────
# IMAP helpers
# ─────────────────────────────────────────────────────────────────────────────

def _connect(gmail_address: str, app_password: str) -> Optional[imaplib.IMAP4_SSL]:
    try:
        client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        client.login(gmail_address, app_password)
        return client
    except imaplib.IMAP4.error as exc:
        logger.error(f"IMAP login failed: {exc}")
    except Exception as exc:
        logger.error(f"IMAP connection error: {exc}")
    return None


def _decode_str(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw or "")


def _get_plain_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                return _decode_str(part.get_payload(decode=True))
    else:
        return _decode_str(msg.get_payload(decode=True))
    return ""


def _load_processed_uids() -> set:
    path = ROOT / "state" / "processed_command_uids.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8-sig") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def _save_processed_uids(uids: set) -> None:
    path = ROOT / "state" / "processed_command_uids.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(list(uids), f)


def _strip_quoted_reply(body: str) -> str:
    clean_lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "--":
            break
        if stripped.startswith(">"):
            continue
        if re.match(r"^On .{5,80}wrote:$", stripped, re.IGNORECASE):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


def _has_any_command(body: str) -> bool:
    bl = body.lower()
    return bool(
        re.search(r"\bset\s+\w+\s*=\s*[0-9]", bl)
        or re.search(r"^status\s*$", bl, re.MULTILINE)
        or re.search(r"^list\s*$", bl, re.MULTILINE)
        or re.search(r"^help\s*$", bl, re.MULTILINE)
        or re.search(r"^add\s+[A-Z]{1,5}\b", bl, re.MULTILINE)
        or re.search(r"^remove\s+[A-Z]{1,5}\b", bl, re.MULTILINE)
    )


def _fetch_command_emails(client: imaplib.IMAP4_SSL, from_address: str) -> list[dict]:
    from datetime import timedelta
    processed = _load_processed_uids()
    since_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")

    folders = [("INBOX", "INBOX"), ("[Gmail]/Sent Mail", "SENT")]
    results = []
    seen_message_ids: set = set()

    for folder_path, folder_key in folders:
        try:
            status, _ = client.select(f'"{folder_path}"')
            if status != "OK":
                continue
        except Exception:
            continue

        status, data = client.search(None, f'FROM "{from_address}" SINCE {since_date}')
        if status != "OK" or not data[0]:
            continue

        for uid in data[0].split():
            uid_str = uid.decode() if isinstance(uid, bytes) else str(uid)
            folder_uid_key = f"{folder_key}:{uid_str}"
            if folder_uid_key in processed:
                continue

            status, msg_data = client.fetch(uid, "(RFC822)")
            if status != "OK":
                continue

            msg = emaillib.message_from_bytes(msg_data[0][1])

            message_id = msg.get("Message-ID", "")
            if message_id and message_id in seen_message_ids:
                processed.add(folder_uid_key)
                continue
            if message_id:
                seen_message_ids.add(message_id)

            raw_subject = msg.get("Subject", "")
            subject = ""
            for part, enc in decode_header(raw_subject):
                subject += _decode_str(
                    part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
                )

            raw_body  = _get_plain_body(msg)
            clean_body = _strip_quoted_reply(raw_body)

            if not _has_any_command(clean_body):
                processed.add(folder_uid_key)
                continue

            results.append({
                "uid": uid,
                "uid_str": uid_str,
                "folder_uid_key": folder_uid_key,
                "subject": subject,
                "body": clean_body,
            })
            logger.info(f"Command email queued [{folder_key}]: '{subject}'")

    _save_processed_uids(processed)
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Command parser
# ─────────────────────────────────────────────────────────────────────────────

def _parse_commands(body: str, default_ticker: str = "DXYZ") -> list[dict]:
    """
    Parse all command lines from the email body.

    Supported commands:
      set target_exit = 90
      set stop_loss = 45
      set shares = 20
      set entry_price = 10.50
      set AAPL target_exit = 200
      add AAPL entry=182.50 shares=5 target=220 stop=160
      add AAPL entry=182.50 shares=5 target=220 stop=160 name=Apple Inc
      remove AAPL
      status
      list
      help
    """
    commands = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(">") or line.startswith("--"):
            continue

        line_lower = line.lower()

        # ── status / list ──────────────────────────────────────────────────
        if re.match(r"^(status|list)\s*$", line, re.IGNORECASE):
            commands.append({"type": "status"})
            continue

        # ── help ───────────────────────────────────────────────────────────
        if re.match(r"^help\s*$", line, re.IGNORECASE):
            commands.append({"type": "help"})
            continue

        # ── remove TICKER ─────────────────────────────────────────────────
        m = re.match(r"^remove\s+([A-Z0-9]{1,6})\s*$", line, re.IGNORECASE)
        if m:
            commands.append({"type": "remove", "ticker": m.group(1).upper()})
            continue

        # ── add TICKER key=value ... ───────────────────────────────────────
        m = re.match(r"^add\s+([A-Z0-9]{1,6})\s*(.*)?$", line, re.IGNORECASE)
        if m:
            ticker = m.group(1).upper()
            rest   = m.group(2) or ""
            fields: dict = {}
            errors_local: list = []

            # Parse key=value pairs — value may contain spaces (for name=Apple Inc)
            # Strategy: find all key=value tokens; last one may grab rest of line
            tokens = re.findall(r'(\w+)\s*=\s*("([^"]*)"|([\w\s.]+?)(?=\s+\w+=|$))', rest)
            for tok in tokens:
                alias = tok[0].lower()
                raw_val = (tok[2] or tok[3]).strip()
                canonical = ADD_FIELD_ALIASES.get(alias)
                if not canonical:
                    errors_local.append(f"Unknown field '{alias}' in add command")
                    continue
                if canonical == "company_name" or canonical == "notes":
                    fields[canonical] = raw_val
                else:
                    try:
                        fields[canonical] = float(raw_val)
                    except ValueError:
                        errors_local.append(f"'{raw_val}' is not a valid number for {alias}")

            commands.append({
                "type":   "add",
                "ticker": ticker,
                "fields": fields,
                "errors": errors_local,
            })
            continue

        # ── set TICKER FIELD = VALUE ───────────────────────────────────────
        m = re.match(
            r"^set\s+([A-Z]{2,6})\s+(\w+)\s*=\s*([0-9]+(?:\.[0-9]+)?)$",
            line, re.IGNORECASE,
        )
        if m:
            field = m.group(2).lower()
            if field in ALLOWED_FIELDS:
                commands.append({
                    "type": "set", "ticker": m.group(1).upper(),
                    "field": field, "value": float(m.group(3)),
                })
            else:
                commands.append({"type": "error", "message": f"Unknown field: '{m.group(2)}'. Allowed: {', '.join(ALLOWED_FIELDS)}"})
            continue

        # ── set FIELD = VALUE ──────────────────────────────────────────────
        m = re.match(
            r"^set\s+(\w+)\s*=\s*([0-9]+(?:\.[0-9]+)?)$",
            line, re.IGNORECASE,
        )
        if m:
            field = m.group(1).lower()
            if field in ALLOWED_FIELDS:
                commands.append({
                    "type": "set", "ticker": default_ticker,
                    "field": field, "value": float(m.group(2)),
                })
            else:
                commands.append({"type": "error", "message": f"Unknown field: '{m.group(1)}'. Allowed: {', '.join(ALLOWED_FIELDS)}"})
            continue

        # ── TICKER FIELD = VALUE ───────────────────────────────────────────
        m = re.match(
            r"^([A-Z]{2,6})\s+(\w+)\s*=\s*([0-9]+(?:\.[0-9]+)?)$",
            line, re.IGNORECASE,
        )
        if m:
            field = m.group(2).lower()
            if field in ALLOWED_FIELDS:
                commands.append({
                    "type": "set", "ticker": m.group(1).upper(),
                    "field": field, "value": float(m.group(3)),
                })
            else:
                commands.append({"type": "error", "message": f"Unknown field: '{m.group(2)}'"})
            continue

    return commands


# ─────────────────────────────────────────────────────────────────────────────
# Apply changes
# ─────────────────────────────────────────────────────────────────────────────

def _load_positions_data() -> tuple[dict, list]:
    path = ROOT / "config" / "positions.json"
    with open(path) as f:
        data = json.load(f)
    return data, data.get("positions", [])


def _save_positions_data(data: dict) -> None:
    path = ROOT / "config" / "positions.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("positions.json saved.")


def _apply_set_commands(commands: list[dict]) -> tuple[list[str], list[str]]:
    data, positions = _load_positions_data()
    successes, errors = [], []
    changed = False

    for cmd in commands:
        if cmd["type"] != "set":
            continue
        ticker = cmd["ticker"]
        field  = cmd["field"]
        value  = cmd["value"]
        pos = next((p for p in positions if p.get("ticker", "").upper() == ticker), None)
        if not pos:
            errors.append(f"${ticker} not found in your positions.")
            continue
        old = pos.get(field, "not set")
        pos[field] = ALLOWED_FIELDS[field](value)
        successes.append(f"${ticker}  {field}:  {old}  →  {value}")
        logger.info(f"Updated: ${ticker} {field} = {value}  (was {old})")
        changed = True

    if changed:
        _save_positions_data(data)
    return successes, errors


def _apply_add_command(cmd: dict) -> tuple[str, str]:
    """
    Add a new position to positions.json.
    Returns (success_msg, error_msg) — one will be empty.
    """
    ticker = cmd["ticker"]
    fields = cmd.get("fields", {})
    parse_errors = cmd.get("errors", [])

    if parse_errors:
        return "", f"Parse errors for add {ticker}: {'; '.join(parse_errors)}"

    # Validate required fields
    missing = ADD_REQUIRED - set(fields.keys())
    if missing:
        return "", (
            f"Cannot add ${ticker} — missing required fields: "
            f"{', '.join(sorted(missing))}. "
            f"Format: add {ticker} entry=X shares=X target=X stop=X"
        )

    data, positions = _load_positions_data()

    # Check if already exists
    if any(p.get("ticker", "").upper() == ticker for p in positions):
        return "", f"${ticker} already exists. Use 'set {ticker} field = value' to update it."

    entry  = float(fields["entry_price"])
    shares = float(fields["shares"])

    new_pos = {
        "ticker":           ticker,
        "company_name":     fields.get("company_name", ticker),
        "entry_price":      entry,
        "shares":           shares,
        "position_value":   round(entry * shares, 2),
        "thesis_type":      "manual",
        "thesis_description": fields.get("notes", ""),
        "target_exit":      float(fields["target_exit"]),
        "stop_loss":        float(fields["stop_loss"]),
        "date_entered":     datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "instant_alert_triggers": [],
        "sell_signals":     [],
        "monitor_frequency_minutes": 30,
        "notes":            fields.get("notes", "Added via email command."),
    }

    positions.append(new_pos)
    data["positions"] = positions
    _save_positions_data(data)

    logger.info(f"Added new position: ${ticker}")
    return (
        f"${ticker} added — entry ${entry:.2f} × {int(shares)} shares, "
        f"target ${fields['target_exit']:.2f}, stop ${fields['stop_loss']:.2f}",
        ""
    )


def _apply_remove_command(ticker: str) -> tuple[str, str]:
    """
    Remove a position from positions.json.
    Returns (success_msg, error_msg).
    """
    data, positions = _load_positions_data()

    original_count = len(positions)
    data["positions"] = [p for p in positions if p.get("ticker", "").upper() != ticker]

    if len(data["positions"]) == original_count:
        return "", f"${ticker} not found in your positions."

    _save_positions_data(data)
    logger.info(f"Removed position: ${ticker}")
    return f"${ticker} removed from positions.", ""


# ─────────────────────────────────────────────────────────────────────────────
# Confirmation & response emails
# ─────────────────────────────────────────────────────────────────────────────

COMMAND_GUIDE_HTML = """
<div style="background:#F8F9FA;border-left:3px solid #3498DB;
            padding:14px 16px;margin-top:16px;font-size:12px;color:#555;
            font-family:monospace;line-height:1.8;">
  <b style="font-family:Arial;font-size:13px;color:#2C3E50;">Full Command Reference</b><br><br>

  <b style="color:#27AE60;">── UPDATE a field ─────────────────────────</b><br>
  set target_exit = 90<br>
  set stop_loss = 45<br>
  set shares = 20<br>
  set entry_price = 10.50<br>
  set position_value = 500<br>
  set AAPL target_exit = 200 &nbsp;<i style="color:#888;">(specify ticker)</i><br><br>

  <b style="color:#3498DB;">── ADD a new stock ─────────────────────────</b><br>
  add AAPL entry=182.50 shares=5 target=220 stop=160<br>
  add TSLA entry=250 shares=3 target=400 stop=200 name=Tesla Inc<br><br>

  <b style="color:#E74C3C;">── REMOVE a stock ──────────────────────────</b><br>
  remove AAPL<br><br>

  <b style="color:#8E44AD;">── INFO ────────────────────────────────────</b><br>
  status &nbsp;&nbsp;<i style="color:#888;">(full positions table)</i><br>
  list &nbsp;&nbsp;&nbsp;&nbsp;<i style="color:#888;">(same as status)</i><br>
  help &nbsp;&nbsp;&nbsp;&nbsp;<i style="color:#888;">(sends this guide)</i><br><br>

  <span style="font-family:Arial;font-size:11px;color:#999;">
  Changes take effect on the next 30-min scan cycle.
  </span>
</div>"""


def _send_confirmation(
    successes: list,
    errors: list,
    parse_errors: list,
    original_subject: str,
) -> None:
    now = datetime.now(timezone.utc).strftime("%B %d %Y  %H:%M UTC")
    rows_html = ""

    for s in successes:
        rows_html += (
            f"<tr><td style='padding:8px 12px;border-bottom:1px solid #eee;"
            f"font-size:13px;color:#1E8449;'>&#10003; {s}</td></tr>"
        )
    for e in errors + parse_errors:
        rows_html += (
            f"<tr><td style='padding:8px 12px;border-bottom:1px solid #eee;"
            f"font-size:13px;color:#C0392B;'>&#10007; {e}</td></tr>"
        )

    if not rows_html:
        rows_html = (
            "<tr><td style='padding:8px 12px;font-size:13px;color:#888;'>"
            "No valid commands found. See format guide below.</td></tr>"
        )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">
      <div style="background:{HEADER_BG};padding:18px;text-align:center;color:white;">
        <div style="font-size:18px;font-weight:bold;">COMMAND CONFIRMED</div>
        <div style="font-size:11px;opacity:0.7;margin-top:4px;">{now}</div>
      </div>
      <div style="padding:16px;">
        <p style="font-size:12px;color:#888;">In reply to: <i>{original_subject}</i></p>
        <table style="width:100%;border-collapse:collapse;border:1px solid #eee;">
          {rows_html}
        </table>
        {COMMAND_GUIDE_HTML}
      </div>
    </div>"""

    send_report_email("Command Confirmed — Stock Monitor", html)


def _send_status_email(positions: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%B %d %Y  %H:%M UTC")
    rows = ""
    for p in positions:
        ticker = p.get("ticker", "")
        pv = p.get("entry_price", 0) * p.get("shares", 0)
        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:8px 10px;font-weight:bold;">${ticker}</td>
          <td style="padding:8px 10px;font-size:12px;">{p.get('company_name','')}</td>
          <td style="padding:8px 10px;">${p.get('entry_price','—')}</td>
          <td style="padding:8px 10px;color:#27AE60;font-weight:bold;">${p.get('target_exit','—')}</td>
          <td style="padding:8px 10px;color:#E74C3C;font-weight:bold;">${p.get('stop_loss','—')}</td>
          <td style="padding:8px 10px;">{int(p.get('shares', 0))}</td>
          <td style="padding:8px 10px;color:#888;">${pv:,.0f}</td>
        </tr>"""

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;">
      <div style="background:{HEADER_BG};padding:18px;text-align:center;color:white;">
        <div style="font-size:18px;font-weight:bold;">POSITIONS STATUS</div>
        <div style="font-size:11px;opacity:0.7;margin-top:4px;">{now}</div>
      </div>
      <div style="padding:16px;">
        <table style="width:100%;border-collapse:collapse;border:1px solid #eee;">
          <thead>
            <tr style="background:#F0F0F0;font-size:11px;color:#888;text-transform:uppercase;">
              <th style="padding:8px 10px;text-align:left;">Ticker</th>
              <th style="padding:8px 10px;text-align:left;">Company</th>
              <th style="padding:8px 10px;text-align:left;">Entry</th>
              <th style="padding:8px 10px;text-align:left;">Target</th>
              <th style="padding:8px 10px;text-align:left;">Stop</th>
              <th style="padding:8px 10px;text-align:left;">Shares</th>
              <th style="padding:8px 10px;text-align:left;">Value</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        {COMMAND_GUIDE_HTML}
      </div>
    </div>"""

    send_report_email("Positions Status — Stock Monitor", html)


def _send_help_email() -> None:
    now = datetime.now(timezone.utc).strftime("%B %d %Y  %H:%M UTC")
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;">
      <div style="background:{HEADER_BG};padding:18px;text-align:center;color:white;">
        <div style="font-size:18px;font-weight:bold;">COMMAND HELP</div>
        <div style="font-size:11px;opacity:0.7;margin-top:4px;">{now}</div>
      </div>
      <div style="padding:16px;">
        <p style="font-size:13px;color:#555;">
          Send any of the commands below in an email to yourself.<br>
          Subject must contain <b>monitor</b> or <b>command</b>.
        </p>
        {COMMAND_GUIDE_HTML}
      </div>
    </div>"""
    send_report_email("Command Help — Stock Monitor", html)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────

def process_command_emails() -> int:
    gmail_address = os.getenv("GMAIL_ADDRESS", "")
    app_password  = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")

    if not gmail_address or not app_password:
        logger.error("GMAIL_ADDRESS or GMAIL_APP_PASSWORD not set.")
        return 0

    client = _connect(gmail_address, app_password)
    if not client:
        return 0

    msgs = _fetch_command_emails(client, gmail_address)
    if not msgs:
        logger.info("No command emails found.")
        client.logout()
        return 0

    total = 0
    for msg in msgs:
        commands = _parse_commands(msg["body"])
        successes, errors = [], []

        for cmd in commands:
            ctype = cmd["type"]

            if ctype == "status":
                _send_status_email(load_positions())

            elif ctype == "help":
                _send_help_email()

            elif ctype == "set":
                ok, err = _apply_set_commands([cmd])
                successes.extend(ok)
                errors.extend(err)
                total += 1

            elif ctype == "add":
                ok_msg, err_msg = _apply_add_command(cmd)
                if ok_msg:
                    successes.append(ok_msg)
                    total += 1
                if err_msg:
                    errors.append(err_msg)

            elif ctype == "remove":
                ok_msg, err_msg = _apply_remove_command(cmd["ticker"])
                if ok_msg:
                    successes.append(ok_msg)
                    total += 1
                if err_msg:
                    errors.append(err_msg)

            elif ctype == "error":
                errors.append(cmd["message"])

        parse_errors = []
        _send_confirmation(successes, errors, parse_errors, msg["subject"])
        logger.info(f"Processed {total} command(s) from '{msg['subject']}'")

        # Mark as processed
        processed = _load_processed_uids()
        processed.add(msg["folder_uid_key"])
        _save_processed_uids(processed)

    client.logout()
    return total


def main():
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    n = process_command_emails()
    print(f"Done. {n} command(s) processed.")


if __name__ == "__main__":
    main()
