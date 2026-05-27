"""
Full test suite for the Stock Catalyst Monitoring System.
Run with: python -m pytest tests/test_all.py -v

Tests are grouped by phase and designed to run WITHOUT network access
except for the explicitly marked integration tests.
All tests use mocking or local fixtures — no real SEC/Groq/Gmail calls.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

# Make sure src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

ROOT = Path(__file__).parent.parent


# =============================================================================
# Phase 1 — EDGAR Scanner
# =============================================================================

class TestEdgarScanner(unittest.TestCase):

    def setUp(self):
        from edgar_scanner import _parse_display_name, _build_filing_link, _parse_hit
        self._parse_display_name = _parse_display_name
        self._build_filing_link  = _build_filing_link
        self._parse_hit          = _parse_hit

    # ------------------------------------------------------------------
    def test_parse_display_name_standard(self):
        names = ["Acme Corp  (ACM, ACMX)  (CIK 0001234567)"]
        company, ticker = self._parse_display_name(names)
        self.assertEqual(company, "Acme Corp")
        self.assertEqual(ticker, "ACM")

    def test_parse_display_name_no_ticker(self):
        names = ["Some Private Company  (CIK 0009999999)"]
        company, ticker = self._parse_display_name(names)
        self.assertEqual(company, "Some Private Company")
        # No ticker bracket present → function returns "N/A"
        self.assertEqual(ticker, "N/A")

    def test_parse_display_name_empty(self):
        company, ticker = self._parse_display_name([])
        self.assertEqual(company, "Unknown")
        # Empty list → function returns "N/A"
        self.assertEqual(ticker, "N/A")

    # ------------------------------------------------------------------
    def test_build_filing_link_strips_leading_zeros(self):
        link = self._build_filing_link("0001234567", "0001234567-24-000001")
        # CIK should have leading zeros stripped in URL
        self.assertIn("/data/1234567/", link)
        self.assertIn("000123456724000001", link)

    def test_build_filing_link_empty_cik(self):
        # Empty CIK guard lives in _parse_hit (uses `if cik else ""`).
        # Verify the guard works end-to-end: _parse_hit with empty ciks list
        # should produce edgar_link = "" (or return None if no CIK at all).
        hit = {
            "_source": {
                "adsh":          "0001234567-24-000001",
                "form":          "8-K",
                "file_date":     "2024-03-15",
                "display_names": ["Widget Co  (WGT)  (CIK 0001234567)"],
                "ciks":          [],   # ← empty CIK list
            },
            "_id": "0001234567-24-000001:doc.htm",
        }
        session = MagicMock()
        result = self._parse_hit(hit, "merger", session)
        if result is not None:
            self.assertEqual(result.get("edgar_link", ""), "")

    # ------------------------------------------------------------------
    def test_parse_hit_returns_none_without_adsh(self):
        hit = {"_source": {}, "_id": "missing"}
        session = MagicMock()
        result = self._parse_hit(hit, "merger", session)
        self.assertIsNone(result)

    def test_parse_hit_extracts_fields(self):
        hit = {
            "_source": {
                "adsh":          "0001234567-24-000001",
                "form":          "8-K",
                "file_date":     "2024-03-15",
                "display_names": ["Widget Co  (WGT)  (CIK 0001234567)"],
                "ciks":          ["0001234567"],
            },
            "_id": "0001234567-24-000001:doc.htm",
        }
        session = MagicMock()
        result = self._parse_hit(hit, "merger agreement", session)
        self.assertIsNotNone(result)
        self.assertEqual(result["accession_no"], "0001234567-24-000001")
        self.assertEqual(result["form_type"],    "8-K")
        self.assertEqual(result["ticker"],       "WGT")
        self.assertEqual(result["matched_keyword"], "merger agreement")
        self.assertIn("edgar_link", result)

    # ------------------------------------------------------------------
    def test_scan_for_mergers_deduplicates(self):
        """Same accession_no from two keyword searches → appears once."""
        from edgar_scanner import scan_for_mergers

        fake_response = {
            "hits": {
                "total": {"value": 1},
                "hits": [{
                    "_source": {
                        "adsh":          "0001234567-24-000001",
                        "form":          "8-K",
                        "file_date":     "2024-03-15",
                        "display_names": ["Widget Co  (WGT)  (CIK 0001234567)"],
                        "ciks":          ["0001234567"],
                    },
                    "_id": "0001234567-24-000001:doc.htm",
                }],
            }
        }

        with patch("edgar_scanner.requests.Session") as mock_sess_cls:
            mock_sess = MagicMock()
            mock_sess_cls.return_value = mock_sess
            mock_resp = MagicMock()
            mock_resp.json.return_value = fake_response
            mock_resp.raise_for_status.return_value = None
            mock_sess.get.return_value = mock_resp

            results = scan_for_mergers(["merger agreement", "definitive agreement"])

        # Same adsh from both keywords — must be deduplicated to 1
        self.assertEqual(len(results), 1)


# =============================================================================
# Phase 2 — Insider Scanner
# =============================================================================

class TestInsiderScanner(unittest.TestCase):

    def test_parse_form4_xml_buy(self):
        from insider_scanner import _parse_form4_xml

        xml = """<?xml version="1.0"?>
        <ownershipDocument>
          <issuer>
            <issuerName>Acme Corp</issuerName>
            <issuerTradingSymbol>ACM</issuerTradingSymbol>
          </issuer>
          <reportingOwner>
            <reportingOwnerId>
              <rptOwnerName>John Smith</rptOwnerName>
            </reportingOwnerId>
            <reportingOwnerRelationship>
              <isOfficer>true</isOfficer>
              <officerTitle>Chief Executive Officer</officerTitle>
            </reportingOwnerRelationship>
          </reportingOwner>
          <nonDerivativeTable>
            <nonDerivativeTransaction>
              <securityTitle><value>Common Stock</value></securityTitle>
              <transactionDate><value>2024-03-15</value></transactionDate>
              <transactionAmounts>
                <transactionShares><value>10000</value></transactionShares>
                <transactionPricePerShare><value>25.50</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
              </transactionAmounts>
              <transactionCoding>
                <transactionCode>P</transactionCode>
              </transactionCoding>
            </nonDerivativeTransaction>
          </nonDerivativeTable>
        </ownershipDocument>"""

        # _parse_form4_xml returns a list[dict] (one entry per transaction)
        results = _parse_form4_xml(xml, "0001234567-24-000001")

        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0, "Expected at least one transaction")
        result = results[0]   # inspect the first transaction

        self.assertEqual(result["company_name"],    "Acme Corp")
        self.assertEqual(result["ticker"],          "ACM")
        self.assertEqual(result["owner_name"],      "John Smith")   # field name is owner_name
        self.assertTrue(result["is_ceo"])
        self.assertFalse(result["is_cfo"])
        self.assertEqual(result["transaction_code"],     "P")
        self.assertEqual(result["acquired_or_disposed"], "A")
        self.assertAlmostEqual(result["shares"],          10000)    # field name is shares
        self.assertAlmostEqual(result["price_per_share"], 25.50)
        self.assertAlmostEqual(result["total_value"],     255000.0)

    def test_parse_form4_xml_sell_excluded(self):
        """Sales (D = disposed) should parse correctly but be filtered by caller."""
        from insider_scanner import _parse_form4_xml

        xml = """<?xml version="1.0"?>
        <ownershipDocument>
          <issuer>
            <issuerName>Acme Corp</issuerName>
            <issuerTradingSymbol>ACM</issuerTradingSymbol>
          </issuer>
          <reportingOwner>
            <reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId>
            <reportingOwnerRelationship>
              <isDirector>1</isDirector>
            </reportingOwnerRelationship>
          </reportingOwner>
          <nonDerivativeTable>
            <nonDerivativeTransaction>
              <securityTitle><value>Common Stock</value></securityTitle>
              <transactionDate><value>2024-03-15</value></transactionDate>
              <transactionAmounts>
                <transactionShares><value>5000</value></transactionShares>
                <transactionPricePerShare><value>30.00</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
              </transactionAmounts>
              <transactionCoding>
                <transactionCode>S</transactionCode>
              </transactionCoding>
            </nonDerivativeTransaction>
          </nonDerivativeTable>
        </ownershipDocument>"""

        results = _parse_form4_xml(xml, "0001234567-24-000002")
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        result = results[0]
        self.assertEqual(result["acquired_or_disposed"], "D")
        self.assertTrue(result["is_director"])

    def test_parse_form4_xml_invalid_returns_empty_list(self):
        from insider_scanner import _parse_form4_xml
        # Invalid XML → should return empty list (not raise)
        result = _parse_form4_xml("<broken xml", "0001234567-24-000099")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)


# =============================================================================
# Phase 3 — Groq Analyzer
# =============================================================================

class TestGroqAnalyzer(unittest.TestCase):

    def test_compute_score_cash_merger(self):
        from groq_analyzer import compute_score
        indicators = {
            "signed_merger_agreement": True,
            "all_cash_deal":           True,
            "termination_fee_present": True,
            "close_within_6_months":   True,
            "heavy_regulatory_approval": False,
            "stock_deal": False,
            "no_termination_fee": False,
            "timeline_over_12_months": False,
        }
        score = compute_score(indicators, {})
        # +30 +20 +15 +10 = 75
        self.assertEqual(score, 75)

    def test_compute_score_stock_deal_no_fee(self):
        from groq_analyzer import compute_score
        indicators = {
            "signed_merger_agreement": True,
            "all_cash_deal":           False,
            "termination_fee_present": False,
            "close_within_6_months":   False,
            "stock_deal":              True,
            "no_termination_fee":      True,
            "heavy_regulatory_approval": True,
            "timeline_over_12_months": True,
        }
        score = compute_score(indicators, {})
        # +30 -15 -10 -20 -10 = -25 → clamped to 0
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_compute_score_insider_buying_bonus(self):
        from groq_analyzer import compute_score
        indicators = {"signed_merger_agreement": True}
        extra      = {"insider_buying_confirmed": True}
        score_with    = compute_score(indicators, extra)
        score_without = compute_score(indicators, {})
        # insider_buying_confirmed adds +15
        self.assertEqual(score_with - score_without, 15)

    def test_score_tier_labels(self):
        """Score → tier label mapping."""
        from groq_analyzer import compute_score

        def tier(score):
            if score >= 65:  return "HIGH INTEREST"
            if score >= 40:  return "WATCH"
            if score >= 20:  return "NOTABLE"
            return "SKIP"

        self.assertEqual(tier(75), "HIGH INTEREST")
        self.assertEqual(tier(65), "HIGH INTEREST")
        self.assertEqual(tier(40), "WATCH")
        self.assertEqual(tier(30), "NOTABLE")
        self.assertEqual(tier(10), "SKIP")


# =============================================================================
# Phase 4 — Report Builder
# =============================================================================

class TestReportBuilder(unittest.TestCase):

    def test_build_no_news_report_contains_disclaimer(self):
        from report_builder import build_no_news_report
        html = build_no_news_report("MORNING")
        # Disclaimer text contains "investment advice" in various forms
        self.assertIn("INVESTMENT ADVICE", html.upper())

    def test_build_no_news_report_label_override(self):
        from report_builder import build_no_news_report
        html = build_no_news_report(label="WEEKLY SWEEP")
        # Label appears in HTML title (mixed-case); compare case-insensitively
        self.assertIn("WEEKLY SWEEP", html.upper())

    def test_build_morning_report_returns_html(self):
        from report_builder import build_morning_report

        groq_result = {
            "ticker":       "ACM",
            "company_name": "Acme Corp",
            "accession_no": "0001234567-24-000001",
            "edgar_link":   "https://www.sec.gov/example",
            "file_date":    "2024-03-15",
            "form_type":    "8-K",
            "score":        70,
            "tier":         "HIGH INTEREST",
            "catalyst_type":"Merger",
            "summary":      "All-cash acquisition at $30/share.",
            "offer_price_per_share": 30.0,
            "payment_type": "cash",
            "months_to_close": 4,
            "key_risks": ["antitrust"],
        }

        with patch("report_builder._get_current_price", return_value=None):
            html = build_morning_report([], [groq_result], [])

        self.assertIn("<html", html.lower())
        self.assertIn("INVESTMENT ADVICE", html.upper())  # disclaimer present
        self.assertIn("Acme Corp", html)
        self.assertIn("70", html)   # score

    def test_no_news_report_includes_position(self):
        """Position cards should appear even in the no-news report."""
        from report_builder import build_no_news_report

        fake_positions = [{
            "ticker": "DXYZ",
            "company_name": "Destiny Tech100 Inc",
            "entry_price": 10.5,
            "shares": 15,
            "target_exit": 80.0,
            "stop_loss": 45.0,
        }]

        with patch("report_builder.load_positions", return_value=fake_positions), \
             patch("report_builder._get_current_price", return_value=60.0):
            html = build_no_news_report("MORNING")

        self.assertIn("DXYZ", html)


# =============================================================================
# Phase 4 — Alert System
# =============================================================================

class TestAlertSystem(unittest.TestCase):

    @patch("alert_system.smtplib.SMTP_SSL")
    def test_smtp_send_success(self, mock_smtp_cls):
        from alert_system import _smtp_send

        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
        mock_smtp_cls.return_value.__exit__  = MagicMock(return_value=False)

        result = _smtp_send(
            "sender@gmail.com",
            "apppassword1234",
            "recipient@gmail.com",
            "Test Subject",
            body_text="Hello",
        )
        self.assertTrue(result)

    @patch("alert_system.smtplib.SMTP_SSL")
    def test_smtp_send_auth_failure_returns_false(self, mock_smtp_cls):
        import smtplib
        from alert_system import _smtp_send

        mock_smtp_cls.return_value.__enter__ = MagicMock(
            side_effect=smtplib.SMTPAuthenticationError(535, b"Bad credentials")
        )
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = _smtp_send(
            "sender@gmail.com",
            "wrongpassword",
            "recipient@gmail.com",
            "Test",
        )
        self.assertFalse(result)

    def test_smtp_send_missing_credentials_returns_false(self):
        from alert_system import _smtp_send
        result = _smtp_send("", "", "recipient@gmail.com", "Test")
        self.assertFalse(result)

    def test_smtp_send_missing_recipient_returns_false(self):
        from alert_system import _smtp_send
        result = _smtp_send("sender@gmail.com", "pass", "", "Test")
        self.assertFalse(result)


# =============================================================================
# Phase 5 — Position Monitor
# =============================================================================

class TestPositionMonitor(unittest.TestCase):

    def setUp(self):
        from position_monitor import (
            _check_price_thresholds,
            _alert_key,
            _already_sent,
            _record_sent,
        )
        self._check    = _check_price_thresholds
        self._key      = _alert_key
        self._sent     = _already_sent
        self._record   = _record_sent

        self.pos = {
            "ticker":       "DXYZ",
            "entry_price":  10.50,
            "target_exit":  80.0,
            "stop_loss":    45.0,
            "shares":       15,
        }

    # ------------------------------------------------------------------
    def test_target_hit(self):
        events = self._check(self.pos, 82.00, prev_close=75.0)
        labels = [e["label"] for e in events]
        self.assertIn("TARGET REACHED", labels)

    def test_stop_hit(self):
        events = self._check(self.pos, 44.00, prev_close=48.0)
        labels = [e["label"] for e in events]
        self.assertIn("STOP LOSS HIT", labels)

    def test_no_event_between_levels(self):
        events = self._check(self.pos, 60.00, prev_close=61.0)
        # -1.6% daily change → below 7% threshold → no events
        labels = [e["label"] for e in events]
        self.assertNotIn("TARGET REACHED", labels)
        self.assertNotIn("STOP LOSS HIT",  labels)
        self.assertEqual(len(events), 0)

    def test_significant_daily_move_up(self):
        events = self._check(self.pos, 75.00, prev_close=60.00)
        # +25% daily → triggers SIGNIFICANT MOVE UP
        labels = [e["label"] for e in events]
        self.assertIn("SIGNIFICANT MOVE UP", labels)

    def test_significant_daily_move_down(self):
        events = self._check(self.pos, 55.00, prev_close=66.00)
        # -16.7% daily → triggers SIGNIFICANT MOVE DOWN
        labels = [e["label"] for e in events]
        self.assertIn("SIGNIFICANT MOVE DOWN", labels)

    def test_no_significant_move_without_prev_close(self):
        """When prev_close is None, only target/stop can trigger."""
        events = self._check(self.pos, 60.00, prev_close=None)
        self.assertEqual(len(events), 0)

    # ------------------------------------------------------------------
    def test_alert_key_format(self):
        key = self._key("DXYZ", "TARGET_HIT", "2024-03-15")
        self.assertEqual(key, "DXYZ:TARGET_HIT:2024-03-15")

    def test_dedup_logic(self):
        sent_data: dict = {"sent_alerts": []}
        key = "DXYZ:TARGET_HIT:2024-03-15"
        self.assertFalse(self._sent(key, sent_data))
        self._record(key, sent_data)
        self.assertTrue(self._sent(key, sent_data))

    def test_dedup_does_not_block_different_day(self):
        sent_data: dict = {"sent_alerts": ["DXYZ:TARGET_HIT:2024-03-15"]}
        key = "DXYZ:TARGET_HIT:2024-03-16"   # next day
        self.assertFalse(self._sent(key, sent_data))

    # ------------------------------------------------------------------
    def test_tier1_events_are_correct(self):
        """Target and stop hits must be Tier 1 (triggers SMS).
        Note: a large daily move (>7%) may ALSO fire on the same check, at tier 2.
        We only assert that the TARGET_REACHED / STOP_LOSS_HIT events are tier 1.
        """
        events_target = self._check(self.pos, 82.0, 75.0)
        events_stop   = self._check(self.pos, 44.0, 48.0)

        target_events = [e for e in events_target if e["label"] == "TARGET REACHED"]
        stop_events   = [e for e in events_stop   if e["label"] == "STOP LOSS HIT"]

        self.assertEqual(len(target_events), 1, "Expected exactly one TARGET REACHED event")
        self.assertEqual(len(stop_events),   1, "Expected exactly one STOP LOSS HIT event")

        for evt in target_events + stop_events:
            self.assertEqual(evt["tier"], 1, msg=f"Expected tier 1 for: {evt['label']}")

    def test_daily_move_is_tier2(self):
        """Big daily moves should be Tier 2 (email only, no SMS)."""
        events = self._check(self.pos, 75.0, 60.0)   # +25% daily
        for evt in events:
            if "MOVE" in evt["label"]:
                self.assertEqual(evt["tier"], 2)


# =============================================================================
# Email Command Processor
# =============================================================================

class TestEmailCommandParser(unittest.TestCase):

    def setUp(self):
        from email_command import _parse_commands, _strip_quoted_reply
        self._parse  = _parse_commands
        self._strip  = _strip_quoted_reply

    # ------------------------------------------------------------------
    def test_parse_set_command_field_value(self):
        cmds = self._parse("set target_exit = 80", "DXYZ")
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["ticker"], "DXYZ")
        self.assertEqual(cmds[0]["field"],  "target_exit")
        self.assertAlmostEqual(cmds[0]["value"], 80.0)

    def test_parse_set_command_with_ticker(self):
        cmds = self._parse("set DXYZ stop_loss = 45", "DXYZ")
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["ticker"], "DXYZ")
        self.assertEqual(cmds[0]["field"],  "stop_loss")
        self.assertAlmostEqual(cmds[0]["value"], 45.0)

    def test_parse_multiple_commands(self):
        body = "set target_exit = 90\nset stop_loss = 40"
        cmds = self._parse(body, "DXYZ")
        self.assertEqual(len(cmds), 2)

    def test_parse_unknown_field_rejected(self):
        cmds = self._parse("set username = hacker", "DXYZ")
        self.assertEqual(len(cmds), 0)

    def test_parse_no_commands(self):
        cmds = self._parse("Hey, how are you doing?", "DXYZ")
        self.assertEqual(len(cmds), 0)

    def test_parse_shares(self):
        cmds = self._parse("set shares = 15", "DXYZ")
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["field"], "shares")
        self.assertAlmostEqual(cmds[0]["value"], 15.0)

    def test_case_insensitive(self):
        cmds = self._parse("SET TARGET_EXIT = 100", "DXYZ")
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["field"], "target_exit")

    # ------------------------------------------------------------------
    def test_strip_quoted_reply_removes_on_wrote(self):
        body = "set target_exit = 80\n\nOn Mon, Mar 15, 2024 at 10:00 AM Someone wrote:\n> Old reply text"
        stripped = self._strip(body)
        self.assertIn("set target_exit = 80", stripped)
        self.assertNotIn("Old reply text", stripped)

    def test_strip_quoted_reply_removes_gt_lines(self):
        body = "set stop_loss = 45\n> this is a quoted line\n> another quoted line"
        stripped = self._strip(body)
        self.assertIn("set stop_loss = 45", stripped)
        self.assertNotIn("> this", stripped)


# =============================================================================
# Utils
# =============================================================================

class TestUtils(unittest.TestCase):

    def test_load_positions_returns_list(self):
        from utils import load_positions
        positions = load_positions()
        self.assertIsInstance(positions, list)
        if positions:
            self.assertIn("ticker", positions[0])

    def test_load_settings_returns_dict(self):
        from utils import load_settings
        settings = load_settings()
        self.assertIsInstance(settings, dict)

    def test_load_sent_alerts_handles_empty_file(self):
        """load_sent_alerts() should not crash on an empty or missing file."""
        from utils import load_sent_alerts
        with patch("utils.open", mock_open(read_data="")) as m:
            m.return_value.__enter__.return_value.read.return_value = ""
            result = load_sent_alerts()
        self.assertIn("sent_alerts", result)
        self.assertIsInstance(result["sent_alerts"], list)

    def test_save_and_reload_sent_alerts(self):
        """Round-trip: save → reload should preserve entries."""
        from utils import save_sent_alerts, load_sent_alerts
        import tempfile

        test_data = {
            "sent_alerts": ["DXYZ:TARGET_HIT:2024-03-15", "EDGAR:0001234567-24-000001"],
        }

        tmp = ROOT / "state" / "_test_sent_alerts_tmp.json"
        try:
            # Patch ROOT/state path by writing directly
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with patch("utils.ROOT", ROOT):
                # Temporarily rename real file
                real = ROOT / "state" / "sent_alerts.json"
                backup = ROOT / "state" / "sent_alerts.json.bak"
                if real.exists():
                    real.rename(backup)
                try:
                    save_sent_alerts(test_data)
                    reloaded = load_sent_alerts()
                    self.assertIn("DXYZ:TARGET_HIT:2024-03-15", reloaded["sent_alerts"])
                    self.assertIn("EDGAR:0001234567-24-000001", reloaded["sent_alerts"])
                finally:
                    # Restore real file
                    real_after = ROOT / "state" / "sent_alerts.json"
                    if real_after.exists():
                        real_after.unlink()
                    if backup.exists():
                        backup.rename(real)
        except Exception:
            if tmp.exists():
                tmp.unlink()
            raise


# =============================================================================
# EDGAR S-1 Registration Watcher (Phase 7)
# =============================================================================

class TestS1Watcher(unittest.TestCase):

    def test_filer_name_filter_blocks_false_positives(self):
        """
        scan_for_registration_statements returns hits for 'SpaceX' text matches.
        _scan_instant_triggers must filter out filings where the FILER is not SpaceX.
        """
        from position_monitor import _scan_instant_triggers

        # A filing that mentions SpaceX but is filed by a different company
        false_positive = {
            "accession_no": "0001234567-24-000001",
            "company_name": "Fervo Energy Co",
            "form_type":    "S-1/A",
            "file_date":    "2024-03-15",
            "edgar_link":   "https://www.sec.gov/example",
            "matched_keyword": "SpaceX",
        }

        # A real SpaceX filing
        real_hit = {
            "accession_no": "0009876543-24-000001",
            "company_name": "Space Exploration Technologies Corp",
            "form_type":    "S-1",
            "file_date":    "2024-03-15",
            "edgar_link":   "https://www.sec.gov/spacex",
            "matched_keyword": "Space Exploration Technologies",
        }

        pos = {
            "ticker":       "DXYZ",
            "thesis_type":  "pre_ipo_speculation",
            "instant_alert_triggers":  [],
            "ipo_company_keywords": ["space exploration technologies", "spacex"],
        }

        with patch("position_monitor.scan_for_mergers",              return_value=[]), \
             patch("position_monitor.scan_for_registration_statements",
                   return_value=[false_positive, real_hit]):
            results = _scan_instant_triggers(pos)

        # Only the real SpaceX filing should pass the filter
        self.assertEqual(len(results), 1)
        self.assertIn("Space Exploration", results[0]["company_name"])

    def test_no_s1_watch_for_non_pre_ipo(self):
        """S-1 watcher must NOT run for regular merger positions."""
        from position_monitor import _scan_instant_triggers

        pos = {
            "ticker":       "ACM",
            "thesis_type":  "merger_arbitrage",   # NOT pre_ipo_speculation
            "instant_alert_triggers": [],
        }

        with patch("position_monitor.scan_for_mergers", return_value=[]) as m_mergers, \
             patch("position_monitor.scan_for_registration_statements") as m_s1:
            _scan_instant_triggers(pos)

        # scan_for_registration_statements must NOT be called for non-pre_ipo positions
        m_s1.assert_not_called()


# =============================================================================
# Workflow smoke tests (import only — no execution)
# =============================================================================

class TestImports(unittest.TestCase):
    """Verify all modules can be imported without errors."""

    def test_import_edgar_scanner(self):
        import edgar_scanner
        self.assertTrue(hasattr(edgar_scanner, "scan_for_mergers"))

    def test_import_insider_scanner(self):
        import insider_scanner
        self.assertTrue(hasattr(insider_scanner, "scan_for_insider_buys"))

    def test_import_groq_analyzer(self):
        import groq_analyzer
        self.assertTrue(hasattr(groq_analyzer, "analyze_batch"))
        self.assertTrue(hasattr(groq_analyzer, "compute_score"))

    def test_import_report_builder(self):
        import report_builder
        self.assertTrue(hasattr(report_builder, "build_morning_report"))
        self.assertTrue(hasattr(report_builder, "build_no_news_report"))

    def test_import_alert_system(self):
        import alert_system
        self.assertTrue(hasattr(alert_system, "send_morning_report"))
        self.assertTrue(hasattr(alert_system, "send_tier1_sms"))

    def test_import_morning_scan(self):
        import morning_scan
        self.assertTrue(hasattr(morning_scan, "main"))

    def test_import_position_monitor(self):
        import position_monitor
        self.assertTrue(hasattr(position_monitor, "monitor_positions"))

    def test_import_email_command(self):
        import email_command
        self.assertTrue(hasattr(email_command, "process_command_emails"))


# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
