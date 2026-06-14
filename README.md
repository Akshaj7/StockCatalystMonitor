# Stock Catalyst Monitoring System

A fully automated, **$0/month** stock-catalyst monitoring system that runs entirely on free tooling. It scans public SEC EDGAR filings for merger deals, insider buying, and other catalysts, monitors the positions you hold, scores every finding, and emails you plain-English reports written by AI — all on an automated schedule via GitHub Actions, with no servers to maintain.

> **You make every decision.** The system only finds and reports. Nothing is ever bought or sold automatically.

---

## Highlights

- **Automated SEC EDGAR scanning** — searches for 8-K merger/acquisition filings and Form 4 insider purchases on a schedule.
- **AI-written summaries** — uses the free Groq API (Llama) to turn dense legal filings into 3-sentence plain-English explanations.
- **0–100 catalyst scoring** — every finding is ranked so you instantly know what deserves attention.
- **Position monitoring** — tracks the stocks you hold against your thesis, target, and stop-loss.
- **Email + SMS alerts** — daily HTML reports by email, plus urgent text alerts via your carrier's email-to-SMS gateway.
- **Control by email** — update positions, add/remove tickers, or request a status report just by emailing yourself a command.
- **Runs while you sleep** — scheduled entirely through GitHub Actions. No server, no subscription, no maintenance.

---

## How it works

```
SEC EDGAR  ──►  Scanners  ──►  Groq AI analysis + scoring  ──►  Report builder  ──►  Email / SMS
(filings)      (edgar,         (groq_analyzer.py)              (report_builder)      (alert_system)
                insider)
                                                                      ▲
                            Your config (positions / settings) ───────┘
                                       ▲
                            Email commands (email_command.py)
```

Every run is triggered by a GitHub Actions workflow on a cron schedule. The scanners pull recent filings from the free SEC EDGAR API, the analyzer scores and summarizes them, and the report builder formats and sends the output to your inbox (and your phone for urgent events).

---

## Tech stack

| Tool | Purpose | Cost |
|------|---------|------|
| **Python 3.11** | Runtime for all scripts | Free |
| **SEC EDGAR API** | Source of all filings | Free (public) |
| **Groq API (Llama)** | AI analysis & plain-English summaries | Free tier |
| **Gmail SMTP / IMAP** | Sends reports, receives email commands | Free |
| **Carrier SMS gateway** | Urgent text alerts (email-to-SMS) | Free |
| **GitHub Actions** | Scheduled automation | Free tier |

Python dependencies (`requirements.txt`):

```
requests>=2.31.0
python-dotenv>=1.0.0
yfinance>=0.2.28
groq>=0.4.2
```

---

## Project structure

```
StockCatalystMonitor/
├── .github/workflows/
│   ├── morning_scan.yml        # Deep overnight scan, before market open
│   ├── evening_scan.yml        # After-hours filings + insider buying recap
│   ├── position_monitor.yml    # Checks held positions during market hours
│   ├── sunday_sweep.yml        # Catches weekend filings before Monday
│   └── email_command.yml       # Processes email commands every 30 min
├── src/
│   ├── edgar_scanner.py        # Scans EDGAR for merger / 8-K filings
│   ├── insider_scanner.py      # Scans Form 4 insider purchases
│   ├── groq_analyzer.py        # AI analysis + 0–100 scoring
│   ├── position_monitor.py     # Monitors your held positions
│   ├── report_builder.py       # Builds formatted HTML email reports
│   ├── alert_system.py         # Email + SMS delivery
│   ├── email_command.py        # Update config by emailing yourself
│   ├── morning_scan.py         # Orchestrates the morning report
│   └── utils.py                # Shared helpers
├── config/
│   ├── positions.json          # Your current holdings
│   ├── watchlist.json          # Stocks you're watching
│   └── settings.json           # Scanning, filters, and email settings
├── state/
│   ├── sent_alerts.json        # Dedupe — prevents duplicate SMS
│   └── processed_command_uids.json  # Tracks processed command emails
├── tests/
├── requirements.txt
└── .env.example
```

---

## Setup

### 1. Prerequisites (all free)

- A **Groq API key** — sign up at [console.groq.com](https://console.groq.com), create a key. No credit card required.
- A **Gmail App Password** — enable 2FA on your Google account, then create a 16-character app password (Security → App passwords). Use this, **not** your regular Gmail password.
- Your **carrier's SMS gateway** address for text alerts, e.g.:
  - AT&T: `number@txt.att.net`
  - T-Mobile: `number@tmomail.net`
  - Verizon: `number@vtext.com`

### 2. Local install

```bash
git clone https://github.com/Akshaj7/StockCatalystMonitor.git
cd StockCatalystMonitor
pip install -r requirements.txt
```

### 3. Configure secrets

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

```
GROQ_API_KEY=your_groq_api_key
GMAIL_ADDRESS=your.email@gmail.com
GMAIL_APP_PASSWORD=your_16_char_app_password
RECIPIENT_EMAIL=your.email@gmail.com
SMS_EMAIL=yournumber@txt.att.net
```

> **Never commit `.env`.** It's already in `.gitignore`. Keys belong in environment variables only — never hard-coded in the source.

### 4. Set your positions

Edit `config/positions.json` with your real holdings (ticker, entry price, shares, target, stop-loss, and the events that should trigger alerts), and `config/settings.json` with your email addresses and scan filters.

### 5. Run locally to test

```bash
python src/morning_scan.py
```

You should receive a formatted report email confirming everything is wired up.

---

## Deploying with GitHub Actions

1. Push the repo to GitHub (a private repo is recommended).
2. Go to **Settings → Secrets and variables → Actions** and add each key from your `.env` as a repository secret (`GROQ_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `RECIPIENT_EMAIL`, `SMS_EMAIL`).
3. Enable Actions for the repo. The workflows will then run on their schedules automatically.
4. Trigger any workflow manually from the **Actions** tab (`workflow_dispatch`) to confirm it works without waiting for the schedule.

The system persists state (sent alerts, processed command emails) by committing JSON files back to the repo with a `[skip ci]` tag, so memory carries across runs without triggering extra workflows.

> **Note on scheduling:** Workflow cron times are defined in **GMT/UTC**. Adjust the cron expressions if you want them anchored to a different timezone.

---

## Controlling the system by email

You can manage your positions without touching code — just **email yourself** with `monitor` or `command` in the subject line. One command per line:

```
set target_exit = 90
set stop_loss = 45
add AAPL entry=182.50 shares=5 target=220 stop=160
remove TSLA
status
help
```

| Command | What it does |
|---------|--------------|
| `set <field> = <value>` | Update a field (`target_exit`, `stop_loss`, `entry_price`, `shares`, `position_value`). Prefix a ticker for multi-position: `set AAPL target_exit = 200`. |
| `add <TICKER> entry=.. shares=.. target=.. stop=..` | Add a new position to monitor. |
| `remove <TICKER>` | Stop monitoring a position. |
| `status` / `list` | Email back the full positions table with current prices. |
| `help` | Email back the full command reference. |

The `email_command` workflow checks your inbox every 30 minutes, applies the commands, and replies with a confirmation.

---

## Scoring

Each filing is scored 0–100 based on factors such as a signed merger agreement (+30), an all-cash deal (+20), a termination fee (+15), and confirmed insider buying (+15), with deductions for heavy regulatory risk, stock-swap deals, or insider selling.

| Score | Label | Meaning |
|-------|-------|---------|
| 60–100 | 🔴 High Interest | Strong signal — worth full attention |
| 40–59 | 🟡 Watch | Developing — monitor, no action yet |
| 20–39 | 🟢 Notable | Something happening, not enough evidence |
| 0–19 | ⚪ Skip | Filtered out |

---

## Automation schedule

| Workflow | When | What it does |
|----------|------|--------------|
| Morning scan | Weekday mornings | Deep scan of overnight filings, delivered before market open |
| Position monitor | Every 30 min, market hours | Quick check of held positions; emails only if something is found |
| Evening scan | Weekday afternoons | After-hours filings and insider buying recap |
| Sunday sweep | Sunday | Catches weekend filings before Monday open |
| Email command | Every 30 min | Processes your email commands |

Position checks are **silent by default** — you only get an email when there's something to report. The morning report always sends so you know the system is alive.

---

## Disclaimer

This software performs **automated analysis only** and does not constitute financial advice. It never buys or sells anything. Always do your own research before making any trading decision. Use at your own risk.

---

## License

No license specified. All rights reserved by the repository owner unless a license is added.
