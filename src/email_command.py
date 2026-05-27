"""
Email Command Processor
Reads your Gmail inbox for self-sent command emails and updates config automatically.
Runs every 30 minutes via GitHub Actions.

HOW TO USE:
  Send an email to YOURSELF (same address you configured in settings).
  Subject:  MONITOR COMMAND  (must contain "monitor" or "command" — case-insensitive)
  Body:     One command per line. Examples:

    set target_exit = 80
    set stop_loss = 45
    set shares = 15
    set entry_price = 10.50
    set DXYZ target_exit = 80      (explicit ticker if you have multiple positions)
    status                          (sends back a full positions summary)

After processing, you receive a confirmation email listing every change made.
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

# Fields the user is allowed to update via email
ALLOWED_FIELDS = {
    "target_exit":    float,
    "stop_loss":      float,
    "entry_price":    float,
    "shares":         float,
    "position_value": float,
}

# Subject must contain one of these words (case-insensitive) to be treated as a command email
SUBJECT_TRIGGERS = ["monitor", "command", "set ", "status"]

HEADER_BG = "#0D1B2A"


# ---------------------------------------------------------------------------
# IMAP helpers
# ---------------------------------------------------------------------------

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
    """Extract plain-text body from an email.Message object."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                return _decode_str(payload)
    else:
        payload = msg.get_payload(decode=True)
        return _decode_str(payload)
    return ""


def _load_processed_uids() -> set:
    """Load previously processed email UIDs to avoid reprocessing."""
    path = ROOT / "state" / "processed_command_uids.json"
    if path.exists():
        return set(json.load(open(path)))
    return set()


def _save_processed_uids(uids: set) -> None:
    path = ROOT / "state" / "processed_command_uids.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    json.dump(list(uids), open(path, "w"))


def _strip_quoted_reply(body: str) -> str:
    """
    Remove quoted reply text so we only parse the NEW lines the user typed.
    Strips:  lines starting with '>'
             Gmail/Outlook 'On ... wrote:' reply headers
             everything after a '-- ' signature separator
    """
    clean_lines = []
    for line in body.splitlines():
        stripped = line.strip()
        # Stop at signature separator
        if stripped == "--":
            break
        # Skip quoted lines
        if stripped.startswith(">"):
            continue
        # Skip "On Mon, 26 May ... wrote:" reply headers (single or multi-line)
        if re.match(r"^On .{5,80}wrote:$", stripped, re.IGNORECASE):
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines)


def _has_any_command(body: str) -> bool:
    """Quick check: does the body contain at least one parseable command?"""
    body_lower = body.lower()
    return (
        re.search(r"\bset\s+\w+\s*=\s*[0-9]", body_lower) is not None
        or re.search(r"^status\s*$", body_lower, re.MULTILINE) is not None
    )


def _fetch_command_emails(client: imaplib.IMAP4_SSL, from_address: str) -> list[dict]:
    """
    Search INBOX and Sent Mail for self-sent command emails.
    Replies go to Sent Mail (not INBOX) in Gmail, so we check both.
    Uses folder-prefixed UID keys (e.g. "INBOX:21092", "SENT:995") to avoid
    processing the same message twice across folders.
    Each returned item: {uid, uid_str, folder_uid_key, subject, body}
    """
    from datetime import timedelta
    processed = _load_processed_uids()

    # Only look at emails from the last 7 days to keep searches fast
    since_date = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%d-%b-%Y")

    folders = [
        ("INBOX",               "INBOX"),
        ("[Gmail]/Sent Mail",   "SENT"),
    ]

    results = []
    seen_message_ids: set = set()  # deduplicate across folders by Message-ID header

    for folder_path, folder_key in folders:
        try:
            status, _ = client.select(f'"{folder_path}"')
            if status != "OK":
                continue
        except Exception:
            continue

        status, data = client.search(
            None, f'FROM "{from_address}" SINCE {since_date}'
        )
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

            # Deduplicate: same email can appear in both INBOX and Sent Mail
            message_id = msg.get("Message-ID", "")
            if message_id and message_id in seen_message_ids:
                processed.add(folder_uid_key)
                continue
            if message_id:
                seen_message_ids.add(message_id)

            # Decode subject
            raw_subject = msg.get("Subject", "")
            subject = ""
            for part, enc in decode_header(raw_subject):
                subject += _decode_str(
                    part.decode(enc or "utf-8", errors="replace") if isinstance(part, bytes) else part
                )

            raw_body = _get_plain_body(msg)
            clean_body = _strip_quoted_reply(raw_body)

            # Silently skip emails with no commands
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


# ---------------------------------------------------------------------------
# Command parser
# ---------------------------------------------------------------------------

def _parse_commands(body: str, default_ticker: str = "DXYZ") -> list[dict]:
    """
    Parse command lines from email body.

    Supported formats (all case-insensitive):
      set target_exit = 80
      set stop_loss = 45
      set shares = 15
      set DXYZ target_exit = 80
      DXYZ target_exit = 80
      status
    """
    commands = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(">") or line.startswith("--"):
            continue  # skip quoted replies and signature separators

        # status command
        if re.match(r"^status\s*$", line, re.IGNORECASE):
            commands.append({"type": "status"})
            continue

        # Pattern A: "set TICKER FIELD = VALUE"  e.g. "set DXYZ target_exit = 80"
        m = re.match(
            r"^set\s+([A-Z]{2,5})\s+(\w+)\s*=\s*([0-9]+(?:\.[0-9]+)?)$",
            line, re.IGNORECASE,
        )
        if m:
            field = m.group(2).lower()
            if field in ALLOWED_FIELDS:
                commands.append({
                    "type": "set",
                    "ticker": m.group(1).upper(),
                    "field": field,
                    "value": float(m.group(3)),
                })
            else:
                commands.append({"type": "error", "message": f"Unknown field: '{m.group(2)}'"})
            continue

        # Pattern B: "set FIELD = VALUE"  e.g. "set target_exit = 80"
        m = re.match(
            r"^set\s+(\w+)\s*=\s*([0-9]+(?:\.[0-9]+)?)$",
            line, re.IGNORECASE,
        )
        if m:
            field = m.group(1).lower()
            if field in ALLOWED_FIELDS:
                commands.append({
                    "type": "set",
                    "ticker": default_ticker,
                    "field": field,
                    "value": float(m.group(2)),
                })
            else:
                commands.append({"type": "error", "message": f"Unknown field: '{m.group(1)}'"})
            continue

        # Pattern C: "TICKER FIELD = VALUE"  e.g. "DXYZ target_exit = 80"
        m = re.match(
            r"^([A-Z]{2,5})\s+(\w+)\s*=\s*([0-9]+(?:\.[0-9]+)?)$",
            line, re.IGNORECASE,
        )
        if m:
            field = m.group(2).lower()
            if field in ALLOWED_FIELDS:
                commands.append({
                    "type": "set",
                    "ticker": m.group(1).upper(),
                    "field": field,
                    "value": float(m.group(3)),
                })
            else:
                commands.append({"type": "error", "message": f"Unknown field: '{m.group(2)}'"})
            continue

    return commands


# ---------------------------------------------------------------------------
# Apply changes
# ---------------------------------------------------------------------------

def _apply_set_commands(commands: list[dict]) -> tuple[list[str], list[str]]:
    """
    Apply 'set' commands to positions.json.
    Returns (success_lines, error_lines).
    """
    positions_path = ROOT / "config" / "positions.json"
    with open(positions_path) as f:
        data = json.load(f)

    positions = data.get("positions", [])
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
        with open(positions_path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info("positions.json saved with updates.")

    return successes, errors


# ---------------------------------------------------------------------------
# Confirmation emails
# ---------------------------------------------------------------------------

def _send_confirmation(successes: list, errors: list, parse_errors: list,
                        original_subject: str) -> None:
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
            "No valid commands were found. See format guide below.</td></tr>"
        )

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:520px;margin:0 auto;">
      <div style="background:{HEADER_BG};padding:18px;text-align:center;color:white;">
        <div style="font-size:18px;font-weight:bold;">COMMAND CONFIRMED</div>
        <div style="font-size:11px;opacity:0.7;margin-top:4px;">{now}</div>
      </div>
      <div style="padding:16px;">
        <p style="font-size:12px;color:#888;">In reply to: <i>{original_subject}</i></p>
        <table style="width:100%;border-collapse:collapse;border:1px solid #eee;">
          {rows_html}
        </table>
        <div style="background:#F8F9FA;border-left:3px solid #3498DB;
                    padding:12px;margin-top:16px;font-size:12px;color:#555;">
          <b>Command format reminder:</b><br><br>
          <code>set target_exit = 90</code><br>
          <code>set stop_loss = 50</code><br>
          <code>set shares = 20</code><br>
          <code>set entry_price = 10.50</code><br>
          <code>set DXYZ target_exit = 90</code>&nbsp; (use ticker for multiple positions)<br>
          <code>status</code>&nbsp; (get full positions summary)<br>
          <br>
          Changes take effect on the next scheduled scan.
        </div>
      </div>
    </div>"""

    send_report_email(f"Command Confirmed — Stock Monitor", html)


def _send_status_email(positions: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%B %d %Y  %H:%M UTC")
    rows = ""
    for p in positions:
        ticker = p.get("ticker", "")
        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:8px 10px;font-weight:bold;">${ticker}</td>
          <td style="padding:8px 10px;font-size:12px;">{p.get('company_name','')}</td>
          <td style="padding:8px 10px;">${p.get('entry_price','—')}</td>
          <td style="padding:8px 10px;color:#27AE60;font-weight:bold;">${p.get('target_exit','—')}</td>
          <td style="padding:8px 10px;color:#E74C3C;font-weight:bold;">${p.get('stop_loss','—')}</td>
          <td style="padding:8px 10px;">{int(p.get('shares', 0))}</td>
        </tr>"""

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:580px;margin:0 auto;">
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
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>
        <div style="background:#F8F9FA;border-left:3px solid #3498DB;
                    padding:12px;margin-top:16px;font-size:12px;color:#555;">
          <b>To update any value, email yourself with subject containing "command":</b><br><br>
          <code>set target_exit = 90</code><br>
          <code>set stop_loss = 50</code><br>
          <code>set shares = 20</code>
        </div>
      </div>
    </div>"""

    send_report_email("Positions Status — Stock Monitor", html)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

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

        # Handle status
        if any(c["type"] == "status" for c in commands):
            _send_status_email(load_positions())

        # Handle set commands
        set_cmds   = [c for c in commands if c["type"] == "set"]
        err_cmds   = [c["message"] for c in commands if c["type"] == "error"]

        successes, apply_errors = _apply_set_commands(set_cmds) if set_cmds else ([], [])
        _send_confirmation(successes, apply_errors, err_cmds, msg["subject"])

        total += len(set_cmds)
        logger.info(f"Processed {len(set_cmds)} command(s) from '{msg['subject']}'")

        # Record UID so we never process this email again
        processed = _load_processed_uids()
        processed.add(msg["uid_str"])
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
