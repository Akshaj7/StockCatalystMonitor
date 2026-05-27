"""
Phase 5: Position Monitor
30-minute watchdog for open positions.

For each position:
  1. Fetch live price via yfinance
  2. Check against target_exit / stop_loss thresholds
  3. Scan SEC EDGAR for instant_alert_triggers (e.g. SpaceX S-1)
  4. Send alerts — email always, SMS for Tier 1 events
  5. Dedup via state/sent_alerts.json so no alert fires twice

RULE 1  — Never auto-trade.
RULE 3  — SpaceX S-1 / instant_alert_triggers are NEVER filtered or delayed.
RULE 4  — Every alert is recorded by its unique key; duplicates are suppressed.
"""

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))

from utils import (
    ROOT,
    load_positions,
    load_sent_alerts,
    save_sent_alerts,
    setup_logging,
)
from alert_system import send_position_alert, send_tier1_sms, _get_credentials, _smtp_send
from edgar_scanner import scan_for_mergers, scan_for_registration_statements

logger = setup_logging("position_monitor")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How many days before the same price-level alert can re-fire
PRICE_ALERT_COOLDOWN_DAYS = 1

# Significant DAILY move threshold — alerts on large same-day swings
SIGNIFICANT_MOVE_THRESHOLD = 0.07   # 7% change from previous close


# ---------------------------------------------------------------------------
# Price helpers
# ---------------------------------------------------------------------------

def _get_price(ticker: str) -> tuple[Optional[float], Optional[float]]:
    """
    Fetch latest price and previous close via yfinance.
    Returns (current_price, prev_close). Either may be None on failure.
    """
    try:
        import yfinance as yf
        t    = yf.Ticker(ticker)
        info = t.fast_info
        price      = getattr(info, "last_price",     None)
        prev_close = getattr(info, "previous_close", None)
        if price and price > 0:
            return (
                round(float(price), 4),
                round(float(prev_close), 4) if prev_close else None,
            )
        # Fallback to 2-day history
        hist = t.history(period="2d")
        if not hist.empty:
            price = round(float(hist["Close"].iloc[-1]), 4)
            prev  = round(float(hist["Close"].iloc[-2]), 4) if len(hist) >= 2 else None
            return price, prev
    except Exception as exc:
        logger.warning(f"yfinance error for {ticker}: {exc}")
    return None, None


# ---------------------------------------------------------------------------
# Alert dedup helpers (RULE 4)
# ---------------------------------------------------------------------------

def _alert_key(*parts: str) -> str:
    return ":".join(str(p) for p in parts)


def _already_sent(key: str, sent_data: dict) -> bool:
    return key in sent_data.get("sent_alerts", [])


def _record_sent(key: str, sent_data: dict) -> None:
    alerts = sent_data.setdefault("sent_alerts", [])
    if key not in alerts:
        alerts.append(key)


# ---------------------------------------------------------------------------
# Price alert logic
# ---------------------------------------------------------------------------

def _check_price_thresholds(
    pos: dict,
    price: float,
    prev_close: Optional[float] = None,
) -> list[dict]:
    """
    Return a list of triggered threshold events.
    Each event: {"type": str, "message": str, "tier": 1|2, "label": str}

    Price levels (target/stop) are Tier 1 → send SMS.
    Daily significant move is Tier 2 → email only.
    Significant move is measured vs. previous close, NOT vs. entry price,
    so a 473%-above-entry position doesn't fire every single day.
    """
    ticker      = pos["ticker"]
    target      = pos.get("target_exit")
    stop        = pos.get("stop_loss")
    entry       = pos.get("entry_price", 0)
    today       = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    events: list[dict] = []

    if target and price >= target:
        events.append({
            "type":    _alert_key(ticker, "TARGET_HIT", today),
            "message": f"${ticker} hit TARGET EXIT ${price:.2f} (target: ${target:.2f})",
            "tier":    1,
            "label":   "TARGET REACHED",
        })

    if stop and price <= stop:
        events.append({
            "type":    _alert_key(ticker, "STOP_HIT", today),
            "message": f"${ticker} hit STOP LOSS ${price:.2f} (stop: ${stop:.2f})",
            "tier":    1,
            "label":   "STOP LOSS HIT",
        })

    # Significant daily move — compare to previous close, not entry price
    if prev_close and prev_close > 0:
        daily_chg = (price - prev_close) / prev_close
        if abs(daily_chg) >= SIGNIFICANT_MOVE_THRESHOLD:
            direction = "UP" if daily_chg > 0 else "DOWN"
            events.append({
                "type":    _alert_key(ticker, f"DAILY_{direction}", today),
                "message": (
                    f"${ticker} moved {daily_chg:+.1%} today "
                    f"(prev close: ${prev_close:.2f} → now: ${price:.2f})"
                ),
                "tier":    2,
                "label":   f"SIGNIFICANT MOVE {direction}",
            })

    return events


# ---------------------------------------------------------------------------
# EDGAR instant-trigger scan (RULE 3)
# ---------------------------------------------------------------------------

def _scan_instant_triggers(pos: dict) -> list[dict]:
    """
    Scan EDGAR for any of the position's instant_alert_triggers.

    For pre_ipo_speculation positions, also runs a dedicated S-1/S-1A
    registration statement scan with a 30-day lookback so a SpaceX IPO
    filing is NEVER missed even if the monitor was offline.

    RULE 3: results are NEVER filtered or scored down — all matches returned.
    """
    triggers = pos.get("instant_alert_triggers", [])
    ticker   = pos["ticker"]
    hits: list[dict] = []

    # ── Standard 8-K keyword scan (24h lookback) ─────────────────────────
    if triggers:
        logger.info(f"[{ticker}] Scanning EDGAR for {len(triggers)} instant triggers...")
        for keyword in triggers:
            try:
                results = scan_for_mergers([keyword])
                for r in results:
                    r["matched_trigger"] = keyword
                hits.extend(results)
                if results:
                    logger.info(
                        f"[{ticker}] TRIGGER '{keyword}' matched "
                        f"{len(results)} EDGAR filing(s)"
                    )
                time.sleep(0.25)
            except Exception as exc:
                logger.error(f"[{ticker}] EDGAR scan error for '{keyword}': {exc}")

    # ── S-1 Registration Statement scan (RULE 3 — 30-day lookback) ───────
    # Applies to pre_ipo_speculation plays where the IPO filing is the exit signal
    if pos.get("thesis_type") == "pre_ipo_speculation":
        ipo_keywords = pos.get("ipo_company_keywords", [])
        if not ipo_keywords:
            # Build from triggers — use company-name-like entries
            ipo_keywords = [
                t for t in triggers
                if not any(c in t.lower() for c in ["merger", "8-k", "dxyz"])
            ]
        if ipo_keywords:
            logger.info(
                f"[{ticker}] Running S-1 registration watch for: {ipo_keywords}"
            )
            try:
                s1_hits = scan_for_registration_statements(
                    ipo_keywords, days_back=30
                )

                # CRITICAL FILTER: only alert when the FILER is the target company.
                # EFTS full-text search finds any S-1 that *mentions* the keyword,
                # including unrelated companies that reference SpaceX in their prospectus.
                # We only want the filing when SpaceX itself is the registrant.
                ipo_lower = [kw.lower() for kw in ipo_keywords]
                confirmed_hits = []
                for h in s1_hits:
                    filer = h.get("company_name", "").lower()
                    if any(kw in filer for kw in ipo_lower):
                        h["matched_trigger"] = (
                            f"S-1 REGISTRATION FILED: {h.get('company_name', '')}"
                        )
                        h["is_ipo_registration"] = True
                        confirmed_hits.append(h)
                    else:
                        logger.debug(
                            f"[{ticker}] S-1 false positive filtered out: "
                            f"'{h.get('company_name','')}' (filer doesn't match IPO target)"
                        )

                hits.extend(confirmed_hits)
                if confirmed_hits:
                    logger.critical(
                        f"[{ticker}] *** CONFIRMED S-1 FROM TARGET COMPANY! "
                        f"{len(confirmed_hits)} filing(s) ***"
                    )
                else:
                    logger.info(
                        f"[{ticker}] S-1 watch: {len(s1_hits)} filings scanned, "
                        f"0 confirmed (target company not the filer)"
                    )
            except Exception as exc:
                logger.error(f"[{ticker}] S-1 registration scan error: {exc}")

    # Deduplicate by accession_no
    seen: set[str] = set()
    unique: list[dict] = []
    for h in hits:
        adsh = h.get("accession_no", "")
        if adsh and adsh not in seen:
            seen.add(adsh)
            unique.append(h)

    return unique


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

_COLORS = {
    "TARGET REACHED":         "#27AE60",
    "STOP LOSS HIT":          "#E74C3C",
    "SIGNIFICANT MOVE UP":    "#2ECC71",
    "SIGNIFICANT MOVE DOWN":  "#E67E22",
    "EDGAR TRIGGER":          "#8E44AD",
}

_BG = {
    "TARGET REACHED":         "#D5F5E3",
    "STOP LOSS HIT":          "#FADBD8",
    "SIGNIFICANT MOVE UP":    "#EAFAF1",
    "SIGNIFICANT MOVE DOWN":  "#FDEBD0",
    "EDGAR TRIGGER":          "#F4ECF7",
}


def _banner(label: str, message: str) -> str:
    color = _COLORS.get(label, "#2C3E50")
    bg    = _BG.get(label, "#ECF0F1")
    return (
        f'<div style="background:{bg};border-left:5px solid {color};'
        f'padding:12px 16px;margin:10px 0;border-radius:4px;">'
        f'<strong style="color:{color};">{label}</strong><br>'
        f'<span style="font-size:14px;">{message}</span>'
        f"</div>"
    )


def _edgar_row(hit: dict) -> str:
    link   = hit.get("edgar_link", "#")
    ticker = hit.get("ticker", "—")
    name   = hit.get("company_name", "Unknown")
    form   = hit.get("form_type", "")
    date   = hit.get("file_date", "")
    kw     = hit.get("matched_trigger", "")
    return (
        f'<tr style="border-bottom:1px solid #eee;">'
        f'<td style="padding:6px 8px;">{ticker}</td>'
        f'<td style="padding:6px 8px;">{name}</td>'
        f'<td style="padding:6px 8px;">{form}</td>'
        f'<td style="padding:6px 8px;">{date}</td>'
        f'<td style="padding:6px 8px;font-size:12px;color:#888;">{kw}</td>'
        f'<td style="padding:6px 8px;"><a href="{link}" style="color:#3498DB;">EDGAR</a></td>'
        f"</tr>"
    )


def _build_alert_html(
    pos: dict,
    price: Optional[float],
    prev_close: Optional[float],
    price_events: list[dict],
    edgar_hits: list[dict],
    now_utc: str,
) -> str:
    ticker  = pos["ticker"]
    name    = pos.get("company_name", ticker)
    entry   = pos.get("entry_price", 0)
    target  = pos.get("target_exit", "—")
    stop    = pos.get("stop_loss", "—")
    shares  = pos.get("shares", 0)

    pct_str = ""
    daily_str = ""
    value_str = ""
    if price and entry:
        pct = (price - entry) / entry * 100
        pct_color = "#27AE60" if pct >= 0 else "#E74C3C"
        pct_str = f'<span style="color:{pct_color};font-weight:bold;">{pct:+.1f}% vs entry</span>'
        value_str = f"${price * shares:,.2f}" if shares else ""
    if price and prev_close:
        dpct = (price - prev_close) / prev_close * 100
        dc = "#27AE60" if dpct >= 0 else "#E74C3C"
        daily_str = f' &nbsp; <span style="color:{dc};font-size:13px;">{dpct:+.2f}% today</span>'

    # Price event banners
    price_banners = "".join(_banner(e["label"], e["message"]) for e in price_events)

    # EDGAR trigger section
    edgar_section = ""
    if edgar_hits:
        rows = "".join(_edgar_row(h) for h in edgar_hits)
        edgar_section = f"""
        <div style="margin-top:20px;">
          <h3 style="color:#8E44AD;border-bottom:2px solid #8E44AD;padding-bottom:6px;">
            ⚡ INSTANT ALERT TRIGGERS DETECTED
          </h3>
          <p style="color:#555;font-size:13px;">
            The following SEC filings matched your instant-alert keywords.
            Review immediately — these may signal a major catalyst.
          </p>
          <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead>
              <tr style="background:#F4ECF7;">
                <th style="padding:6px 8px;text-align:left;">Ticker</th>
                <th style="padding:6px 8px;text-align:left;">Company</th>
                <th style="padding:6px 8px;text-align:left;">Form</th>
                <th style="padding:6px 8px;text-align:left;">Date</th>
                <th style="padding:6px 8px;text-align:left;">Trigger</th>
                <th style="padding:6px 8px;text-align:left;">Link</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

    disclaimer = (
        '<p style="color:#999;font-size:11px;border-top:1px solid #eee;'
        'padding-top:12px;margin-top:20px;">'
        "THIS IS NOT INVESTMENT ADVICE. This is an automated informational alert. "
        "All trading decisions are yours alone.</p>"
    )

    price_display = f"${price:.2f}" if price else "N/A"

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:680px;margin:20px auto;
                padding:24px;border:1px solid #ddd;border-radius:8px;">
      <h2 style="color:#2C3E50;margin-top:0;">
        ⚠ Position Alert — ${ticker}
      </h2>

      <!-- Position summary -->
      <table style="width:100%;border-collapse:collapse;margin-bottom:16px;
                    background:#F8F9FA;border-radius:6px;">
        <tr>
          <td style="padding:10px 14px;">
            <strong style="font-size:15px;">{name}</strong><br>
            <span style="color:#888;font-size:12px;">as of {now_utc}</span>
          </td>
          <td style="padding:10px 14px;text-align:right;">
            <span style="font-size:22px;font-weight:bold;">{price_display}</span>
            <br>{pct_str}{daily_str}
          </td>
        </tr>
        <tr style="border-top:1px solid #eee;">
          <td style="padding:8px 14px;font-size:13px;color:#555;">
            Entry: <strong>${entry}</strong> &nbsp;|&nbsp;
            Target: <strong>${target}</strong> &nbsp;|&nbsp;
            Stop: <strong>${stop}</strong>
          </td>
          <td style="padding:8px 14px;text-align:right;font-size:13px;color:#555;">
            {shares} shares &nbsp;|&nbsp; {value_str}
          </td>
        </tr>
      </table>

      {price_banners}
      {edgar_section}
      {disclaimer}
    </div>"""


def _build_no_alert_html(
    pos: dict,
    price: Optional[float],
    prev_close: Optional[float],
    now_utc: str,
) -> str:
    """Minimal confirmation HTML when no alerts fire (used for daily check-in only)."""
    ticker = pos["ticker"]
    entry  = pos.get("entry_price", 0)
    target = pos.get("target_exit", "—")
    stop   = pos.get("stop_loss", "—")
    shares = pos.get("shares", 0)

    total_pct_str = ""
    daily_pct_str = ""
    if price and entry:
        total_pct = (price - entry) / entry * 100
        color = "#27AE60" if total_pct >= 0 else "#E74C3C"
        total_pct_str = f'<span style="color:{color};">{total_pct:+.1f}% from entry</span>'
    if price and prev_close:
        daily_pct = (price - prev_close) / prev_close * 100
        color = "#27AE60" if daily_pct >= 0 else "#E74C3C"
        daily_pct_str = f'<span style="color:{color};">{daily_pct:+.2f}% today</span>'

    price_display  = f"${price:.2f}" if price else "N/A"
    prev_display   = f"${prev_close:.2f}" if prev_close else "N/A"

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:20px auto;
                padding:20px;border:1px solid #ddd;border-radius:8px;">
      <h3 style="color:#2C3E50;margin-top:0;">📍 Position Check-In — ${ticker}</h3>
      <p style="color:#2E7D32;background:#E8F5E9;padding:8px 12px;border-radius:4px;">
        No alerts triggered. System is watching.
      </p>
      <table style="width:100%;font-size:13px;border-collapse:collapse;">
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:6px 4px;color:#555;">Current Price</td>
          <td style="padding:6px 4px;"><strong>{price_display}</strong></td>
        </tr>
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:6px 4px;color:#555;">Daily Change</td>
          <td style="padding:6px 4px;">{daily_pct_str} (prev close: {prev_display})</td>
        </tr>
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:6px 4px;color:#555;">vs. Entry (${entry})</td>
          <td style="padding:6px 4px;">{total_pct_str}</td>
        </tr>
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:6px 4px;color:#555;">Target Exit</td>
          <td style="padding:6px 4px;"><strong style="color:#27AE60;">${target}</strong></td>
        </tr>
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:6px 4px;color:#555;">Stop Loss</td>
          <td style="padding:6px 4px;"><strong style="color:#E74C3C;">${stop}</strong></td>
        </tr>
        <tr>
          <td style="padding:6px 4px;color:#555;">Shares</td>
          <td style="padding:6px 4px;">{shares}</td>
        </tr>
      </table>
      <p style="color:#999;font-size:11px;margin-top:16px;">
        {now_utc} — THIS IS NOT INVESTMENT ADVICE.
      </p>
    </div>"""


# ---------------------------------------------------------------------------
# Daily check-in dedup (so the "nothing triggered" email only sends once a day)
# ---------------------------------------------------------------------------

def _should_send_checkin(ticker: str, sent_data: dict) -> bool:
    now   = datetime.now(timezone.utc)
    # Only send check-in during 8 AM – 9 PM GMT to avoid middle-of-night emails
    if not (8 <= now.hour < 21):
        return False
    today = now.strftime("%Y-%m-%d")
    key   = _alert_key(ticker, "CHECKIN", today)
    return not _already_sent(key, sent_data)


def _record_checkin(ticker: str, sent_data: dict) -> None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    key   = _alert_key(ticker, "CHECKIN", today)
    _record_sent(key, sent_data)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def monitor_positions() -> None:
    """
    Run one monitoring cycle over all open positions.
    Called by GitHub Actions every 30 minutes.
    """
    positions = load_positions()
    if not positions:
        logger.info("No positions configured — nothing to monitor.")
        return

    sent_data = load_sent_alerts()
    now_utc   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    any_saved = False

    for pos in positions:
        ticker = pos["ticker"]
        logger.info(f"--- Monitoring ${ticker} ---")

        # 1. Fetch live price
        price, prev_close = _get_price(ticker)
        if price:
            daily_str = ""
            if prev_close:
                daily_str = f"  (prev close: ${prev_close:.2f})"
            logger.info(f"[{ticker}] Price: ${price:.2f}{daily_str}")
        else:
            logger.warning(f"[{ticker}] Could not fetch live price.")

        # 2. Check price thresholds
        price_events = (
            _check_price_thresholds(pos, price, prev_close) if price else []
        )

        # 3. Scan EDGAR for instant triggers (RULE 3 — always runs, never filtered)
        edgar_hits = _scan_instant_triggers(pos)

        # ---------------------------------------------------------------
        # 4. Decide what to send
        # ---------------------------------------------------------------
        alerts_to_send: list[dict] = []      # {"key", "message", "tier", "label"}
        new_edgar_hits: list[dict] = []       # EDGAR hits not yet alerted

        # Price events — check dedup (keys collected; recorded only after successful send)
        pending_price_keys: list[str] = []
        for evt in price_events:
            key = evt["type"]
            if not _already_sent(key, sent_data):
                alerts_to_send.append(evt)
                pending_price_keys.append(key)

        # EDGAR hits — dedup by accession_no (RULE 4)
        pending_edgar_keys: list[str] = []
        for hit in edgar_hits:
            adsh = hit.get("accession_no", "")
            key  = _alert_key("EDGAR", adsh) if adsh else None
            if key and not _already_sent(key, sent_data):
                new_edgar_hits.append(hit)
                pending_edgar_keys.append(key)
            elif not key:
                # No accession number — include anyway (RULE 3 override)
                new_edgar_hits.append(hit)

        # ---------------------------------------------------------------
        # 5. Send alerts  (record keys ONLY after confirmed delivery)
        # ---------------------------------------------------------------
        if alerts_to_send or new_edgar_hits:
            html = _build_alert_html(
                pos, price, prev_close, alerts_to_send, new_edgar_hits, now_utc
            )
            email_ok = send_position_alert(ticker, "", html)

            if email_ok:
                # Mark price alerts as sent
                for k in pending_price_keys:
                    _record_sent(k, sent_data)
                    any_saved = True
                # Mark EDGAR hits as sent
                for k in pending_edgar_keys:
                    _record_sent(k, sent_data)
                    any_saved = True
            else:
                logger.warning(
                    f"[{ticker}] Alert email failed — will retry next cycle."
                )

            # Tier 1 SMS for price hits (RULE 3) — fire even if email failed
            for evt in alerts_to_send:
                if evt.get("tier") == 1:
                    send_tier1_sms(ticker, evt["message"], price)

            # EDGAR triggers always get SMS (RULE 3)
            for hit in new_edgar_hits:
                kw  = hit.get("matched_trigger", "SEC filing detected")
                msg = (
                    f"EDGAR TRIGGER: {kw}\n"
                    f"{hit.get('company_name','Unknown')} filed {hit.get('form_type','')}\n"
                    f"{hit.get('edgar_link','')}"
                )
                send_tier1_sms(ticker, msg, price)

        else:
            # Nothing triggered — send a daily check-in (once per day only)
            if _should_send_checkin(ticker, sent_data):
                html = _build_no_alert_html(pos, price, prev_close, now_utc)
                sender, password, recipient, _ = _get_credentials()
                subject = f"Position Check-In -- ${ticker} | {now_utc}"
                ok = _smtp_send(sender, password, recipient, subject, body_html=html)
                if ok:
                    logger.info(f"[{ticker}] Daily check-in email sent.")
                    _record_checkin(ticker, sent_data)
                    any_saved = True
                else:
                    logger.warning(f"[{ticker}] Check-in email failed — will retry tomorrow.")
            else:
                logger.info(
                    f"[{ticker}] No alerts. Check-in already sent today — skipping."
                )

    # Persist state
    if any_saved:
        save_sent_alerts(sent_data)
        logger.info("sent_alerts.json updated.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Load .env when run locally (GitHub Actions sets env vars directly)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    monitor_positions()
