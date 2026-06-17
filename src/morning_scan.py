"""
Morning Scan Orchestrator
Runs Phases 1-4 in sequence: EDGAR scan → Insider scan → Groq analysis → Email report.
Scheduled to run at 6:00 AM EST on weekdays via GitHub Actions.
"""

import json
import sys
import io
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows console encoding so emoji in log lines don't crash the script
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, setup_logging, load_positions
from edgar_scanner import scan_for_mergers
from insider_scanner import scan_for_insider_buys, scan_watchlist_insider_buys
from groq_analyzer import analyze_batch
from report_builder import build_morning_report, build_no_news_report
from alert_system import send_morning_report, send_evening_report

logger = setup_logging("morning_scan")

# Max filings to send through Groq to stay well within token budget.
# Prioritise high-keyword matches (merger agreement > strategic alternatives)
GROQ_BATCH_LIMIT = 10


def load_config() -> dict:
    with open(ROOT / "config" / "settings.json") as f:
        return json.load(f)


def save_scan_results(edgar: list, insider: list, groq: list) -> None:
    out = {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "edgar_results":  edgar,
        "insider_results": insider,
        "groq_results":   groq,
    }
    path = ROOT / "data" / "morning_scan_results.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(out, f, indent=2)
    logger.info(f"Full results saved → {path}")


def _parse_args():
    """Parse CLI arguments: --evening, --days N, --label TEXT."""
    import argparse
    parser = argparse.ArgumentParser(description="Stock catalyst scan")
    parser.add_argument("--evening",  action="store_true", help="Run as evening scan")
    parser.add_argument("--days",     type=int,  default=1,  help="Days to look back (default 1)")
    parser.add_argument("--label",    type=str,  default="",  help="Report label override")
    return parser.parse_args()


def main():
    args = _parse_args()

    is_evening    = args.evening
    lookback_days = args.days
    label_override = args.label or ("EVENING" if is_evening else "MORNING")
    if lookback_days > 1:
        label_override = args.label or f"WEEKLY SWEEP ({lookback_days}d)"

    start_time = datetime.now(timezone.utc)
    logger.info("=" * 60)
    logger.info(f"{label_override} SCAN STARTING")
    logger.info(f"Run time: {start_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    if lookback_days > 1:
        logger.info(f"Lookback window: {lookback_days} days")
    logger.info("=" * 60)

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    config = load_config()
    filters = config.get("filters", {})

    # ── Phase 1: EDGAR merger scan ─────────────────────────────────────────
    logger.info("Phase 1: Scanning EDGAR for merger filings...")
    edgar_results = scan_for_mergers(
        filters.get("merger_keywords", []),
        days_back=lookback_days,
    )
    logger.info(f"  → {len(edgar_results)} merger filings found")

    # ── Phase 2: Insider buying scan ───────────────────────────────────────
    logger.info("Phase 2: Scanning Form 4 insider buying...")
    min_value = filters.get("insider_minimum_purchase", 50000)
    txn_codes = filters.get("insider_transaction_codes", ["P"])

    insider_results = scan_for_insider_buys(
        min_value=min_value,
        transaction_codes=txn_codes,
    )

    # Watchlist scan — checks positions directly, bypasses the 150-filing cap
    positions = load_positions()
    watchlist_tickers = [p["ticker"] for p in positions if p.get("ticker") and p.get("ticker") != "N/A"]
    if watchlist_tickers:
        logger.info(f"Phase 2b: Watchlist insider scan for {watchlist_tickers}...")
        watchlist_results = scan_watchlist_insider_buys(
            tickers=watchlist_tickers,
            min_value=min_value,
            transaction_codes=txn_codes,
            days_back=2,
        )
        # Merge, dedup by accession number
        existing_adsh = {r["accession_no"] for r in insider_results}
        for r in watchlist_results:
            if r["accession_no"] not in existing_adsh:
                insider_results.append(r)
                existing_adsh.add(r["accession_no"])
        logger.info(f"  → {len(watchlist_results)} watchlist hit(s) found")

    logger.info(f"  → {len(insider_results)} qualifying insider purchases found")

    # ── Phase 3: Groq AI analysis (top filings only) ───────────────────────
    groq_results = []
    if edgar_results:
        logger.info(f"Phase 3: Groq AI analysis on top {GROQ_BATCH_LIMIT} filings...")
        # Prioritise: keyword "agreement and plan of merger" > "merger agreement" > others
        priority_order = {
            "agreement and plan of merger": 0,
            "merger agreement":             1,
            "going private":                2,
            "tender offer":                 3,
            "definitive agreement":         4,
            "strategic alternatives":       5,
        }
        sorted_filings = sorted(
            edgar_results,
            key=lambda x: priority_order.get(x.get("matched_keyword", ""), 99),
        )
        batch = sorted_filings[:GROQ_BATCH_LIMIT]
        groq_results = analyze_batch(batch)
        logger.info(f"  → {len(groq_results)} filings analyzed by Groq")
    else:
        logger.info("Phase 3: No filings to analyze.")

    # ── Phase 4: Build report and send email ───────────────────────────────
    logger.info(f"Phase 4: Building report and sending email ({label_override})...")
    if groq_results or insider_results:
        report_html = build_morning_report(
            edgar_results, groq_results, insider_results,
            label=label_override,
        )
    else:
        report_html = build_no_news_report(label_override)

    if is_evening:
        sent = send_evening_report(report_html)
    else:
        sent = send_morning_report(report_html)

    if sent:
        logger.info(f"  → {label_override} report email delivered ✓")
    else:
        logger.error(f"  → Failed to send {label_override} report email!")

    # Save all results for debugging / Phase 5 use
    save_scan_results(edgar_results, insider_results, groq_results)

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info("=" * 60)
    logger.info(f"{label_override} SCAN COMPLETE in {elapsed:.0f}s")
    logger.info(
        f"Summary: {len(edgar_results)} filings | "
        f"{len(insider_results)} insider buys | "
        f"{len(groq_results)} AI-analyzed | "
        f"Email {'sent' if sent else 'FAILED'}"
    )
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
