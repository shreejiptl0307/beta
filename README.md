# 🇮🇳 Indian Stock Multi-Agent Analysis Dashboard

A local, one-click web dashboard that runs a panel of 8 named AI/heuristic agents to scan the Indian stock universe (NSE), debate each candidate stock, and automatically dispatch high-conviction BUY signals to Telegram.

Runs **100% locally** on your machine with zero cloud backend dependencies.

---

## ⚡ Key Highlights

- **8 Specialized Agents on Duty**:
  - 🔭 **Scout**: Screens large, mid, and small-cap buckets for top movers.
  - 📈 **Technician**: Analyzes RVOL, 52-week position, moving averages, and trend direction.
  - ⚖️ **Fundamentalist**: Evaluates consensus ratings, target prices, and implied upside.
  - 📰 **Newsdesk**: Scrapes recent headlines and computes net sentiment tone.
  - 🐂 **Bull**: Builds the long thesis (momentum, catalysts, breakouts).
  - 🐻 **Bear**: Stresses downside risks (resistance, lack of volume, valuation overhangs).
  - 👨‍⚖️ **Judge**: Weighs the panel debate, issues verdict (`BUY`, `WATCH`, `AVOID`), and confidence (1–10).
  - 📨 **Messenger**: Dispatches formatted alerts to your Telegram chat + logs to local SQLite audit DB.

- **Dual-Engine Debate Architecture**:
  - **Claude Code CLI (Zero-API-Key LLM)**: Auto-detects local `claude` CLI on your PATH and leverages your Claude Pro/Max subscription without per-call API billing.
  - **Direct API Support**: Native support for Anthropic (`ANTHROPIC_API_KEY`) and OpenAI (`OPENAI_API_KEY`).
  - **Deterministic Rule Engine (Offline Fallback)**: Built-in quantitative and technical scoring system that works anytime without network or LLM keys.
  - **Grounding Verifier**: Ensures that every statistic or number cited by agents is strictly verified against the underlying market evidence bundle.

- **Telegram Signal Integration**:
  - Auto-broadcasts high-confidence BUY signals (`confidence >= 7/10`) with full breakdown, live price, and judge rationale.
  - Sends a clean daily summary recap at the conclusion of each analysis cycle.
  - Guaranteed security: Bot tokens and keys are never rendered in logs or browser responses.

---

## 🚀 Quickstart & Setup

### 1. Install Dependencies
Ensure you have Python 3.9+ installed:

```bash
cd /Users/Shreeji/.gemini/antigravity/scratch/indian-stock-agents-dashboard
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Copy the template and fill in your details:

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Telegram Bot Configuration (Get token from @BotFather, Chat ID from @userinfobot)
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here

# LLM Mode (auto | claude_code | anthropic | openai | deterministic)
LLM_PROVIDER=auto
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
CLAUDE_MODEL=haiku

# Application Settings
BRAND=Antigravity Alpha
CONFIDENCE_THRESHOLD=7
SHORTLIST_PER_BUCKET=4
PORT=5050
```

> **LLM with No API Key**: If you have Claude Code installed, simply run `claude` once and log in with your Claude plan (`/login`). The dashboard will auto-detect the `claude` CLI on your PATH and run full LLM panel debates at no additional API cost.

### 3. Start the Dashboard
```bash
python app.py
```
Open your browser and navigate to:
👉 **[http://127.0.0.1:5050](http://127.0.0.1:5050)**

---

## 🖥️ Operating Modes

1. **Demo Mode (Offline Evidence)**:
   - Loads pre-built evidence bundles for real Indian stocks (Trent, Reliance, Suzlon, HDFC Bank, Tata Steel, Zomato).
   - Fast, reliable, and runs anytime outside market hours.

2. **Live Mode (NSE Screener)**:
   - Queries real-time NSE price history, volume, analyst estimates, and headlines via `yfinance` for tickers defined in `universe.json`.
   - Screens large-cap, mid-cap, and small-cap buckets for top movers.
   - Recommended during active market hours (**NSE: Mon–Fri 09:15–15:30 IST**).

---

## 📊 Telegram BUY Signal Example

When an evaluated stock triggers a BUY verdict with confidence >= 7:

```
🟢 BUY SIGNAL — TRENT.NS (Mid/Large cap)

Verdict: BUY | Confidence: 9/10
Winner: Bull

Why: Strong bull leadership (Net +45.0). Supported by exceptional volume surge (3.42x RVOL).

Key catalyst: Near 52-week high breakout zone (97.61%)

Live price: ₹7,320.50 | Day change: +3.39%

— Analysis only. No trade was placed. Not investment advice.
```

---

## 📁 Project Architecture

```
indian-stock-agents-dashboard/
├── app.py                  # Flask server, state machine orchestrator, SQLite audit, Telegram sender
├── scoring.py              # Rule-based scoring engine & Grounding Verifier
├── llm.py                  # Multi-provider LLM debate engine (Claude Code CLI / APIs / Fallback)
├── data_sources.py         # Evidence bundle builder, demo loader & yfinance live screener
├── templates/
│   └── dashboard.html      # Self-contained lightweight SaaS UI (pure HTML/CSS/JS)
├── demo_data/              # Rich pre-built evidence bundles for offline demos
│   ├── TRENT.json
│   ├── RELIANCE.json
│   ├── SUZLON.json
│   ├── HDFCBANK.json
│   ├── TATASTEEL.json
│   └── ZOMATO.json
├── universe.json           # Editable NSE stock universe grouped by market cap
├── audit.db                # SQLite audit history for runs and stock verdicts
├── requirements.txt        # Minimal Python dependencies
└── .env                    # Local secrets and runtime settings
```

---

## 🔒 Safety & Compliance Notice

- **Analysis Only**: This system performs research and signals only. **No trading orders are placed**.
- **Not Investment Advice**: All signals and debate rationale are generated for informational purposes.
