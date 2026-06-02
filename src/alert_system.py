"""
Phase 4: Alert System
Handles all email and SMS delivery via Gmail SMTP.
"""

import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, load_settings, setup_logging

logger = setup_logging("alert_system")

GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 465  # SSL


def _get_credentials() -> tuple[str, str, str, str]:
    """Return (sender, app_password, recipient, sms_gateway) from env + settings."""
    sender       = os.getenv("GMAIL_ADDRESS", "")
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")
    recipient    = os.getenv("RECIPIENT_EMAIL", sender)
    sms_gateway  = os.getenv("SMS_EMAIL", "")

    # Fall back to settings.json for non-secret values
    if not sender or not recipient:
        settings = load_settings()
        email_cfg = settings.get("email", {})
        sender    = sender    or email_cfg.get("sender", "")
        recipient = recipient or email_cfg.get("recipient", "")
        sms_gateway = sms_gateway or email_cfg.get("sms_gateway", "")

    return sender, app_password, recipient, sms_gateway


def _smtp_send(
    sender: str,
    app_password: str,
    to_address: str,
    subject: str,
    body_html: Optional[str] = None,
    body_text: Optional[str] = None,
) -> bool:
    """
    Low-level SMTP send. Returns True if ALL recipients succeeded.
    to_address may be a single address or a comma-separated list.
    """
    if not sender or not app_password:
        logger.error("Gmail credentials not set (GMAIL_ADDRESS / GMAIL_APP_PASSWORD).")
        return False
    if not to_address:
        logger.error("No recipient address — skipping send.")
        return False

    # Support comma-separated recipient list — send individually for reliability
    recipients = [a.strip() for a in to_address.split(",") if a.strip()]

    all_ok = True
    try:
        with smtplib.SMTP_SSL(GMAIL_HOST, GMAIL_PORT, timeout=30) as server:
            server.login(sender, app_password)
            for addr in recipients:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"]    = f"Stock Monitor <{sender}>"
                msg["To"]      = addr
                if body_text:
                    msg.attach(MIMEText(body_text, "plain", "utf-8"))
                if body_html:
                    msg.attach(MIMEText(body_html, "html", "utf-8"))
                try:
                    server.sendmail(sender, addr, msg.as_string())
                    logger.info(f"Email sent → {addr}  |  Subject: {subject}")
                except smtplib.SMTPException as exc:
                    logger.error(f"Failed to send to {addr}: {exc}")
                    all_ok = False
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. "
            "Check that GMAIL_APP_PASSWORD is the 16-char App Password, not your Gmail login."
        )
        return False
    except Exception as exc:
        logger.error(f"Unexpected error sending email: {exc}")
        return False
    return all_ok


# ---------------------------------------------------------------------------
# Public send functions
# ---------------------------------------------------------------------------

def send_report_email(subject: str, html_body: str) -> bool:
    """Send the main HTML report email to the configured recipient."""
    sender, password, recipient, _ = _get_credentials()
    return _smtp_send(sender, password, recipient, subject, body_html=html_body)


def send_sms_alert(message: str) -> bool:
    """
    Send a Tier 1 SMS alert via email-to-SMS gateway.
    Subject is intentionally blank — most SMS gateways display only the body.
    """
    sender, password, _, sms_gateway = _get_credentials()
    if not sms_gateway:
        logger.warning("SMS_EMAIL not configured — skipping SMS alert.")
        return False
    return _smtp_send(
        sender, password, sms_gateway,
        subject="",           # blank subject = cleaner SMS
        body_text=message,
    )


def send_morning_report(html_body: str, report_date: Optional[str] = None) -> bool:
    """Always-send morning report (confirms system is running even if nothing found)."""
    date_str = report_date or datetime.now(timezone.utc).strftime("%B %d %Y")
    subject = f"📊 Catalyst Morning Report — {date_str}"
    return send_report_email(subject, html_body)


def send_evening_report(html_body: str, report_date: Optional[str] = None) -> bool:
    date_str = report_date or datetime.now(timezone.utc).strftime("%B %d %Y")
    subject = f"📊 Catalyst Evening Report — {date_str}"
    return send_report_email(subject, html_body)


def send_position_alert(ticker: str, description: str, html_body: str) -> bool:
    """Send a position-change alert email (only when something noteworthy is found)."""
    subject = f"⚠ Position Alert — ${ticker}"
    return send_report_email(subject, html_body)


def send_tier1_sms(ticker: str, event: str, current_price: Optional[float] = None) -> bool:
    """
    Send highest-priority SMS (e.g. SpaceX S-1 detected, deal cancelled).
    Always fires regardless of other filters.
    """
    price_part = f" | Price: ${current_price:.2f}" if current_price else ""
    message = (
        f"URGENT ALERT ${ticker}\n"
        f"{event}{price_part}\n"
        f"Check your email for full details.\n"
        f"THIS IS NOT INVESTMENT ADVICE."
    )
    logger.critical(f"TIER 1 SMS ALERT: {ticker} — {event}")
    return send_sms_alert(message)


def send_test_email() -> bool:
    """Send a test email to verify credentials are working."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    html = f"""
    <div style="font-family:Arial;max-width:500px;margin:20px auto;padding:20px;
                border:2px solid #27AE60;border-radius:8px;">
      <h2 style="color:#27AE60;">✅ Stock Monitor — Connection Test</h2>
      <p>Email delivery is working correctly.</p>
      <p style="color:#888;font-size:12px;">Sent at: {now}</p>
    </div>"""
    return send_report_email("✅ Stock Monitor — Test Email", html)


def send_test_sms() -> bool:
    """Send a test SMS to verify the gateway is working."""
    return send_sms_alert(
        f"Stock Monitor test SMS — delivery confirmed at "
        f"{datetime.now(timezone.utc).strftime('%H:%M UTC')}"
    )
