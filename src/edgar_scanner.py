"""
Phase 1: Core EDGAR Scanner
Scans SEC EDGAR full-text search API (EFTS) for 8-K merger/acquisition filings
from the last 24 hours using configurable keywords from settings.json.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, load_settings, setup_logging

logger = setup_logging("edgar_scanner")

EFTS_BASE_URL = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_clean}/"

# SEC requires a User-Agent with contact info
_contact = os.getenv("GMAIL_ADDRESS", "user@example.com")
USER_AGENT = f"StockCatalystMonitor/1.0 {_contact}"

# SEC rate limit: max 10 requests/second
_MIN_INTERVAL = 0.11  # slightly over 1/10 to be safe


def _get_date_range(days_back: int = 1) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (now - timedelta(days=days_back)).strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    })
    return s


def _search_efts(
    session: requests.Session,
    keyword: str,
    start_date: str,
    end_date: str,
    offset: int = 0,
    page_size: int = 20,
    forms: str = "8-K",
) -> dict:
    """Call EDGAR EFTS and return the raw JSON response, or {} on error."""
    params = {
        "q": f'"{keyword}"',
        "forms": forms,
        "dateRange": "custom",
        "startdt": start_date,
        "enddt": end_date,
        "from": offset,
        "hits.hits.total.value": page_size,
    }
    url = f"{EFTS_BASE_URL}?{urlencode(params)}"
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as exc:
        logger.error(f"EFTS HTTP error {exc.response.status_code} for '{keyword}'")
    except requests.exceptions.ConnectionError:
        logger.error(f"EFTS connection error for '{keyword}'")
    except requests.exceptions.Timeout:
        logger.error(f"EFTS timeout for '{keyword}'")
    except Exception as exc:
        logger.error(f"EFTS unexpected error for '{keyword}': {exc}")
    return {}


def _get_ticker_from_cik(session: requests.Session, cik: str) -> Optional[str]:
    """Look up a company's ticker via the EDGAR submissions API."""
    try:
        url = SUBMISSIONS_URL.format(cik=cik.zfill(10))
        time.sleep(_MIN_INTERVAL)
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        tickers = resp.json().get("tickers", [])
        return tickers[0] if tickers else None
    except Exception as exc:
        logger.debug(f"Ticker lookup failed for CIK {cik}: {exc}")
        return None


def _parse_display_name(display_names: list) -> tuple[str, str]:
    """
    Parse company name and ticker from EFTS display_names.
    Format: "Company Name  (TICKER1, TICKER2)  (CIK 0001234567)"
    Returns (company_name, ticker).
    """
    if not display_names:
        return "Unknown", "N/A"

    raw = display_names[0]

    # Company name is everything before the first '('
    company_match = re.match(r"^(.+?)\s+\(", raw)
    company_name = company_match.group(1).strip() if company_match else raw.strip()

    # Tickers appear in the parentheses BEFORE "(CIK xxxxxxxx)"
    ticker_match = re.search(
        r"\(([A-Z][A-Z0-9\-\.]{0,9}(?:,\s*[A-Z][A-Z0-9\-\.]{0,9})*)\)\s+\(CIK", raw
    )
    if ticker_match:
        first_ticker = ticker_match.group(1).split(",")[0].strip()
        return company_name, first_ticker

    return company_name, "N/A"


def _build_filing_link(cik: str, accession_no: str) -> str:
    # CIK in EFTS may be zero-padded; strip for the URL path
    cik_num = str(int(cik)) if cik.lstrip("0") else cik
    accession_clean = accession_no.replace("-", "")
    return FILING_INDEX_URL.format(cik=cik_num, accession_clean=accession_clean)


def _parse_hit(hit: dict, keyword: str, session: requests.Session) -> Optional[dict]:
    """Convert a single EFTS hit into a structured filing dict."""
    source = hit.get("_source", {})

    # EFTS uses 'adsh' for accession number, not 'accession_no'
    accession_no = source.get("adsh", "").strip()
    if not accession_no:
        return None

    ciks = source.get("ciks", [])
    cik = ciks[0] if ciks else ""

    company_name, ticker = _parse_display_name(source.get("display_names", []))

    # Fall back to EDGAR submissions API if no ticker parsed
    if ticker == "N/A" and cik:
        time.sleep(_MIN_INTERVAL)
        fetched = _get_ticker_from_cik(session, cik)
        if fetched:
            ticker = fetched

    return {
        "accession_no": accession_no,
        "company_name": company_name,
        "ticker": ticker,
        "cik": cik,
        "file_date": source.get("file_date", ""),
        "form_type": source.get("form", "8-K"),
        "edgar_link": _build_filing_link(cik, accession_no) if cik else "",
        "matched_keyword": keyword,
    }


def scan_for_mergers(keywords: list[str], days_back: int = 1) -> list[dict]:
    """
    Search EDGAR for 8-K filings matching each keyword in the last `days_back` days.
    Returns a deduplicated list of filings sorted by file date descending.
    """
    start_date, end_date = _get_date_range(days_back)
    logger.info(f"Date range: {start_date} → {end_date}")

    session = _make_session()
    seen: set[str] = set()
    filings: list[dict] = []
    total_api_calls = 0

    for keyword in keywords:
        logger.info(f"Searching: '{keyword}'")

        # Paginate through all results for this keyword
        offset = 0
        page_size = 20
        while True:
            if total_api_calls > 0:
                time.sleep(_MIN_INTERVAL)

            data = _search_efts(session, keyword, start_date, end_date, offset, page_size)
            total_api_calls += 1

            if not data:
                break

            hits = data.get("hits", {}).get("hits", [])
            total_available = data.get("hits", {}).get("total", {})
            if isinstance(total_available, dict):
                total_available = total_available.get("value", 0)

            logger.info(f"  offset={offset}: {len(hits)} hits (total available: {total_available})")

            for hit in hits:
                accession_no = hit.get("_source", {}).get("adsh", "")
                if not accession_no or accession_no in seen:
                    continue
                seen.add(accession_no)

                time.sleep(_MIN_INTERVAL)
                total_api_calls += 1
                filing = _parse_hit(hit, keyword, session)
                if filing:
                    filings.append(filing)
                    logger.info(
                        f"  + {filing['company_name']} ({filing['ticker']}) "
                        f"[{filing['accession_no']}]"
                    )

            # Stop paginating if we have all results
            if offset + page_size >= total_available or not hits:
                break
            offset += page_size

    logger.info(
        f"Scan complete — {len(filings)} unique filings found, "
        f"{total_api_calls} API calls made"
    )
    filings.sort(key=lambda x: x.get("file_date", ""), reverse=True)
    return filings


def scan_for_registration_statements(
    company_name_keywords: list[str],
    days_back: int = 30,
) -> list[dict]:
    """
    RULE 3 — SpaceX S-1 Detection
    --------------------------------
    Search EDGAR for S-1 / S-1/A (IPO registration statements) filed by companies
    whose name contains any of the given keywords.

    Uses a wider lookback window (default 30 days) so a filing isn't missed if
    the position monitor was offline for a few days.

    Returns a list of matching filing dicts — same shape as scan_for_mergers().
    """
    start_date, end_date = _get_date_range(days_back)
    session = _make_session()
    seen: set[str] = set()
    filings: list[dict] = []
    total_calls = 0

    for keyword in company_name_keywords:
        logger.info(f"[S-1 Watch] Searching registrations for: '{keyword}'")
        offset = 0
        page_size = 20
        while True:
            if total_calls > 0:
                time.sleep(_MIN_INTERVAL)
            # Search S-1 and S-1/A forms for the company name
            data = _search_efts(
                session, keyword, start_date, end_date,
                offset=offset, page_size=page_size,
                forms="S-1,S-1/A,S-11,S-11/A",
            )
            total_calls += 1

            if not data:
                break

            hits = data.get("hits", {}).get("hits", [])
            total_available = data.get("hits", {}).get("total", {})
            if isinstance(total_available, dict):
                total_available = total_available.get("value", 0)

            logger.info(
                f"[S-1 Watch] offset={offset}: {len(hits)} hits "
                f"(total: {total_available})"
            )

            for hit in hits:
                accession_no = hit.get("_source", {}).get("adsh", "")
                if not accession_no or accession_no in seen:
                    continue
                seen.add(accession_no)
                filing = _parse_hit(hit, keyword, session)
                if filing:
                    filing["form_type"] = hit.get("_source", {}).get("form", "S-1")
                    filings.append(filing)

            if len(hits) < page_size or offset + page_size >= total_available:
                break
            offset += page_size

    logger.info(
        f"[S-1 Watch] Complete — {len(filings)} S-1 filings found, "
        f"{total_calls} API calls"
    )
    return filings


def save_results(filings: list[dict]) -> Path:
    """Save scan results to data/edgar_scan_results.json and return the path."""
    output_path = ROOT / "data" / "edgar_scan_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "scan_timestamp": datetime.now(timezone.utc).isoformat(),
        "total_filings": len(filings),
        "filings": filings,
    }
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    logger.info(f"Results saved → {output_path}")
    return output_path


def main() -> list[dict]:
    settings = load_settings()
    keywords = settings.get("filters", {}).get("merger_keywords", [])

    if not keywords:
        logger.error("No merger_keywords found in config/settings.json")
        sys.exit(1)

    logger.info(f"Loaded {len(keywords)} keywords from settings.json")
    filings = scan_for_mergers(keywords)
    output_path = save_results(filings)

    # Console summary
    divider = "=" * 62
    print(f"\n{divider}")
    print(f"  EDGAR SCAN RESULTS — {len(filings)} merger filing(s) found")
    print(divider)

    for f in filings:
        print(f"\n  {f['company_name']}  ({f['ticker']})")
        print(f"    Form:     {f['form_type']}  |  Filed: {f['file_date']}")
        print(f"    Keyword:  '{f['matched_keyword']}'")
        print(f"    ID:       {f['accession_no']}")
        print(f"    Link:     {f['edgar_link']}")

    if not filings:
        print("\n  No merger filings found in the last 24 hours.")

    print(f"\n  Keywords searched: {len(keywords)}")
    print(f"  Results saved to:  {output_path}")
    print(divider)

    return filings


if __name__ == "__main__":
    # Load .env if present (local dev only)
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    main()
