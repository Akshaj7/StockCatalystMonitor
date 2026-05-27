"""
Phase 3: Groq AI Analyzer
Accepts raw SEC filing text, sends it to the Groq API for plain-English analysis,
applies the 0-100 scoring rubric, and returns a structured result dict.
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

sys.path.insert(0, str(Path(__file__).parent))
from utils import ROOT, setup_logging

logger = setup_logging("groq_analyzer")

# Token budget — warn at 80% of the 500k/day free limit
DAILY_TOKEN_LIMIT = 500_000
TOKEN_WARN_THRESHOLD = 400_000

# Filing text is truncated to this many characters before sending to Groq.
# ~12k chars ≈ ~3,000 tokens — keeps each call cheap.
MAX_FILING_CHARS = 12_000

# Groq retry config
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # seconds (doubled each retry)

# Preferred model order — first available 70B model is used
PREFERRED_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
]

# ---------------------------------------------------------------------------
# Scoring rubric (from PRD Section 5)
# ---------------------------------------------------------------------------
SCORING_RUBRIC = {
    "signed_merger_agreement":   +30,
    "all_cash_deal":             +20,
    "termination_fee_present":   +15,
    "close_within_6_months":     +10,
    "insider_buying_confirmed":  +15,
    "unusual_options_activity":  +10,
    "known_activist_involved":   +5,
    "heavy_regulatory_approval": -20,
    "stock_deal":                -15,
    "no_termination_fee":        -10,
    "timeline_over_12_months":   -10,
    "insider_selling_detected":  -15,
}

SCORE_LABELS = {
    (60, 100): "HIGH INTEREST",
    (40, 59):  "WATCH",
    (20, 39):  "NOTABLE",
    (0,  19):  "SKIP",
}

SYSTEM_PROMPT = """You are an expert securities analyst specializing in merger arbitrage and SEC filing analysis.

Analyze the provided SEC filing text and return ONLY a valid JSON object (no markdown, no extra text) with exactly these fields:

{
  "catalyst_type": "<merger|insider_buying|activist|going_private|tender_offer|other>",
  "summary": "<plain English summary in 3 sentences maximum. Write for a retail investor.>",
  "offer_price_per_share": <number or null>,
  "payment_type": "<cash|stock|mixed|unknown>",
  "months_to_close": <integer estimate or null>,
  "termination_fee_amount": <number in dollars or null>,
  "key_risks": ["<risk 1>", "<risk 2>"],
  "indicators": {
    "signed_merger_agreement": <true/false>,
    "all_cash_deal": <true/false>,
    "termination_fee_present": <true/false>,
    "close_within_6_months": <true/false>,
    "heavy_regulatory_approval": <true/false>,
    "stock_deal": <true/false>,
    "no_termination_fee": <true/false>,
    "timeline_over_12_months": <true/false>
  }
}

Rules:
- signed_merger_agreement: true only if a definitive agreement is confirmed (not LOI or rumor)
- all_cash_deal: true only if 100% cash consideration
- stock_deal: true if any stock component in the merger consideration
- close_within_6_months: true if expected close is within 6 months
- heavy_regulatory_approval: true if antitrust or significant government review is required
- no_termination_fee and termination_fee_present are mutually exclusive
- Be conservative: if uncertain, default to false"""


# ---------------------------------------------------------------------------
# Groq client helpers
# ---------------------------------------------------------------------------

_daily_tokens_used = 0
_groq_model: Optional[str] = None


def _get_groq_client():
    """Lazy-import groq and return a client instance."""
    try:
        from groq import Groq
    except ImportError:
        raise ImportError("groq package not installed. Run: pip install groq")
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GROQ_API_KEY environment variable is not set.")
    return Groq(api_key=api_key)


def _resolve_model(client) -> str:
    """Find the best available Groq model from the preferred list."""
    global _groq_model
    if _groq_model:
        return _groq_model
    try:
        available = {m.id for m in client.models.list().data}
        for candidate in PREFERRED_MODELS:
            if candidate in available:
                _groq_model = candidate
                logger.info(f"Using Groq model: {_groq_model}")
                return _groq_model
    except Exception as exc:
        logger.warning(f"Could not list Groq models: {exc} — defaulting to {PREFERRED_MODELS[0]}")
    _groq_model = PREFERRED_MODELS[0]
    return _groq_model


def _call_groq(client, model: str, filing_text: str) -> tuple[str, int]:
    """
    Call Groq with retry + exponential backoff.
    Returns (response_text, tokens_used).
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Analyze this SEC filing:\n\n{filing_text[:MAX_FILING_CHARS]}"},
    ]
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=800,
            )
            tokens = completion.usage.total_tokens if completion.usage else 0
            return completion.choices[0].message.content, tokens
        except Exception as exc:
            last_exc = exc
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(f"Groq call failed (attempt {attempt + 1}/{MAX_RETRIES}): {exc} — retrying in {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"Groq API failed after {MAX_RETRIES} attempts: {last_exc}")


# ---------------------------------------------------------------------------
# Filing text fetcher
# ---------------------------------------------------------------------------

def fetch_filing_text(
    cik: str,
    accession_no: str,
    filename: str,
    session: Optional[requests.Session] = None,
) -> str:
    """
    Download and return the plain text of a filing document.
    Strips HTML/XML tags. Returns empty string on failure.
    """
    if not cik or not accession_no or not filename:
        return ""
    try:
        cik_num = str(int(cik))
    except (ValueError, TypeError):
        cik_num = cik.lstrip("0") or cik

    accession_clean = accession_no.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{filename}"

    _session = session or requests.Session()
    _session.headers.setdefault(
        "User-Agent",
        f"StockCatalystMonitor/1.0 {os.getenv('GMAIL_ADDRESS', 'user@example.com')}",
    )

    try:
        resp = _session.get(url, timeout=30)
        resp.raise_for_status()
        raw = resp.text
    except Exception as exc:
        logger.warning(f"Could not fetch filing text from {url}: {exc}")
        return ""

    # Strip HTML/XML tags
    text = re.sub(r"<[^>]+>", " ", raw)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def compute_score(indicators: dict, extra_signals: Optional[dict] = None) -> int:
    """
    Apply the PRD scoring rubric to a dict of boolean indicators.
    extra_signals can add insider_buying_confirmed, unusual_options_activity,
    known_activist_involved, insider_selling_detected.
    """
    combined = dict(indicators)
    if extra_signals:
        combined.update(extra_signals)

    raw = sum(
        SCORING_RUBRIC[key] for key, flag in combined.items()
        if key in SCORING_RUBRIC and flag
    )
    return max(0, min(100, raw))


def score_label(score: int) -> str:
    for (lo, hi), label in SCORE_LABELS.items():
        if lo <= score <= hi:
            return label
    return "SKIP"


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_filing(
    filing_text: str,
    filing_metadata: Optional[dict] = None,
    extra_signals: Optional[dict] = None,
) -> dict:
    """
    Analyze a filing with Groq and return a structured result.

    Args:
        filing_text: Raw text of the SEC filing (HTML/XML stripped or not).
        filing_metadata: Optional dict with company_name, ticker, accession_no, etc.
        extra_signals: Optional dict of boolean flags for scoring factors not
                       detectable from the filing text alone (e.g. insider_buying_confirmed).

    Returns dict with keys: summary, score, label, catalyst_type, offer_price,
                            payment_type, months_to_close, termination_fee,
                            key_risks, indicators, tokens_used.
    """
    global _daily_tokens_used

    client = _get_groq_client()
    model = _resolve_model(client)

    # Strip any HTML that wasn't pre-cleaned
    clean_text = re.sub(r"<[^>]+>", " ", filing_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()

    raw_response, tokens = _call_groq(client, model, clean_text)
    _daily_tokens_used += tokens

    if _daily_tokens_used >= TOKEN_WARN_THRESHOLD:
        logger.warning(
            f"Daily token usage at {_daily_tokens_used:,} / {DAILY_TOKEN_LIMIT:,} "
            f"({100 * _daily_tokens_used / DAILY_TOKEN_LIMIT:.0f}%) — approaching free limit"
        )

    # Parse Groq's JSON response
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError:
        # Try to extract JSON from the response if Groq added extra text
        match = re.search(r"\{.*\}", raw_response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
            except json.JSONDecodeError:
                parsed = {}
        else:
            parsed = {}
        if not parsed:
            logger.error(f"Could not parse Groq JSON response: {raw_response[:300]}")

    indicators = parsed.get("indicators", {})
    score = compute_score(indicators, extra_signals)
    label = score_label(score)

    meta = filing_metadata or {}
    result = {
        "company_name": meta.get("company_name", "Unknown"),
        "ticker": meta.get("ticker", "N/A"),
        "accession_no": meta.get("accession_no", ""),
        "edgar_link": meta.get("edgar_link", ""),
        "file_date": meta.get("file_date", ""),
        "catalyst_type": parsed.get("catalyst_type", "unknown"),
        "summary": parsed.get("summary", ""),
        "offer_price": parsed.get("offer_price_per_share"),
        "payment_type": parsed.get("payment_type", "unknown"),
        "months_to_close": parsed.get("months_to_close"),
        "termination_fee": parsed.get("termination_fee_amount"),
        "key_risks": parsed.get("key_risks", []),
        "indicators": indicators,
        "score": score,
        "label": label,
        "tokens_used": tokens,
    }

    logger.info(
        f"Analyzed: {result['company_name']} ({result['ticker']}) — "
        f"Score: {score}/100 [{label}] — Tokens: {tokens}"
    )
    return result


def analyze_batch(filings: list[dict], extra_signals_map: Optional[dict] = None) -> list[dict]:
    """
    Analyze a list of filing dicts (as returned by edgar_scanner).
    Only analyzes filings with a score threshold worth pursuing (skips obvious noise).
    Fetches filing text for each entry.

    extra_signals_map: optional dict keyed by accession_no → extra_signals dict.
    """
    results = []
    http_session = requests.Session()
    http_session.headers["User-Agent"] = (
        f"StockCatalystMonitor/1.0 {os.getenv('GMAIL_ADDRESS', 'user@example.com')}"
    )

    for filing in filings:
        accession_no = filing.get("accession_no", "")
        cik = filing.get("cik", "")

        # Derive filename from EFTS _id if available, otherwise skip
        # The edgar_scanner stores the full edgar_link but not the filename.
        # We attempt to fetch the filing index to find the primary document.
        filing_text = _fetch_primary_document(cik, accession_no, http_session)
        if not filing_text:
            logger.debug(f"No text for {accession_no} — skipping AI analysis")
            continue

        extra = (extra_signals_map or {}).get(accession_no, {})
        result = analyze_filing(filing_text, filing_metadata=filing, extra_signals=extra)
        results.append(result)

        # Small delay to stay within Groq rate limits (30 req/min = 1 per 2s)
        time.sleep(4.0)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def _fetch_primary_document(cik: str, accession_no: str, session: requests.Session) -> str:
    """
    Fetch the primary document of a filing by reading the filing index JSON,
    then downloading the first non-index, non-graphic document.
    """
    if not cik or not accession_no:
        return ""
    try:
        cik_num = str(int(cik))
    except (ValueError, TypeError):
        cik_num = cik.lstrip("0") or cik

    accession_clean = accession_no.replace("-", "")
    index_url = (
        f"https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={cik_num}&type=8-K&dateb=&owner=include&count=1"
        f"&search_text=&output=atom"
    )

    # Simpler: use the submission index JSON
    index_json_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/"
        f"{accession_no}-index.json"
    )
    try:
        resp = session.get(index_json_url, timeout=15)
        if resp.status_code == 200:
            index_data = resp.json()
            docs = index_data.get("items", [])
            for doc in docs:
                doc_type = doc.get("type", "")
                filename = doc.get("name", "")
                if not filename:
                    continue
                ext = filename.lower().rsplit(".", 1)[-1]
                # Skip index pages, graphics, zip files
                if ext in ("htm", "html", "txt") and "index" not in filename.lower():
                    text = fetch_filing_text(cik_num, accession_no, filename, session)
                    if text and len(text) > 500:
                        return text
    except Exception as exc:
        logger.debug(f"Index JSON fetch failed for {accession_no}: {exc}")

    # Final fallback: try fetching the accession_no.txt full submission
    try:
        txt_url = f"https://www.sec.gov/Archives/edgar/data/{cik_num}/{accession_clean}/{accession_no}.txt"
        resp = session.get(txt_url, timeout=20)
        if resp.status_code == 200 and len(resp.text) > 500:
            clean = re.sub(r"<[^>]+>", " ", resp.text)
            return re.sub(r"\s+", " ", clean).strip()
    except Exception:
        pass

    return ""


# ---------------------------------------------------------------------------
# CLI test entry point
# ---------------------------------------------------------------------------

def main():
    # Test with a sample merger filing from today's EDGAR scan results
    scan_file = ROOT / "data" / "edgar_scan_results.json"
    if not scan_file.exists():
        print("No edgar_scan_results.json found. Run edgar_scanner.py first.")
        return

    with open(scan_file) as f:
        data = json.load(f)

    filings = data.get("filings", [])
    if not filings:
        print("No filings in scan results.")
        return

    # Test on the first 3 filings to conserve tokens
    test_filings = filings[:3]
    print(f"\nAnalyzing {len(test_filings)} filings with Groq...\n")

    results = analyze_batch(test_filings)

    divider = "=" * 62
    print(f"\n{divider}")
    print(f"  GROQ ANALYSIS RESULTS — {len(results)} filing(s) analyzed")
    print(divider)

    for r in results:
        print(f"\n  {r['company_name']}  ({r['ticker']})")
        print(f"  Score:  {r['score']}/100  [{r['label']}]")
        print(f"  Type:   {r['catalyst_type']}")
        print(f"  Summary:")
        # Word-wrap the summary
        words = r["summary"].split()
        line = "    "
        for word in words:
            if len(line) + len(word) > 75:
                print(line)
                line = "    " + word + " "
            else:
                line += word + " "
        if line.strip():
            print(line)
        if r["offer_price"]:
            print(f"  Offer:  ${r['offer_price']} per share ({r['payment_type']})")
        if r["months_to_close"]:
            print(f"  Close:  ~{r['months_to_close']} months")
        if r["key_risks"]:
            print(f"  Risks:  {', '.join(r['key_risks'][:3])}")
        print(f"  Tokens: {r['tokens_used']:,}")

    total_tokens = sum(r["tokens_used"] for r in results)
    print(f"\n  Total tokens used this session: {total_tokens:,}")
    print(f"  Daily budget remaining: ~{DAILY_TOKEN_LIMIT - _daily_tokens_used:,} / {DAILY_TOKEN_LIMIT:,}")
    print(divider)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    main()
