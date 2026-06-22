# Indo — Indian Commodity Market Agent: Context File

## Project Goal

Build an AI agent that analyzes Indian commodity markets (Natural Gas, Crude Oil, Gold, Silver, Copper) on **MCX** and alerts via Telegram on high-confidence long/short signals. Deploy to a cloud VPS for 24/7 operation.

---

## What We Did & Why

### 1. Basic Agent with yfinance (US futures proxy)

**Problem**: MCX data is hard to get programmatically. We started with yfinance US futures (NG=F, CL=F, GC=F, SI=F, HG=F) as a proxy to build and test the full pipeline before tackling MCX integration.

**Files**: `data/fetcher.py`, `config.py`, `agent.py`

**Result**: Working agent that fetches price data, computes indicators, generates reports, and pushes Telegram alerts. All 6 technical indicators work on this data path.

### 2. Technical Indicators (6 indicators)

SMA crossover, EMA alignment, RSI (overbought/oversold), MACD (line + histogram), Bollinger Bands (position), ATR (volatility). Each contributes to a directional score (-60 to +60) that maps to STRONG_SELL → STRONG_BUY.

**Files**: `data/fetcher.py` (indicator functions), `analysis/technical.py` (signal logic)

**Why**: Needed a systematic, objective scoring system for trade signals. Pure discretionary analysis wouldn't work for a 24/7 automated agent.

### 3. Sentiment Analysis

Google News RSS + keyword scoring. Falls back from LLM to keyword if LLM is unavailable (never blocks analysis).

**Files**: `analysis/sentiment.py`

**Why**: News drives commodity prices. Even simple keyword sentiment adds edge.

### 4. Report Generation + Telegram Alerts

Markdown report with per-commodity breakdown. Two delivery modes:
- `--monitor N`: Silent loop, only pushes on STRONG_BUY/STRONG_SELL above configurable threshold (deduplicates by key|signal|score)
- `--telegram`: Push full report every cycle

**Files**: `reporting/reporter.py`

**Why**: User needs mobile alerts, not dashboard monitoring. Moving to Paraguay = can't babysit a laptop.

### 5. Python 3.14 ElementTree fix

Sentiment RSS parsing required explicit `is not None` checks — Python 3.14 changed ElementTree truth-value semantics (empty elements are no longer falsy).

### 6. Llama.cpp / LLM Support

Supports Ollama, OpenAI, Anthropic, and llama.cpp (via OpenAI-compatible endpoint). LFM 2.5 1.2B Instruct identified as the local model choice (~900MB Q4, 80 tok/s on CPU).

**Files**: `agent.py` (llm_analysis function), `analysis/sentiment.py` (LLM headline classification)

**Why**: NVIDIA NIM free tier (Llama 3.1 8B, 40 req/min) is the recommended LLM option — no GPU needed on VPS, free.

### 7. Angel One SmartAPI Integration (MCX Data)

**This is the most important recent change.** Replaces yfinance US futures with real MCX futures data (INR prices, Open Interest, Indian contract specs).

**Files**: `data/mcx_fetcher.py` (new), `data/__init__.py` (unified routing), `config.py` (DATA_SOURCE toggle)

**How it works**:
- Set `DATA_SOURCE=angel_one` in `.env`
- Angel One SmartAPI is **free** with a free Angel One trading account
- Authenticates with client ID + password + TOTP
- Searches MCX for near-month futures contract tokens automatically
- Fetches daily OHLCV candles (90 days by default)
- Outputs same DataFrame format as yfinance — all indicators work unchanged
- Falls back to yfinance if credentials aren't configured

**MCX symbol mapping**:
| Commodity | yfinance | Angel One MCX |
|-----------|----------|---------------|
| Natural Gas | NG=F | NATURALGAS |
| Crude Oil | CL=F | CRUDEOIL |
| Gold | GC=F | GOLD |
| Silver | SI=F | SILVER |
| Copper | HG=F | COPPER |

---

## What's Left To Do

### P0 — Setup (blocking everything else)

- [ ] **Create Angel One trading account** (free, angelone.in) — needed for MCX data
- [ ] **Register on SmartAPI portal** (https://smartapi.angelone.in) — create a "Trading API" app to get API key
- [ ] **Enable TOTP** in SmartAPI settings — get the TOTP secret
- [ ] **Fill `.env`** with ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_PASSWORD, ANGEL_TOTP_SECRET
- [ ] **Run `uv run python agent.py`** to verify MCX data flows
- [ ] **Create Telegram bot** via @BotFather → get token + chat ID → fill `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`

### P1 — Strategy Improvements

- [x] **ADX regime filter** — Skip signals when ADX < 20 (ranging market). ADX indicator computed in `fetcher.py`, suppresses to NEUTRAL in `technical.py`. Displayed in reports.
- [ ] **Volume/OI confirmation** — MCX data has OI (column 6 in candle data). Add volume trend + OI change as signal confirmations.
- [ ] **Multi-timeframe confirmation** — Check daily bias, then hourly chart for pullback entry. Would need hourly candle data from SmartAPI.
- [ ] **LLM-based headline sentiment** — Swap keyword counting for LFM/llama.cpp classification on news headlines. Code structure is ready (sentiment.py falls back to keywords).

### P2 — Backtesting

- [ ] **Build backtester** — Walk-forward loop over 2+ years of OHLCV + OI data. Compute P&L with slippage.
- [ ] **Data source for backtesting**: Angel One historical data API goes back ~10 years for NSE, MCX is more limited. May need to find/buy historical MCX data separately.

### P3 — Infrastructure

- [ ] **VPS deployment** — Hetzner CX11 (€3.79/mo) or Contabo VPS 10 ($4.50/mo). Ubuntu + uv + systemd service.
- [ ] **NVIDIA NIM setup** (optional) — Free tier API for LLM analysis without GPU. Set `LLM_PROVIDER=openai` with NIM base URL.

### P4 — Production

- [ ] **Paper trade live** for 2 months before wiring broker API
- [ ] **Broker API** for actual execution (Angel One SmartAPI already supports order placement when ready)

---

## Key Decisions & Rationale

| Decision | Why |
|----------|-----|
| **Angel One over Zerodha** | Angel One SmartAPI is fully free (MCX data + historical). Zerodha charges ₹500/mo for data access. |
| **Angel One over scraping MCX** | MCX locked down their backpage.aspx APIs (404). The bhavcopy page requires JS rendering. Angel One is reliable, free, and includes OI data. |
| **Angel One over paid APIs** | DHBoss (~₹0.05/hit), TickerMarket, apidatafeed all cost money. Angel One is free with a free trading account. |
| **llama.cpp over Ollama** | User prefers direct llama.cpp server for GGUF models. Code supports both. |
| **LFM 2.5 1.2B Instruct** | ~900MB Q4, 80 tok/s on CPU. Viable for local inference. But NVIDIA NIM (free) gives Llama 3.1 8B with no local GPU. |
| **--monitor over --schedule** | Monitor only pushes Telegram on high-confidence signals when score changes. Schedule pushes full reports every N hours regardless. |
| **curl_cffi for Akamai** | MCX uses Akamai WAF. The `mcx-data` library uses curl_cffi for Chrome TLS impersonation. We use direct REST API (Angel One), so this isn't needed for our data path. |

---

## Architecture Summary

```
agent.py (entrypoint)
  ├── config.py (settings, credentials, thresholds)
  ├── data/
  │   ├── __init__.py (unified fetch_price_data routing)
  │   ├── fetcher.py (yfinance US futures + technical indicators)
  │   └── mcx_fetcher.py (Angel One SmartAPI MCX data)
  ├── analysis/
  │   ├── technical.py (signal generation from indicators)
  │   ├── sentiment.py (news RSS + keyword/LLM scoring)
  │   └── fundamentals.py (EIA API stub, currently optional/broken)
  └── reporting/
      └── reporter.py (markdown report + Telegram push)
```

Data flow: `DATA_SOURCE` in `.env` (yfinance or angel_one) → `data/__init__.py` routes to correct fetcher → DataFrame with open/high/low/close/volume → `compute_all_indicators()` adds SMA/EMA/RSI/MACD/BB/ATR → `analysis/technical.py` scores → `combine_signals()` merges with sentiment + fundamental → report/alert.

---

## Relevant Files

| File | Purpose |
|------|---------|
| `agent.py` | Entrypoint, orchestration, --monitor loop, LLM narrative call |
| `config.py` | All config (commodities, weights, thresholds, env vars, LLM/alert/Angel settings) |
| `data/fetcher.py` | yfinance price fetch + 6 technical indicators |
| `data/mcx_fetcher.py` | **NEW** Angel One SmartAPI MCX data (login, search, candle fetch) |
| `data/__init__.py` | Unified data routing by DATA_SOURCE |
| `analysis/technical.py` | Signal generation (STRONG_BUY → STRONG_SELL with scores) |
| `analysis/sentiment.py` | Google News RSS + keyword scoring + LLM headline classification |
| `analysis/fundamentals.py` | EIA API stub (nat gas / crude production) |
| `reporting/reporter.py` | Markdown report builder + Telegram HTTP push |
| `.env` | Secrets (Telegram, LLM, Angel One, thresholds) |
| `requirements.txt` | yfinance, pandas, numpy, requests, python-dotenv, pyotp |
| `CONTEXT.md` | This file |

---

## Quick Commands

```bash
# Run once with yfinance (no credentials needed)
uv run python agent.py

# Run with MCX data (after setting .env)
DATA_SOURCE=angel_one uv run python agent.py

# Alert mode every 60 minutes (yfinance)
uv run python agent.py --monitor 60

# Alert mode with MCX data
DATA_SOURCE=angel_one uv run python agent.py --monitor 60

# Full report via Telegram (yfinance)
uv run python agent.py --telegram

# With LLM narrative (requires LLM server)
uv run python agent.py --llm

# Schedule mode every 8 hours
uv run python agent.py --schedule 8

# Verify syntax of all files
uv run python3 -m py_compile agent.py
uv run python3 -m py_compile config.py
uv run python3 -m py_compile data/mcx_fetcher.py
uv run python3 -m py_compile data/__init__.py
uv run python3 -m py_compile reporting/reporter.py
```
