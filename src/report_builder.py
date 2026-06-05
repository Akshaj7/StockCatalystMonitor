"""
Phase 4: Report Builder
Builds formatted HTML email reports and plain-text SMS alerts from scan results.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, load_positions, setup_logging, COMMAND_FOOTER_HTML

logger = setup_logging("report_builder")

# Score tier colours (inline CSS — required for email clients)
TIER_STYLES = {
    "HIGH INTEREST": ("🔴", "#C0392B", "#FADBD8"),
    "WATCH":         ("🟡", "#E67E22", "#FDEBD0"),
    "NOTABLE":       ("🟢", "#1E8449", "#D5F5E3"),
    "SKIP":          ("⚪", "#7F8C8D", "#F2F3F4"),
}

HEADER_BG   = "#0D1B2A"
SECTION_BG  = "#F8F9FA"
ACCENT_BLUE = "#1A73E8"
TEXT_DARK   = "#1A1A2A"
TEXT_MID    = "#555555"
TEXT_LIGHT  = "#888888"

DISCLAIMER = (
    "This is automated analysis only. Always do your own research. "
    "Nothing in this report is investment advice. All trading decisions are yours alone."
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(current: float, entry: float) -> str:
    if not entry:
        return "N/A"
    pct = (current - entry) / entry * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _price_color(current: float, entry: float) -> str:
    return "#27AE60" if current >= entry else "#E74C3C"


def _get_current_price(ticker: str) -> Optional[float]:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period="1d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# HTML building blocks
# ---------------------------------------------------------------------------

def _html_wrapper(title: str, body_html: str, generated_at: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="margin:0;padding:0;background:#EBEBEB;font-family:Arial,Helvetica,sans-serif;">
<div style="max-width:620px;margin:0 auto;background:#FFFFFF;">

  <!-- Header -->
  <div style="background:{HEADER_BG};padding:24px 20px;text-align:center;">
    <div style="font-size:22px;font-weight:bold;color:#FFFFFF;letter-spacing:2px;">
      📊 CATALYST REPORT
    </div>
    <div style="font-size:12px;color:#AABBCC;margin-top:6px;">
      {generated_at}
    </div>
  </div>

  {body_html}

  <!-- Command quick-reference -->
  <div style="padding:0 20px;">
    {COMMAND_FOOTER_HTML}
  </div>

  <!-- Footer -->
  <div style="background:#F0F0F0;padding:14px 20px;text-align:center;
              font-size:10px;color:{TEXT_LIGHT};border-top:1px solid #DDDDDD;">
    {DISCLAIMER}
  </div>

</div>
</body>
</html>"""


def _section(title: str, content_html: str) -> str:
    return f"""
  <div style="padding:16px 20px 4px;">
    <div style="font-size:11px;font-weight:bold;color:{TEXT_LIGHT};
                letter-spacing:1.5px;text-transform:uppercase;
                border-bottom:2px solid {HEADER_BG};padding-bottom:4px;margin-bottom:12px;">
      {title}
    </div>
    {content_html}
  </div>"""


def _position_card(pos: dict, current_price: Optional[float]) -> str:
    ticker       = pos.get("ticker", "")
    name         = pos.get("company_name", "")
    entry        = pos.get("entry_price", 0)
    shares       = pos.get("shares", 0)
    target       = pos.get("target_exit", 0)
    stop         = pos.get("stop_loss", 0)
    thesis_desc  = pos.get("thesis_description", "")
    notes        = pos.get("notes", "")
    date_entered = pos.get("date_entered", "")

    if current_price:
        price_str  = f"${current_price:,.2f}"
        pct_str    = _pct(current_price, entry)
        pct_color  = _price_color(current_price, entry)
        price_line = (
            f"Entry: <b>${entry:.2f}</b> &nbsp;|&nbsp; "
            f"Current: <b style='color:{pct_color};'>{price_str}</b> &nbsp;|&nbsp; "
            f"<b style='color:{pct_color};'>{pct_str}</b>"
        )
    else:
        price_line = f"Entry: <b>${entry:.2f}</b> &nbsp;|&nbsp; Current: N/A (market closed)"

    # Days held
    days_held = ""
    if date_entered:
        try:
            entered_dt = datetime.strptime(date_entered, "%Y-%m-%d")
            days = (datetime.now() - entered_dt).days
            days_held = f"Days held: <b>{days}</b> &nbsp;|&nbsp; "
        except ValueError:
            pass

    # Target / stop
    target_str = f"Target: <b>${target:.2f}</b>" if target else ""
    stop_str   = f"Stop: <b>${stop:.2f}</b>" if stop else ""
    targets = " &nbsp;|&nbsp; ".join(filter(None, [target_str, stop_str]))

    # Status line
    status_color = "#27AE60"
    status_text  = "✓ No exit signals triggered — Thesis intact"
    action_text  = "ACTION: HOLD"

    if current_price and stop and current_price < stop:
        status_color = "#E74C3C"
        status_text  = "⚠ PRICE BELOW STOP LOSS"
        action_text  = "ACTION: REVIEW POSITION"
    elif current_price and target and current_price >= target:
        status_color = "#E67E22"
        status_text  = "🎯 TARGET PRICE REACHED"
        action_text  = "ACTION: CONSIDER SELLING"

    return f"""
    <div style="background:{SECTION_BG};border-left:4px solid {status_color};
                padding:12px 14px;margin-bottom:10px;border-radius:2px;">
      <div style="font-size:15px;font-weight:bold;color:{TEXT_DARK};">
        ${ticker} &mdash; {name}
      </div>
      <div style="font-size:12px;color:{TEXT_MID};margin-top:4px;">{price_line}</div>
      <div style="font-size:12px;color:{TEXT_LIGHT};margin-top:2px;">
        {days_held}Thesis: {thesis_desc}
      </div>
      {"<div style='font-size:12px;color:" + TEXT_LIGHT + ";margin-top:2px;'>" + targets + "</div>" if targets else ""}
      <div style="font-size:12px;color:{status_color};margin-top:6px;font-weight:bold;">
        {status_text}
      </div>
      <div style="font-size:13px;font-weight:bold;color:{HEADER_BG};margin-top:4px;">
        {action_text}
      </div>
    </div>"""


def _catalyst_card(result: dict) -> str:
    label    = result.get("label", "SKIP")
    emoji, border_color, bg_color = TIER_STYLES.get(label, TIER_STYLES["SKIP"])
    score    = result.get("score", 0)
    company  = result.get("company_name", "Unknown")
    ticker   = result.get("ticker", "N/A")
    summary  = result.get("summary", "")
    offer    = result.get("offer_price")
    payment  = result.get("payment_type", "")
    months   = result.get("months_to_close")
    fee      = result.get("termination_fee")
    risks    = result.get("key_risks", [])
    link     = result.get("edgar_link", "")
    filed    = result.get("file_date", "")
    keyword  = result.get("matched_keyword", "")

    offer_line = ""
    if offer:
        offer_line = (
            f"<div style='font-size:12px;color:{TEXT_MID};margin-top:4px;'>"
            f"Offer: <b>${offer:.2f}/share</b> ({payment})"
            + (f" &nbsp;|&nbsp; Close: ~{months} months" if months else "")
            + (f" &nbsp;|&nbsp; Term. fee: ${fee/1e6:.1f}M" if fee else "")
            + "</div>"
        )

    risks_line = ""
    if risks:
        risks_text = " &bull; ".join(risks[:3])
        risks_line = f"<div style='font-size:11px;color:{TEXT_LIGHT};margin-top:3px;'>Risks: {risks_text}</div>"

    link_line = ""
    if link:
        link_line = (
            f"<div style='margin-top:8px;'>"
            f"<a href='{link}' style='font-size:11px;color:{ACCENT_BLUE};'>📄 View SEC Filing</a>"
            f"</div>"
        )

    filed_line = f"Filed: {filed}" if filed else ""
    keyword_line = f"Keyword: <i>{keyword}</i>" if keyword else ""
    meta = " &nbsp;|&nbsp; ".join(filter(None, [filed_line, keyword_line]))

    return f"""
    <div style="background:{bg_color};border-left:4px solid {border_color};
                padding:12px 14px;margin-bottom:10px;border-radius:2px;">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
        <div style="font-size:15px;font-weight:bold;color:{TEXT_DARK};">
          {emoji} ${ticker} &mdash; {company}
        </div>
        <div style="font-size:13px;font-weight:bold;color:{border_color};
                    background:white;padding:2px 8px;border-radius:10px;
                    border:1px solid {border_color};white-space:nowrap;">
          {label} [{score}/100]
        </div>
      </div>
      <div style="font-size:12px;color:{TEXT_MID};margin-top:6px;">{summary}</div>
      {offer_line}
      {risks_line}
      <div style="font-size:11px;color:{TEXT_LIGHT};margin-top:4px;">{meta}</div>
      {link_line}
    </div>"""


def _insider_card(purchase: dict) -> str:
    ticker   = purchase.get("ticker", "N/A")
    company  = purchase.get("company_name", "")
    name     = purchase.get("owner_name", "")
    title    = purchase.get("officer_title", "") or ("Director" if purchase.get("is_director") else "Insider")
    shares   = purchase.get("shares", 0)
    price    = purchase.get("price_per_share", 0)
    total    = purchase.get("total_value", 0)
    date     = purchase.get("transaction_date", "")
    multi    = purchase.get("multiple_insiders_buying", False)
    ceo_cfo  = purchase.get("is_ceo") or purchase.get("is_cfo")

    badge = ""
    if purchase.get("is_ceo"):
        badge = f" <span style='background:#E74C3C;color:white;font-size:10px;padding:1px 6px;border-radius:8px;'>CEO</span>"
    elif purchase.get("is_cfo"):
        badge = f" <span style='background:#E67E22;color:white;font-size:10px;padding:1px 6px;border-radius:8px;'>CFO</span>"

    cluster_banner = ""
    if multi:
        cluster_banner = (
            f"<div style='font-size:11px;font-weight:bold;color:#8E44AD;"
            f"margin-bottom:6px;'>⚡ CLUSTER: MULTIPLE INSIDERS BUYING</div>"
        )

    border_color = "#E74C3C" if ceo_cfo else "#3498DB"
    bg_color     = "#FDEDEC" if ceo_cfo else "#EBF5FB"

    return f"""
    <div style="background:{bg_color};border-left:4px solid {border_color};
                padding:12px 14px;margin-bottom:10px;border-radius:2px;">
      {cluster_banner}
      <div style="font-size:14px;font-weight:bold;color:{TEXT_DARK};">
        ${ticker} &mdash; {company}
      </div>
      <div style="font-size:12px;color:{TEXT_MID};margin-top:4px;">
        {name}{badge} &mdash; {title}
      </div>
      <div style="font-size:13px;font-weight:bold;color:{border_color};margin-top:5px;">
        {shares:,.0f} shares @ ${price:.2f} = <b>${total:,.0f}</b>
      </div>
      <div style="font-size:11px;color:{TEXT_LIGHT};margin-top:3px;">
        Date: {date}
      </div>
    </div>"""


def _filings_link_table(filings: list[dict]) -> str:
    """Compact table of all filings with direct clickable SEC EDGAR links."""
    rows = []
    for f in filings:
        ticker  = f.get("ticker", "N/A")
        company = f.get("company_name", "Unknown")
        link    = f.get("edgar_link", "")
        date    = f.get("file_date", "")
        keyword = f.get("matched_keyword", "")
        accession = f.get("accession_no", "")

        if link:
            company_cell = (
                f"<a href='{link}' style='color:{ACCENT_BLUE};text-decoration:none;font-weight:bold;'>"
                f"{company}</a>"
            )
        else:
            company_cell = f"<span style='font-weight:bold;'>{company}</span>"

        rows.append(
            f"<tr style='border-bottom:1px solid #EEEEEE;'>"
            f"<td style='padding:6px 8px;font-size:12px;color:{TEXT_DARK};white-space:nowrap;'>"
            f"<b>${ticker}</b></td>"
            f"<td style='padding:6px 8px;font-size:12px;'>{company_cell}</td>"
            f"<td style='padding:6px 8px;font-size:11px;color:{TEXT_LIGHT};white-space:nowrap;'>{date}</td>"
            f"<td style='padding:6px 8px;font-size:11px;color:{TEXT_LIGHT};'>{keyword}</td>"
            f"</tr>"
        )

    return (
        f"<table style='width:100%;border-collapse:collapse;font-family:Arial;'>"
        f"<thead>"
        f"<tr style='background:{SECTION_BG};'>"
        f"<th style='padding:6px 8px;font-size:11px;color:{TEXT_LIGHT};text-align:left;'>TICKER</th>"
        f"<th style='padding:6px 8px;font-size:11px;color:{TEXT_LIGHT};text-align:left;'>COMPANY (click for SEC filing)</th>"
        f"<th style='padding:6px 8px;font-size:11px;color:{TEXT_LIGHT};text-align:left;'>FILED</th>"
        f"<th style='padding:6px 8px;font-size:11px;color:{TEXT_LIGHT};text-align:left;'>KEYWORD</th>"
        f"</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"</table>"
    )


def _stats_bar(edgar_count: int, analyzed_count: int, high_count: int,
               insider_count: int) -> str:
    return f"""
  <div style="background:{HEADER_BG};padding:12px 20px;text-align:center;
              font-size:11px;color:#AABBCC;">
    {edgar_count} filings scanned &nbsp;|&nbsp;
    {analyzed_count} AI-analyzed &nbsp;|&nbsp;
    {high_count} high interest &nbsp;|&nbsp;
    {insider_count} insider purchases
  </div>"""


# ---------------------------------------------------------------------------
# Public report builders
# ---------------------------------------------------------------------------

def build_morning_report(
    edgar_results: list[dict],
    groq_results: list[dict],
    insider_results: list[dict],
    report_type: str = "MORNING",
    label: str = "",
) -> str:
    """Build the full HTML morning / evening / weekly report."""
    if label:
        report_type = label
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%A %B %d %Y  &nbsp;|&nbsp;  Generated %I:%M %p UTC")

    body_parts = []

    # --- Positions section ---
    positions = load_positions()
    pos_cards = []
    for pos in positions:
        price = _get_current_price(pos.get("ticker", ""))
        pos_cards.append(_position_card(pos, price))

    if pos_cards:
        body_parts.append(_section("Your Positions", "\n".join(pos_cards)))

    # --- Catalyst discoveries ---
    # Filter out SKIPs unless nothing else found, sort by score desc
    display_results = [r for r in groq_results if r.get("score", 0) >= 20]
    if not display_results and groq_results:
        display_results = groq_results[:5]  # show top 5 even if all SKIP

    if display_results:
        catalyst_cards = "".join(_catalyst_card(r) for r in display_results)
        body_parts.append(_section(
            f"New Catalyst Discoveries ({len(display_results)} found)",
            catalyst_cards,
        ))
    else:
        body_parts.append(_section(
            "New Catalyst Discoveries",
            "<div style='color:#888;font-size:13px;padding:8px 0;'>"
            "No high-interest catalyst filings found in this scan window.</div>",
        ))

    # --- Insider buying ---
    if insider_results:
        insider_cards = "".join(_insider_card(p) for p in insider_results[:10])
        body_parts.append(_section(
            f"Insider Buying ({len(insider_results)} purchase(s) ≥ $50k)",
            insider_cards,
        ))
    else:
        body_parts.append(_section(
            "Insider Buying",
            "<div style='color:#888;font-size:13px;padding:8px 0;'>"
            "No qualifying insider purchases detected.</div>",
        ))

    # --- All filings with direct EDGAR links ---
    if edgar_results:
        body_parts.append(_section(
            f"All Filings Scanned Today ({len(edgar_results)} total) — Direct SEC Links",
            _filings_link_table(edgar_results),
        ))

    # Stats bar
    high_count = sum(1 for r in groq_results if r.get("label") == "HIGH INTEREST")
    stats = _stats_bar(
        len(edgar_results),
        len(groq_results),
        high_count,
        len(insider_results),
    )

    body_html = "\n".join(body_parts) + "\n" + stats

    title = f"Catalyst {report_type.title()} Report — {now.strftime('%B %d %Y')}"
    return _html_wrapper(title, body_html, generated_at)


def build_position_alert_html(position: dict, trigger_description: str,
                               current_price: Optional[float] = None) -> str:
    """Build a short HTML email for a 30-minute position check alert."""
    ticker = position.get("ticker", "")
    name   = position.get("company_name", "")
    entry  = position.get("entry_price", 0)
    now    = datetime.now(timezone.utc)
    generated_at = now.strftime("%B %d %Y  &nbsp;|&nbsp;  %I:%M %p UTC")

    card = _position_card(position, current_price)
    alert_box = f"""
    <div style="background:#FDEDEC;border:2px solid #E74C3C;padding:14px;
                margin:12px 0;border-radius:4px;text-align:center;">
      <div style="font-size:16px;font-weight:bold;color:#C0392B;">⚠ POSITION ALERT</div>
      <div style="font-size:13px;color:#555;margin-top:6px;">{trigger_description}</div>
    </div>"""

    body_html = _section(f"Alert — ${ticker}", alert_box + card)
    return _html_wrapper(f"Position Alert — ${ticker}", body_html, generated_at)


def build_sms_alert(ticker: str, event: str, current_price: Optional[float] = None) -> str:
    """Build the plain-text body for a Tier 1 SMS alert (kept under 160 chars)."""
    price_part = f" | Price: ${current_price:.2f}" if current_price else ""
    msg = f"URGENT ${ticker}: {event}{price_part} | Check email for details. This is NOT a buy/sell recommendation."
    return msg[:320]  # SMS gateways truncate long messages


def build_no_news_report(report_type: str = "MORNING", label: str = "") -> str:
    """Minimal report sent when the scanner runs but finds nothing noteworthy.
    Always sent for morning reports to confirm the system is running."""
    if label:
        report_type = label
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%A %B %d %Y  &nbsp;|&nbsp;  %I:%M %p UTC")

    positions = load_positions()
    pos_cards = []
    for pos in positions:
        price = _get_current_price(pos.get("ticker", ""))
        pos_cards.append(_position_card(pos, price))

    pos_section = _section("Your Positions", "\n".join(pos_cards)) if pos_cards else ""
    notice = _section(
        "System Status",
        "<div style='background:#D5F5E3;border-left:4px solid #27AE60;"
        "padding:12px;border-radius:2px;font-size:13px;color:#1E8449;'>"
        "✅ System running normally. No catalyst filings detected in this scan window. "
        "You will be notified when something noteworthy is found.</div>",
    )

    body_html = pos_section + notice
    title = f"Catalyst {report_type.title()} Report — {now.strftime('%B %d %Y')}"
    return _html_wrapper(title, body_html, generated_at)
