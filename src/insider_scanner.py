"""
Phase 2: Insider Buying Scanner
Scans SEC EDGAR Form 4 filings from the last 24 hours.
Filters for open-market purchases (code P) above the minimum dollar threshold.
Excludes automatic plan purchases (code A) and option exercises.
"""

import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, load_settings, setup_logging

logger = setup_logging("insider_scanner")

EFTS_BASE_URL = "https://efts.sec.gov/LATEST/search-index"
FILING_DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/{filename}"

_contact = os.getenv("GMAIL_ADDRESS", "user@example.com")
USER_AGENT = f"StockCatalystMonitor/1.0 {_contact}"
_MIN_INTERVAL = 0.11


def _get_date_range(days_back: int = 1) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days_back)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    })
    return s


def _fetch_form4_hits(
    session: requests.Session,
    start_date: str,
    end_date: str,
    offset: int = 0,
    page_size: int = 20,
) -> dict:
    params = {
        "forms": "4",
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "from": offset,
    }
    url = f"{EFTS_BASE_URL}?{urlencode(params)}"
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.error(f"EFTS Form 4 fetch error: {exc}")
        return {}


def _xml_url_from_hit(hit: dict) -> Optional[str]:
    """
    Build the direct URL for the Form 4 XML document.
    The EFTS _id field is '{accession_no}:{filename}'.
    """
    hit_id = hit.get("_id", "")
    source = hit.get("_source", {})
    ciks = source.get("ciks", [])
    adsh = source.get("adsh", "")

    if not ciks or not adsh:
        return None

    cik = str(int(ciks[0]))  # strip leading zeros
    accession_clean = adsh.replace("-", "")

    if ":" in hit_id:
        filename = hit_id.split(":", 1)[1]
        # Form 4 XML documents end in .xml — skip if the indexed file isn't XML
        if not filename.lower().endswith(".xml"):
            return None
    else:
        return None

    return FILING_DOC_URL.format(cik=cik, accession_clean=accession_clean, filename=filename)


def _safe_float(text: str) -> float:
    try:
        return float(text.strip().replace(",", "")) if text else 0.0
    except ValueError:
        return 0.0


def _get_val(elem: ET.Element, tag: str) -> str:
    """
    Extract text from a Form 4 XML element.
    EDGAR Form 4 XML wraps scalar values in <value> child elements.
    """
    node = elem.find(f".//{tag}")
    if node is None:
        return ""
    value_child = node.find("value")
    if value_child is not None and value_child.text:
        return value_child.text.strip()
    return node.text.strip() if node.text else ""


def _parse_form4_xml(xml_text: str, adsh: str) -> list[dict]:
    """Parse a Form 4 XML document and return all non-derivative transactions."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.debug(f"XML parse error [{adsh}]: {exc}")
        return []

    # Issuer info
    issuer_cik = _get_val(root, "issuerCik")
    company_name = _get_val(root, "issuerName")
    ticker = _get_val(root, "issuerTradingSymbol") or "N/A"

    # Reporting owner info
    owner_name = _get_val(root, "rptOwnerName")
    officer_title = _get_val(root, "officerTitle")
    is_director = _get_val(root, "isDirector") == "1"
    is_officer = _get_val(root, "isOfficer") == "1"
    title_lower = officer_title.lower()
    is_ceo = any(t in title_lower for t in ("chief executive", " ceo", "(ceo)"))
    is_cfo = any(t in title_lower for t in ("chief financial", " cfo", "(cfo)"))

    transactions = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = _get_val(txn, "transactionCode")
        if not code:
            continue

        acquired = _get_val(txn, "transactionAcquiredDisposedCode")
        txn_date = _get_val(txn, "transactionDate")
        security = _get_val(txn, "securityTitle")
        shares = _safe_float(_get_val(txn, "transactionShares"))
        price = _safe_float(_get_val(txn, "transactionPricePerShare"))
        total_value = shares * price

        transactions.append({
            "accession_no": adsh,
            "issuer_cik": issuer_cik,
            "company_name": company_name,
            "ticker": ticker,
            "owner_name": owner_name,
            "officer_title": officer_title,
            "is_ceo": is_ceo,
            "is_cfo": is_cfo,
            "is_director": is_director,
            "is_officer": is_officer,
            "transaction_code": code,
            "acquired_or_disposed": acquired,
            "transaction_date": txn_date,
            "security_title": security,
            "shares": shares,
            "price_per_share": price,
            "total_value": total_value,
        })

    return transactions


def scan_for_insider_buys(
    min_value: int = 50000,
    transaction_codes: list = None,
    max_filings: int = 150,
) -> list[dict]:
    """
    Search for Form 4 filings and return qualifying insider purchases.
    Caps at max_filings to stay within rate limits.
    """
    if transaction_codes is None:
        transaction_codes = ["P"]

    start_date, end_date = _get_date_range()
    logger.info(f"Date range: {start_date} → {end_date}")
    logger.info(f"Filter: codes={transaction_codes}, min=${min_value:,}")

    session = _make_session()

    # Collect Form 4 filing hits (paginated), deduped by accession number
    all_hits: list[dict] = []
    seen_adsh: set[str] = set()
    offset = 0
    page_size = 20

    while len(all_hits) < max_filings:
        time.sleep(_MIN_INTERVAL)
        data = _fetch_form4_hits(session, start_date, end_date, offset, page_size)
        if not data:
            break

        hits = data.get("hits", {}).get("hits", [])
        total_available = data.get("hits", {}).get("total", {})
        if isinstance(total_available, dict):
            total_available = total_available.get("value", 0)

        if offset == 0:
            logger.info(f"Total Form 4 filings available today: {total_available}")

        for hit in hits:
            adsh = hit.get("_source", {}).get("adsh", "")
            if adsh and adsh not in seen_adsh:
                seen_adsh.add(adsh)
                all_hits.append(hit)

        if offset + page_size >= total_available or not hits:
            break
        offset += page_size

    all_hits = all_hits[:max_filings]

    logger.info(f"Processing {len(all_hits)} Form 4 filings (capped at {max_filings})...")

    qualifying: list[dict] = []
    company_buys: dict[str, list] = {}  # ticker → [owner_name, ...]
    filings_parsed = 0
    filings_skipped = 0

    for hit in all_hits:
        xml_url = _xml_url_from_hit(hit)
        if not xml_url:
            filings_skipped += 1
            continue

        time.sleep(_MIN_INTERVAL)
        try:
            resp = session.get(xml_url, timeout=15)
            if resp.status_code == 404:
                filings_skipped += 1
                continue
            resp.raise_for_status()
            # Guard against HTML error pages returned as 200
            if resp.text.strip().startswith("<!"):
                filings_skipped += 1
                continue
        except Exception as exc:
            logger.debug(f"Fetch failed [{xml_url}]: {exc}")
            filings_skipped += 1
            continue

        adsh = hit.get("_source", {}).get("adsh", "")
        transactions = _parse_form4_xml(resp.text, adsh)
        filings_parsed += 1

        for txn in transactions:
            # Must be an open-market purchase code AND an acquisition
            if txn["transaction_code"] not in transaction_codes:
                continue
            if txn["acquired_or_disposed"] != "A":
                continue
            if txn["total_value"] < min_value:
                continue

            qualifying.append(txn)
            ticker = txn["ticker"]
            company_buys.setdefault(ticker, []).append(txn["owner_name"])

            label = " [CEO]" if txn["is_ceo"] else " [CFO]" if txn["is_cfo"] else ""
            logger.info(
                f"  + {txn['company_name']} ({ticker}) | "
                f"{txn['owner_name']}{label} | "
                f"${txn['total_value']:,.0f}"
            )

    # Flag companies where multiple insiders bought in this scan window
    for txn in qualifying:
        ticker = txn["ticker"]
        buyers = company_buys.get(ticker, [])
        txn["multiple_insiders_buying"] = len(buyers) > 1
        txn["insiders_buying_count"] = len(buyers)

    qualifying.sort(key=lambda x: x["total_value"], reverse=True)

    logger.info(
        f"Scan complete — {len(qualifying)} qualifying purchase(s) found | "
        f"{filings_parsed} parsed, {filings_skipped} skipped"
    )
    return qualifying


def scan_watchlist_insider_buys(
    tickers: list[str],
    min_value: int = 50000,
    transaction_codes: list = None,
    days_back: int = 2,
) -> list[dict]:
    """
    Directly scan Form 4 filings for specific tickers using EDGAR EFTS ticker search.
    Bypasses the general 150-filing cap — searches per ticker so no position is missed.
    Form 4s are filed under the INSIDER's CIK, not the company's, so the EFTS full-text
    search (which indexes <issuerTradingSymbol>) is the correct lookup method.
    Uses days_back=2 by default to catch filings that arrived after the last scan.
    """
    if not tickers:
        return []
    if transaction_codes is None:
        transaction_codes = ["P"]

    start_date, end_date = _get_date_range(days_back)
    session = _make_session()
    qualifying: list[dict] = []
    seen_adsh: set[str] = set()

    logger.info(f"Watchlist insider scan: {tickers} ({start_date} → {end_date})")

    for ticker in tickers:
        logger.info(f"  Checking {ticker}...")
        # Search EFTS for Form 4s where <issuerTradingSymbol> = ticker
        params = {
            "q": f'"{ticker}"',
            "forms": "4",
            "dateRange": "custom",
            "startdt": start_date,
            "enddt": end_date,
            "from": 0,
        }
        url = f"{EFTS_BASE_URL}?{urlencode(params)}"
        time.sleep(_MIN_INTERVAL)
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            hits = resp.json().get("hits", {}).get("hits", [])
        except Exception as exc:
            logger.error(f"  {ticker}: EFTS search failed: {exc}")
            continue

        for hit in hits:
            src = hit.get("_source", {})
            adsh = src.get("adsh", "")
            if not adsh or adsh in seen_adsh:
                continue

            # Confirm issuer ticker matches (filter false positives)
            display_names = str(src.get("display_names", ""))
            if ticker.upper() not in display_names.upper():
                continue

            xml_url = _xml_url_from_hit(hit)
            if not xml_url:
                continue

            time.sleep(_MIN_INTERVAL)
            try:
                r = session.get(xml_url, timeout=15)
                if not r.ok or r.text.strip().startswith("<!"):
                    continue
            except Exception:
                continue

            transactions = _parse_form4_xml(r.text, adsh)
            seen_adsh.add(adsh)

            for txn in transactions:
                # Confirm the transaction is for our watched ticker
                if txn.get("ticker", "").upper() != ticker.upper():
                    continue
                if txn["transaction_code"] not in transaction_codes:
                    continue
                if txn["acquired_or_disposed"] != "A":
                    continue
                if txn["total_value"] < min_value:
                    continue

                label = " [CEO]" if txn["is_ceo"] else " [CFO]" if txn["is_cfo"] else ""
                logger.info(
                    f"  ★ WATCHLIST HIT: {txn['company_name']} ({txn['ticker']}) | "
                    f"{txn['owner_name']}{label} | ${txn['total_value']:,.0f}"
                )
                qualifying.append(txn)

    qualifying.sort(key=lambda x: x["total_value"], reverse=True)
    logger.info(f"Watchlist scan complete — {len(qualifying)} qualifying purchase(s)")
    return qualifying


def save_results(purchases: list[dict]) -> Path:
    output_path = ROOT / "data" / "insider_scan_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_purchases": len(purchases),
        "purchases": purchases,
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Results saved → {output_path}")
    return output_path


def main() -> list[dict]:
    settings = load_settings()
    filters = settings.get("filters", {})
    min_value = filters.get("insider_minimum_purchase", 50000)
    codes = filters.get("insider_transaction_codes", ["P"])

    purchases = scan_for_insider_buys(min_value=min_value, transaction_codes=codes)
    output_path = save_results(purchases)

    divider = "=" * 62
    print(f"\n{divider}")
    print(f"  INSIDER BUYING — {len(purchases)} qualifying purchase(s) found")
    print(divider)

    for p in purchases:
        label = " [CEO]" if p["is_ceo"] else " [CFO]" if p["is_cfo"] else ""
        title_display = p["officer_title"] or ("Director" if p["is_director"] else "10%+ Owner")
        cluster = "  *** CLUSTER: MULTIPLE INSIDERS ***" if p["multiple_insiders_buying"] else ""

        print(f"\n  {p['company_name']}  ({p['ticker']}){cluster}")
        print(f"    Insider:  {p['owner_name']}{label}  —  {title_display}")
        print(f"    Purchase: {p['shares']:,.0f} shares @ ${p['price_per_share']:.2f}  =  ${p['total_value']:,.0f}")
        print(f"    Date:     {p['transaction_date']}")
        print(f"    Filing:   {p['accession_no']}")

    if not purchases:
        print(f"\n  No open-market purchases >= ${min_value:,} found in the last 24 hours.")

    print(f"\n  Min threshold: ${min_value:,}  |  Codes: {codes}")
    print(f"  Results saved: {output_path}")
    print(divider)

    return purchases


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    main()
