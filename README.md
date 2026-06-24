# Indo — Indian Commodity Market Agent

My first quant strategy — a multi-factor trading agent for Indian commodity
markets (MCX). Combines technical analysis, LLM-powered news sentiment, and
multi-timeframe confirmation into a single daily signal.

## Strategy

A scoring system that blends:

| Factor | Weight | What It Looks At |
|--------|--------|------------------|
| Technical | 55% | SMA/EMA crossovers, RSI, MACD, Bollinger Bands, ATR, Volume/OI, ADX regime filter |
| Sentiment | 25% | News headlines classified by local LLM (LFM 2.5) as bullish/bearish/neutral |
| Multi-timeframe | — | Checks daily bias, then hourly pullback for entry confirmation |

**Regime filter**: ADX < 20 = ranging market, all signals suppressed.

**Position sizing**: ATR-based stops (2×) and targets (3×), fixed 10% capital
allocation per trade.

## Data Sources

- **Angel One SmartAPI** — real MCX futures data (Gold, Silver, Crude, NatGas, Copper)
- **yfinance** — fallback US futures for backtesting (25-year history)
- **Google News RSS** — commodity headlines
- **Local LLM (llama.cpp)** — sentiment classification via LFM 2.5 GGUF

## Quick Start

```bash
# Install
uv sync

# Configure
cp .env.example .env   # fill in Angel One creds, Telegram token, etc.

# Run once
./run.sh once

# Monitor for alerts
./run.sh monitor

# Backtest
./run.sh backtest
```

## Signals

| Score | Signal |
|-------|--------|
| ≥ +20 | STRONG_BUY |
| +6 to +19 | BUY |
| -5 to +5 | NEUTRAL |
| -19 to -6 | SELL |
| ≤ -20 | STRONG_SELL |

## Backtest Results (1999–2024, US Futures)

| Commodity | Trades | Win Rate | Profit Factor | Return |
|-----------|--------|----------|---------------|--------|
| Natural Gas | 132 | 44.7% | 1.34 | +24.4% |
| Crude Oil | 88 | 43.2% | 1.26 | +9.3% |
| Gold | 165 | 47.9% | 1.09 | +2.2% |
| Silver | 148 | 41.2% | 1.00 | −0.1% |
| Copper | 118 | 41.5% | 0.94 | −1.8% |

Strategy designed for MCX intraday/medium-term — US futures backtest is
indicative only.

## Stack

- **Python** — pure, no framework
- **Angel One SmartAPI** — MCX data via REST
- **llama.cpp** — local LLM inference (no API costs)
- **pandas / numpy** — indicator computation
- **Telegram Bot API** — push alerts

## Why "Indo"

Short for *Indian Commodities* — built specifically for MCX, where fundamental
drivers differ from global benchmarks (import parity, government policies,
domestic demand cycles).
