**STOCK CATALYST MONITORING SYSTEM**

Complete Project Plan & Claude Code Build Guide

Version 1.0  |  May 2026  |  $0/month to run

| **$0/month** Complete Cost | **Fully Automated** Runs While You Sleep | **Plain English** AI Reports |
| --- | --- | --- |

# **1. WHAT WE ARE BUILDING**

A fully automated stock catalyst monitoring system that runs every day without you touching anything. It scans public SEC government filings, detects merger deals, insider buying, and activist investors, monitors your current positions, and delivers plain English reports to your email.

## **Core Capabilities**

- Scans SEC EDGAR every morning and evening for merger filings, insider buying, activist investors

- Monitors any positions you hold every 30 minutes during market hours

- Sends instant text message alerts for critical events like deal cancellations or SpaceX S-1 filing

- Delivers AI-written plain English summaries of complex legal filings

- Scores and ranks every finding from 0-100 so you know what to focus on

- Costs $0 per month using free Groq API and free GitHub Actions

| **YOUR ROLE** The system finds and monitors. You make every single decision. Nothing is ever bought or sold automatically. You are always in complete control. |
| --- |

## **Investor Profile**

| **Detail** | **Value** |
| --- | --- |
| Portfolio Size | Under $1,000 |
| Trading Style | Catalyst and speculation based |
| Current Position | DXYZ (Destiny Tech100) - SpaceX pre-IPO play |
| Exit Strategy | Sell DXYZ before SpaceX IPO is announced |
| Coding Experience | None required |
| Monthly Budget | $0 (all free tools) |

# **2. COMPLETE TECH STACK**

Every tool used in this system is completely free. No subscriptions, no credit cards required.

| **Tool** | **Purpose** | **Cost** | **Where To Get It** |
| --- | --- | --- | --- |
| Python 3.x | The programming language the scripts run in | $0 | python.org (free) |
| Groq API | AI that reads filings and writes plain English summaries | $0 | console.groq.com |
| GitHub | Stores your code | $0 | github.com (free account) |
| GitHub Actions | Runs your scripts automatically on a schedule | $0 | Included with GitHub |
| SEC EDGAR API | Source of all merger, insider, and activist filings | $0 | Built into the code |
| Gmail SMTP | Delivers your daily reports by email | $0 | Your existing Gmail |
| SMS Gateway | Sends text alerts for urgent events | $0 | Email-to-text (free) |

## **AI Model: Groq + Llama 3.1 70B**

Groq is a company that runs powerful open source AI models on extremely fast custom hardware. The free tier gives you 500,000 tokens per day. This system uses roughly 30,000 tokens per day, which is only 6% of your free limit.

| **GROQ FREE LIMITS** 500,000 tokens per day free │ 30 requests per minute │ No credit card required │ Signup at console.groq.com |
| --- |

# **3. PROJECT FILE STRUCTURE**

This is every file that will be created and what each one does:

| stock-monitor/ |
| --- |
| │ |
| ├── .github/ |
| │   └── workflows/ |
| │       ├── morning_scan.yml       # Runs 6:00am EST weekdays |
| │       ├── evening_scan.yml       # Runs 4:30pm EST weekdays |
| │       ├── position_monitor.yml   # Runs every 30min market hours |
| │       ├── instant_alert.yml      # Runs every 30min during market hours |
| │       └── sunday_sweep.yml       # Runs Sunday 4:00pm EST |
| │ |
| ├── src/ |
| │   ├── edgar_scanner.py           # Scans SEC EDGAR for new filings |
| │   ├── insider_scanner.py         # Scans Form 4 insider buying |
| │   ├── activist_scanner.py        # Scans 13-D activist filings |
| │   ├── position_monitor.py        # Monitors your held positions |
| │   ├── groq_analyzer.py           # AI analysis using Groq |
| │   ├── alert_system.py            # Handles all alerts and emails |
| │   ├── report_builder.py          # Builds formatted HTML reports |
| │   ├── morning_scan.py            # Orchestrates morning report |
| │   ├── evening_scan.py            # Orchestrates evening report |
| │   ├── instant_alert.py           # Handles Tier 1 instant alerts |
| │   └── utils.py                   # Shared helper functions |
| │ |
| ├── config/ |
| │   ├── positions.json             # Your current holdings |
| │   ├── watchlist.json             # Stocks you are watching |
| │   └── settings.json              # All configuration settings |
| │ |
| ├── state/ |
| │   └── sent_alerts.json           # Tracks alerts already sent — prevents duplicate SMS |
| │ |
| ├── tests/ |
| │   └── test_all.py                # Tests to verify everything works |
| │ |
| ├── requirements.txt               # Python packages needed |
| ├── README.md                      # Step by step setup instructions |
| └── .env.example                   # Template showing required API keys |

# **4. CONFIGURATION FILES**

These three JSON files control everything about how the system works. You edit them to add positions, change settings, and adjust alert triggers. No coding required to update them.

## **positions.json — Your Current Holdings**

Add any stock you currently hold here. The system will monitor it and send you alerts based on your specific thesis for that trade.

| { |
| --- |
| "positions": [ |
| { |
| "ticker": "DXYZ", |
| "company_name": "Destiny Tech100 Inc", |
| "entry_price": 10.50, |
| "shares": 10, |
| "position_value": 105.00, |
| "thesis_type": "pre_ipo_speculation", |
| "thesis_description": "SpaceX pre-IPO play via closed end fund.", |
| "target_exit": 15.00, |
| "stop_loss": 7.00, |
| "date_entered": "2024-01-15", |
| "instant_alert_triggers": [ |
| "Space Exploration Technologies S-1", |
| "SpaceX registration statement", |
| "SpaceX IPO", |
| "DXYZ merger", |
| "Destiny Tech100 8-K" |
| ], |
| "sell_signals": [ |
| "SpaceX S-1 filed", |
| "SpaceX IPO date announced", |
| "Elon Musk confirms IPO timeline", |
| "DXYZ premium collapses" |
| ], |
| "monitor_frequency_minutes": 30, |
| "notes": "Buy rumor sell news strategy. Exit BEFORE IPO not after." |
| } |
| ] |
| } |

## **settings.json — System Configuration**

| { |
| --- |
| "email": { |
| "sender": "your.gmail@gmail.com", |
| "recipient": "your.gmail@gmail.com", |
| "sms_gateway": "your.phone@txt.att.net" |
| }, |
| "scanning": { |
| "morning_scan_time": "06:00", |
| "evening_scan_time": "16:30", |
| "position_check_interval_minutes": 30, |
| "instant_alert_check_minutes": 30, |
| "market_open": "09:30", |
| "market_close": "16:00" |
| }, |
| "filters": { |
| "merger_keywords": [ |
| "agreement and plan of merger", |
| "merger agreement", |
| "going private", |
| "tender offer", |
| "definitive agreement", |
| "strategic alternatives" |
| ], |
| "insider_minimum_purchase": 50000, |
| "insider_transaction_codes": ["P"] |
| } |
| } |

## **sent_alerts.json — Duplicate Alert Prevention**

Every time an alert SMS is sent, the system records it in this file so it is never sent again for the same event. The file lives in the `state/` folder and is automatically saved back to the repository after each run. You never need to edit this file manually.

| { |
| --- |
| "sent_alerts": [ |
| { |
| "alert_id": "spacex-s1-0001234567-24-000001", |
| "type": "spacex_s1", |
| "filing_accession": "0001234567-24-000001", |
| "sent_at": "2024-01-15T14:05:00", |
| "description": "Space Exploration Technologies S-1 filing detected" |
| } |
| ], |
| "last_updated": "2024-01-15T14:05:00" |
| } |

The `alert_id` is built from the SEC filing's unique accession number. Because every EDGAR filing has a different accession number, the same filing can never trigger a second SMS no matter how many times the workflow runs. When a new trading day begins, only filings from that day are checked — old entries in this file are ignored automatically after 7 days.

# **5. SCORING SYSTEM**

Every filing found by the system gets scored from 0 to 100. This score determines how it appears in your report. Higher score means more opportunity and more evidence supporting the trade.

## **Scoring Factors**

| **Factor** | **Points** | **Why It Matters** |
| --- | --- | --- |
| Signed merger agreement present | +30 | Deal is real, not just rumor |
| All cash deal (not stock swap) | +20 | Cash is certain, stock value can change |
| Termination fee in agreement | +15 | Acquirer pays penalty if they walk away |
| Expected close within 6 months | +10 | Your money is not tied up for too long |
| Insider buying confirmed same period | +15 | Insiders confirm they believe in the deal |
| Unusual options activity detected | +10 | Sophisticated players are positioning |
| Known activist investor involved | +5 | Track record of forcing value creation |
| Heavy regulatory approval required | -20 | Government can block or delay deals |
| Stock deal instead of cash | -15 | Stock price can fall before closing |
| No termination fee in agreement | -10 | Acquirer can walk away too easily |
| Timeline over 12 months | -10 | Long time for things to go wrong |
| Insider selling detected | -15 | Insiders losing confidence is a bad sign |

## **Score Thresholds**

| **Score Range** | **Label** | **What It Means** |
| --- | --- | --- |
| 60 to 100 | 🔴 HIGH INTEREST | Strong signal, worth your full attention and research |
| 40 to 59 | 🟡 WATCH | Developing situation, monitor but no action yet |
| 20 to 39 | 🟢 NOTABLE | Something happening but not enough evidence yet |
| 0 to 19 | ⚪ SKIP | Filtered out, not worth your time |

# **6. AUTOMATION SCHEDULE**

The system runs on a specific schedule designed to catch news before you need to act on it. You never need to check manually — the reports come to you.

| **Schedule** | **Time (EST)** | **Days** | **What It Does** |
| --- | --- | --- | --- |
| Morning Report | 6:00 AM | Mon to Fri | Deep scan of all overnight filings. Delivered before market opens at 9:30am giving you time to research. |
| Position Monitor | Every 30 min | Mon to Fri 9:30am-4:00pm | Quick check of all your held positions during market hours. Email only sent if something found. |
| Instant Alert | Every 30 min | Mon to Fri market hours | Checks for Tier 1 critical events only. Sends immediate SMS text if triggered. |
| Evening Report | 4:30 PM | Mon to Fri | After hours filings, insider buying filed today, recap of positions. |
| Sunday Sweep | 4:00 PM | Sunday only | Catches any filings made over the weekend before Monday market open. |

## **Alert Tiers Explained**

### **Tier 1 — Instant SMS Alert (Within 30 Minutes)**

These events require you to know immediately. A text message is sent to your phone regardless of time of day.

- Merger agreement terminated — the deal you bought into is cancelled

- SpaceX S-1 registration statement filed on EDGAR — your DXYZ exit signal

- Competing bid received for a company you hold

- Stock price drops more than 10% suddenly during market hours

- Activist investor files amended 13-D showing they sold their stake

### **Tier 2 — Next Scheduled Report (Within 1 Hour)**

- New analyst coverage initiated on a position

- Related company in same sector gets acquired

- Management makes public statement about a deal

- Volume spike more than 3x normal on a position

### **Tier 3 — Informational Only (Evening Report)**

- General market news affecting your sector

- Minor executive changes at held companies

- Routine quarterly filings

# **7. GITHUB ACTIONS WORKFLOW FILES**

These YAML files tell GitHub when and how to run your scripts automatically. You put them in the .github/workflows/ folder and GitHub handles the rest for free.

## **morning_scan.yml**

| name: Morning Catalyst Scan |
| --- |
| on: |
| schedule: |
| - cron: '0 11 * * 1-5'   # 6:00am EST = 11:00am UTC weekdays |
| workflow_dispatch:           # Allows you to run it manually anytime |
|  |
| jobs: |
| morning-scan: |
| runs-on: ubuntu-latest |
| steps: |
| - uses: actions/checkout@v3 |
| - name: Set up Python |
| uses: actions/setup-python@v4 |
| with: |
| python-version: '3.11' |
| - name: Install dependencies |
| run: pip install -r requirements.txt |
| - name: Run morning scan |
| env: |
| GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }} |
| GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }} |
| GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }} |
| RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }} |
| SMS_EMAIL: ${{ secrets.SMS_EMAIL }} |
| run: python src/morning_scan.py |

## **position_monitor.yml**

| name: Position Monitor |
| --- |
| on: |
| schedule: |
| - cron: '*/30 14-21 * * 1-5'  # Every 30min 9:30am-4:30pm EST |
|  |
| jobs: |
| monitor: |
| runs-on: ubuntu-latest |
| steps: |
| - uses: actions/checkout@v3 |
| - name: Set up Python |
| uses: actions/setup-python@v4 |
| with: |
| python-version: '3.11' |
| - name: Install dependencies |
| run: pip install -r requirements.txt |
| - name: Monitor positions |
| env: |
| GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }} |
| GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }} |
| GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }} |
| RECIPIENT_EMAIL: ${{ secrets.RECIPIENT_EMAIL }} |
| SMS_EMAIL: ${{ secrets.SMS_EMAIL }} |
| run: python src/position_monitor.py |

## **instant_alert.yml**

| name: Instant Alert Monitor |
| --- |
| on: |
| schedule: |
| - cron: '*/30 14-21 * * 1-5'  # Every 30min during market hours |
| workflow_dispatch:               # Allows you to run it manually anytime |
|  |
| permissions: |
| contents: write                  # Required to save state file back to repo |
|  |
| jobs: |
| instant-alert: |
| runs-on: ubuntu-latest |
| steps: |
| - uses: actions/checkout@v3 |
| - name: Set up Python |
| uses: actions/setup-python@v4 |
| with: |
| python-version: '3.11' |
| - name: Install dependencies |
| run: pip install -r requirements.txt |
| - name: Check instant alerts |
| env: |
| GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }} |
| GMAIL_ADDRESS: ${{ secrets.GMAIL_ADDRESS }} |
| GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }} |
| SMS_EMAIL: ${{ secrets.SMS_EMAIL }} |
| run: python src/instant_alert.py |
| - name: Save alert state |
| run: \| |
|   git config user.name "github-actions[bot]" |
|   git config user.email "github-actions[bot]@users.noreply.github.com" |
|   git add state/sent_alerts.json |
|   git diff --staged --quiet \|\| git commit -m "Update alert state [skip ci]" |
|   git push |

| **HOW STATE SAVING WORKS** After each run the workflow commits the updated sent_alerts.json back to your repository. The [skip ci] tag in the commit message prevents this from triggering another workflow run. If no new alerts were sent, git detects no changes and skips the commit entirely. |
| --- |

# **8. REPORT FORMATS**

This is exactly what each type of report looks like when it arrives in your email or as a text message.

## **Morning Report Email**

| Subject: Catalyst Report — January 15 2024 |
| --- |
|  |
| ═══════════════════════════════════════════════ |
| DAILY CATALYST REPORT |
| Monday January 15 2024  │  Generated 6:00am EST |
| ═══════════════════════════════════════════════ |
|  |
| YOUR POSITIONS |
| ─────────────── |
| $DXYZ — Destiny Tech100 |
| Entry: $10.50  │  Current: $11.20  │  +6.7% |
| Thesis: SpaceX Pre-IPO Speculation |
| Status: No SpaceX S-1 detected |
| Status: No negative SpaceX news |
| Status: Premium to NAV still elevated |
| ACTION: HOLD — Thesis intact |
|  |
| ═══════════════════════════════════════════════ |
| NEW CATALYST DISCOVERIES |
| ═══════════════════════════════════════════════ |
|  |
| HIGH INTEREST  [Score: 75/100] |
| Company: Acme Corp ($ACME) |
| Filing: 8-K — Agreement and Plan of Merger |
| Filed: January 14 2024 at 11:42pm |
|  |
| WHAT HAPPENED: |
| Acme Corp signed a definitive merger agreement |
| to be acquired for $14.20 per share in cash. |
| Deal expected to close Q2 2024. |
|  |
| Offer price:    $14.20 per share (cash) |
| Current price:  $13.45 |
| Upside:         5.6% if deal closes |
| Timeline:       April to June 2024 |
| Termination fee: $45 million |
| Approvals needed: Shareholder vote only |
|  |
| DIRECT FILING LINK: [EDGAR LINK] |
|  |
| ─────────────────────────────────────────────── |
| INSIDER BUYING |
| ─────────────── |
| $WXYZ — CEO purchased $180,000 of own stock |
| at $12.40 per share. First purchase in 14 months. |
|  |
| ─────────────────────────────────────────────── |
| STATS: 47 filings scanned  │  6 analyzed  │  1 high interest |
| This is automated analysis only. Always do your own research. |

## **Instant SMS Alert**

| URGENT POSITION ALERT |
| --- |
|  |
| $DXYZ — SpaceX S-1 filing detected |
| on SEC EDGAR at 2:14pm EST |
|  |
| DXYZ currently: $14.20 (+27%) |
|  |
| THIS IS YOUR SELL SIGNAL |
| Check email for full details |

| **SILENCE IS NORMAL** The 30-minute position monitor only sends an email if something noteworthy is found. If you do not receive an email during market hours it means everything is normal with your positions. |
| --- |

# **9. BUILD PHASES — STEP BY STEP**

Build the system one phase at a time. Test each phase before starting the next. Paste the exact prompt for each phase into Claude Code.

## **Phase 1 — Core EDGAR Scanner**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 1 of my stock monitoring system. Create edgar_scanner.py that connects to SEC EDGAR full text search API, searches for 8-K filings from the last 24 hours containing merger and acquisition keywords from settings.json, returns a list of filings with company name, ticker, filing date, and direct EDGAR link, filters out obvious non-merger 8-Ks, saves results to a JSON file, includes proper rate limiting at 10 requests per second maximum, and uses the required User-Agent header. Print results to console so I can test it. Include error handling for API failures. |
| --- |

## **Phase 2 — Insider Buying Scanner**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 2. Create insider_scanner.py that scans SEC EDGAR Form 4 filings from the last 24 hours, filters for transaction code P meaning open market purchase only, filters for purchases over $50,000 minimum, extracts company ticker, insider name, title, amount purchased, price paid, and total value, flags if the insider is CEO or CFO specifically, flags if multiple insiders bought in the same week, and saves to a JSON file. Ignore automatic plan purchases coded as A and ignore option exercises. |
| --- |

## **Phase 3 — Groq AI Analyzer**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 3. Create groq_analyzer.py that takes raw SEC filing text as input, connects to the Groq API using model llama-3.1-70b-versatile, sends the filing to the AI with a system prompt instructing it to extract the catalyst type, specific dollar amounts, expected timeline, key risk factors, and a plain English summary in 3 sentences maximum, applies the scoring system from settings.json to produce a score from 0 to 100, and returns the score and plain English summary. Handle API errors and include token counting to stay under free limits. |
| --- |

## **Phase 4 — Report Builder and Email Delivery**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 4. Create report_builder.py and alert_system.py that takes all findings from phases 1 through 3, builds a formatted HTML email report, sorts findings by score with high interest first, includes position status at the top of every report, sends via Gmail SMTP using an app password, sends SMS alerts for Tier 1 events via email to SMS gateway, and only sends 30-minute position check emails when something noteworthy is found. The morning report always sends even if nothing is found to confirm the system is working. |
| --- |

## **Phase 5 — Position Monitor**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 5. Create position_monitor.py that reads positions from positions.json, checks for any new SEC filings for each position, checks for any filings mentioning the company by name, compares current price to entry price, checks whether any sell signals from positions.json have been triggered, runs a thesis check appropriate for each thesis type, sends email only when something is found, sends immediate SMS for Tier 1 events, and logs all checks to a daily log file. |
| --- |

## **Phase 6 — GitHub Actions Automation**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 6. Create all GitHub Actions workflow files from the project plan including morning_scan.yml at 6am EST weekdays, evening_scan.yml at 4:30pm EST weekdays, position_monitor.yml every 30 minutes during market hours, instant_alert.yml every 30 minutes during market hours, and sunday_sweep.yml on Sunday at 4pm EST. Also create requirements.txt with all needed Python packages, README.md with step by step setup instructions for someone with zero coding experience explaining how to create a GitHub account, create a private repository, upload all files, add secrets for API keys, and enable GitHub Actions. |
| --- |

## **Phase 7 — DXYZ Specific Monitoring**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 7. Add specialized monitoring for my DXYZ position and add duplicate alert prevention to the entire instant alert system. First, implement state management in instant_alert.py: on startup load state/sent_alerts.json, for every potential alert check whether its SEC filing accession number already exists in the sent_alerts list, only send the SMS if the accession number is new, after sending record the accession number plus alert type plus timestamp into sent_alerts.json, and automatically remove entries older than 7 days to keep the file small. The file must be created with an empty sent_alerts list if it does not exist yet. Second, add SpaceX S-1 detection searching for Space Exploration Technologies S-1, SpaceX registration statement, and SpaceX IPO filing. Third, add DXYZ NAV premium tracking to the morning report estimating NAV from fund filings and comparing to the current price. Track whether the premium is rising or falling. Make SpaceX S-1 detection the highest priority alert in the entire system so it is never filtered out. Add to the morning report the days held, unrealized gain or loss, and current premium to estimated NAV. |
| --- |

## **Phase 8 — Testing**

| **PASTE THIS INTO CLAUDE CODE** Build Phase 8. Create test_all.py that tests EDGAR API connection, tests Groq API connection, tests Gmail sending with a test email, tests SMS gateway with a test text, runs a sample scan using a known past filing to verify the scoring works correctly, checks that all config files load correctly, verifies positions.json is a valid format, and prints pass or fail for each test. Also add a manual trigger option so I can run the morning scan anytime to test it without waiting for the schedule. |
| --- |

# **10. SETUP CHECKLIST**

Complete these steps before you start building. Each one takes only a few minutes and is completely free.

## **Step 1 — Get Your Free Groq API Key**

- Go to console.groq.com

- Sign up with your Google account or email address

- Click API Keys in the left menu

- Click Create API Key and give it any name

- Copy the key and save it somewhere safe — you will not see it again

| **NO CREDIT CARD NEEDED** Groq free tier requires no payment information. You get 500,000 tokens per day permanently free. |
| --- |

## **Step 2 — Create GitHub Account**

- Go to github.com and click Sign Up

- Choose a free account

- Verify your email address

- You will create your repository after the code is built

## **Step 3 — Create Gmail App Password**

- Go to myaccount.google.com

- Click the Security tab

- Enable 2-factor authentication if not already on

- Search for App passwords in the search bar

- Select Mail as the app type

- Copy the 16-character password generated

| **IMPORTANT** Use the 16-character app password in your configuration, not your regular Gmail password. App passwords are specifically for automated applications. |
| --- |

## **Step 4 — Find Your SMS Email Gateway**

Most US carriers let you receive texts via email for free. Find yours below:

| **Carrier** | **SMS Email Format** | **Example** |
| --- | --- | --- |
| AT&T | number@txt.att.net | 3145551234@txt.att.net |
| T-Mobile | number@tmomail.net | 3145551234@tmomail.net |
| Verizon | number@vtext.com | 3145551234@vtext.com |
| Sprint | number@messaging.sprintpcs.com | 3145551234@messaging.sprintpcs.com |
| Cricket | number@sms.cricketwireless.net | 3145551234@sms.cricketwireless.net |

## **Environment Variables**

Create a file called .env in your project folder. Never share this file or put it on GitHub. These are your secret keys.

| GROQ_API_KEY=your_groq_api_key_here |
| --- |
| GMAIL_ADDRESS=your.email@gmail.com |
| GMAIL_APP_PASSWORD=your_16_char_app_password_here |
| RECIPIENT_EMAIL=your.email@gmail.com |
| SMS_EMAIL=yournumber@txt.att.net |

When you deploy to GitHub Actions these same values go into Repository Settings then Secrets then Actions. GitHub encrypts them and they are never visible to anyone.

# **11. DXYZ POSITION — SPECIAL MONITORING**

DXYZ requires different monitoring than a standard merger arbitrage play because the catalyst (SpaceX IPO) is a private company event that does not appear in normal SEC filings until the moment SpaceX files to go public.

## **Understanding Your Trade**

| **Factor** | **Detail** |
| --- | --- |
| What you own | Shares of Destiny Tech100, a closed end fund |
| What the fund holds | Stakes in private companies including SpaceX |
| Why you bought it | Speculation that SpaceX IPO rumors will drive price up |
| Your exit strategy | Sell before SpaceX IPO is officially announced |
| The key risk | DXYZ trades at massive premium to real asset value |
| What collapses the trade | SpaceX actually going public removes the scarcity premium |

## **Your Critical Exit Signals**

| **SELL IMMEDIATELY — Tier 1 Instant Alert** SpaceX S-1 registration statement filed on SEC EDGAR. This means the IPO process has officially started. DXYZ premium will collapse as SpaceX becomes directly accessible to investors. |
| --- |

- SpaceX announces a direct listing date

- Elon Musk publicly confirms a specific IPO timeline

- DXYZ premium to NAV drops below your personal threshold

- Large institutional seller appears in DXYZ via 13-D filing

## **What The System Monitors For DXYZ**

| **What It Monitors** | **How Often** | **Alert Type** |
| --- | --- | --- |
| SpaceX S-1 on SEC EDGAR | Every 30 minutes | Instant SMS — highest priority |
| DXYZ 8-K filings from Destiny Tech100 | Every 30 minutes | Instant SMS |
| DXYZ NAV vs current price premium | Every morning | Morning report |
| Premium trend rising or falling | Every morning | Morning report |
| Institutional buying or selling of DXYZ | Twice daily | Scheduled report |
| Any SEC filing mentioning SpaceX | Every 30 minutes | Instant SMS if S-1 related |

| **BUY THE RUMOR SELL THE NEWS** Your strategy is correct. The pattern in markets is that prices rise on anticipation and fall on the actual announcement. When SpaceX officially files to IPO, people can buy SpaceX directly and no longer need DXYZ as a workaround. The premium disappears fast. |
| --- |

# **12. TOTAL COST SUMMARY**

| **Item** | **Monthly Cost** | **Notes** |
| --- | --- | --- |
| Groq API | $0.00 | 500,000 tokens/day free. You use 30,000 (6% of limit) |
| GitHub Actions | $0.00 | Free tier is more than enough for this system |
| SEC EDGAR API | $0.00 | Always free, publicly funded government resource |
| Gmail SMTP | $0.00 | Free with your existing Gmail account |
| SMS via email gateway | $0.00 | Built into your carrier plan at no cost |
| CourtListener | $0.00 | Free federal court search |
| OpenInsider | $0.00 | Free insider buying tracker |

| **TOTAL NEW COST** | **$0.00/month** | You only pay your existing Claude Pro subscription |
| --- | --- | --- |

| **PERSPECTIVE** A Bloomberg Terminal with similar capabilities costs $2,000 per month. You are building a system that does the most important parts for free by using public government APIs and open source AI. |
| --- |

# **13. IMPORTANT RULES FOR THE SYSTEM**

These rules must be followed when building the system. They protect your money and your security.

| **RULE 1 — NEVER AUTO TRADE** The system must never buy or sell stocks automatically under any circumstances. It provides information only. Every trade decision is made by you personally. |
| --- |

| **RULE 2 — NEVER STORE KEYS IN CODE** API keys, passwords, and email addresses must always be in environment variables. Never write them directly into Python files. Use the .env file locally and GitHub Secrets in production. |
| --- |

| **RULE 3 — DXYZ ALERT IS HIGHEST PRIORITY** The SpaceX S-1 detection must never be filtered, scored down, or delayed. This single alert is the most important event the entire system monitors for. It always triggers an immediate SMS. |
| --- |

| **RULE 4 — NEVER SEND THE SAME ALERT TWICE** Every SMS sent must be recorded in state/sent_alerts.json using the SEC filing accession number as the unique ID. Before sending any alert, check this file first. If the accession number is already recorded, skip it silently. The workflow saves the updated state file back to the repository after every run so the memory persists across all future runs. |
| --- |

- Always add rate limiting for EDGAR API — maximum 10 requests per second

- Always include error handling — scripts should never crash silently

- Always add the disclaimer in every report: This is automated analysis only. Always do your own research.

- Keep all reports mobile friendly since you read on your phone

- Silence is the default for position checks — only email when something is found

- The morning report always sends even if nothing is found — it confirms the system is running

# **14. HOW TO START BUILDING**

Follow these steps exactly to get the system built and running.

## **Before Your First Claude Code Session**

- Get your free Groq API key from console.groq.com

- Create a free GitHub account at github.com

- Create a Gmail app password following Step 3 in Section 10

- Find your SMS email gateway from Section 10 using your carrier

- Have your DXYZ entry price ready

## **Starting Your Claude Code Session**

| **PASTE THIS AS YOUR FIRST MESSAGE IN CLAUDE CODE** I want to build an automated stock catalyst monitoring system. I have zero coding experience. I have the complete project plan ready. Start with Phase 1 only. Explain every step like I have never coded before. Show me exactly where to put each file. Test that Phase 1 works before we move to Phase 2. |
| --- |

## **Working Through The Phases**

- Start Phase 1 and run the test before anything else

- When Phase 1 passes tell Claude Code to start Phase 2

- Continue one phase at a time until all 8 phases are complete

- Run the full test suite from Phase 8 at the end

- Ask Claude Code to create complete GitHub deployment instructions

## **After Deployment**

- Update positions.json with your real DXYZ entry price and share count

- Update settings.json with your real email address and SMS gateway

- Add all secrets to GitHub Actions following the README instructions

- Run a manual test using the workflow_dispatch trigger

- Wait for your first real morning report the following weekday at 6am

| **FINAL NOTE** Once deployed the system runs every day without you touching anything. The only maintenance required is updating positions.json when you open or close trades. Everything else is automatic. |
| --- |