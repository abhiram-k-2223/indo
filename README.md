# Indo — Indian Commodity Market Agent

A multi-factor trading agent for Indian commodity markets (MCX). Combines
technical analysis, LLM-powered news sentiment, and multi-timeframe confirmation
into a single daily signal.

## Strategy

A scoring system that blends:

| Factor | Weight | What It Looks At |
|--------|--------|------------------|
| Technical | 65% | SMA/EMA crossovers, RSI, MACD, Bollinger Bands, ATR, Volume/OI, ADX regime filter, multi-timeframe (MTF) confirmation |
| Sentiment | 35% | News headlines scored via phrase matching + LLM (LFM 2.5) with confidence weighting |

**Regime filter**: ADX < 25 = ranging market, all directional signals suppressed.

**Signal smoothing**: Composite score uses a rolling 3-bar median to reduce noise
from single-bar outliers. Consensus and stability metrics reported alongside.

**Position sizing**: ATR-based stops (2×) and targets (3×), fixed 15% capital
allocation per trade.

## Data Sources

- **Angel One SmartAPI** — real MCX futures data (Gold, Silver, Crude, NatGas, Copper)
- **yfinance** — fallback US futures for backtesting (max history)
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
| ≥ +25 | STRONG_BUY |
| +8 to +24 | BUY |
| -7 to +7 | NEUTRAL |
| -24 to -8 | SELL |
| ≤ -25 | STRONG_SELL |

Thresholds are configurable via `SIGNAL_THRESHOLDS` in `config.py` and validated
at startup for proper ordering.

## Backtest Results (yfinance, US Futures, with costs)

| Commodity | Trades | Win Rate | Profit Factor | Return | Sharpe |
|-----------|--------|----------|---------------|--------|--------|
| Natural Gas | 109 | 46.8% | 1.10 | +12.2% | 0.10 |
| Crude Oil | 120 | 49.2% | 1.14 | +13.4% | 0.11 |
| Gold | 157 | 56.7% | 1.46 | +20.5% | **0.34** |
| Silver | 127 | 53.5% | 1.41 | +23.8% | 0.27 |
| Copper | 124 | 49.2% | 1.20 | +10.8% | 0.16 |

Risk params: SL 2.5× ATR, TP 4× ATR, trailing 3×/2.5×. Includes 0.05% slippage and 0.02% commission.

Strategy designed for MCX intraday/medium-term — US futures backtest is
indicative only.

## Stack

- **Python** — pure, no framework
- **Angel One SmartAPI** — MCX data via REST
- **llama.cpp** — local LLM inference (no API costs)
- **pandas / numpy** — indicator computation
- **Telegram Bot API** — push alerts

## Why "Indo"

Short for *Indian Commodities* — built specifically for MCX, where price
drivers differ from global benchmarks (import parity, government policies,
domestic demand cycles).
