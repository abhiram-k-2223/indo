#!/usr/bin/env python3
"""
Backtester — walk-forward simulation over historical daily data.
Runs the same indicator engine as the live agent, no lookahead.

Usage:
  uv run python backtester.py                           # all commodities
  uv run python backtester.py --commodity gold           # single
  uv run python backtester.py --commodity gold --plot    # with equity curve
"""

import sys
import argparse
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime

import pandas as pd
import numpy as np

from config import COMMODITIES, TECHNICAL_CONFIG, DATA_SOURCE, WEIGHTS
from data import compute_all_indicators
from data.mcx_fetcher import (
    fetch_mcx_price_data as _mcx_fetch,
    login as _mcx_login,
    refresh_all_tokens as _mcx_refresh,
)
from analysis.technical import analyze_technicals, signal_from_score
from analysis.sentiment import analyze_sentiment


# ─── Config ────────────────────────────────────────

BACKTEST_CFG = {
    "sl_atr_mult": 2.0,
    "tp_atr_mult": 3.0,
    "position_pct": 0.10,
    "capital": 100_000,
    "min_signals": ["STRONG_BUY", "STRONG_SELL"],
    "min_trade_days": 5,      # skip last N days to avoid end-of-data artifacts
}


def _fetch_bt_data(key: str):
    """Fetch with max history for backtesting. Falls back to yfinance."""
    if DATA_SOURCE == "angel_one":
        _mcx_login()
        _mcx_refresh()
        df = _mcx_fetch(key)
        if df is not None and not df.empty:
            return df
        print("  (MCX failed, trying yfinance)", file=sys.stderr)
    cfg = COMMODITIES.get(key)
    if not cfg:
        return None
    import yfinance as yf
    ticker = yf.Ticker(cfg.yfinance_ticker)
    df = ticker.history(period="max", interval="1d")
    if df.empty or len(df) < 30:
        return None
    df.columns = [c.lower() for c in df.columns]
    return df


# ─── Trade record ──────────────────────────────────

@dataclass
class Trade:
    commodity: str
    entry_date: pd.Timestamp
    entry_price: float
    direction: int                # 1 long, -1 short
    atr: float
    entry_score: int
    units: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0
    pnl_pct: float = 0.0

    def __post_init__(self):
        if self.direction == 1:
            self.stop_loss = self.entry_price - self.atr * BACKTEST_CFG["sl_atr_mult"]
            self.take_profit = self.entry_price + self.atr * BACKTEST_CFG["tp_atr_mult"]
        else:
            self.stop_loss = self.entry_price + self.atr * BACKTEST_CFG["sl_atr_mult"]
            self.take_profit = self.entry_price - self.atr * BACKTEST_CFG["tp_atr_mult"]

    def close(self, date: pd.Timestamp, price: float, reason: str):
        self.exit_date = date
        self.exit_price = price
        self.exit_reason = reason
        raw = (price - self.entry_price) * self.direction * self.units
        self.pnl = round(raw, 2)
        self.pnl_pct = round(raw / (self.units * self.entry_price) * 100, 2)


# ─── Walk-forward engine ───────────────────────────

def run_backtest(commodity_key: str, df: pd.DataFrame, sentiment_score: int = 0) -> Dict:
    cfg = TECHNICAL_CONFIG
    bc = BACKTEST_CFG
    warmup = max(cfg["sma_long"], cfg["ema_long"], cfg["adx_period"] * 2) + 10
    n = len(df)
    if n < warmup:
        return {"error": f"Need ≥{warmup} rows, got {n}"}

    df = compute_all_indicators(df)
    trades: List[Trade] = []
    active: Optional[Trade] = None
    equity = [float(bc["capital"])]
    capital = float(bc["capital"])

    for i in range(warmup, n):
        window = df.iloc[:i + 1]
        cur = df.iloc[i]
        date = df.index[i]

        if active is not None:
            price = cur["close"]
            if active.direction == 1:
                if price <= active.stop_loss:
                    active.close(date, price, "stop_loss"); trades.append(active); active = None
                elif price >= active.take_profit:
                    active.close(date, price, "take_profit"); trades.append(active); active = None
            else:
                if price >= active.stop_loss:
                    active.close(date, price, "stop_loss"); trades.append(active); active = None
                elif price <= active.take_profit:
                    active.close(date, price, "take_profit"); trades.append(active); active = None

        tech = analyze_technicals(window)
        combined_score = tech["score"] * WEIGHTS["technical"] + sentiment_score * WEIGHTS["sentiment"]
        combined_signal, direction = signal_from_score(combined_score)

        if active is not None and direction != 0 and direction != active.direction:
            active.close(date, cur["close"], "reversal")
            trades.append(active)
            active = None

        skip_end = bc["min_trade_days"]
        if active is None and direction != 0 and combined_signal in bc["min_signals"] and i < n - skip_end:
            atr = cur.get("atr", None)
            if atr is not None and pd.notna(atr) and atr > 0:
                position_value = capital * bc["position_pct"]
                units = position_value / cur["close"]
                active = Trade(commodity_key, date, cur["close"], direction, atr,
                               int(combined_score), units=units)

        if active:
            unrealized = (cur["close"] - active.entry_price) * active.direction * active.units
            equity.append(capital + unrealized)
        else:
            equity.append(capital)

    if active is not None:
        active.close(df.index[-1], df.iloc[-1]["close"], "end_of_data")
        trades.append(active)
        active = None

    total_pnl = sum(t.pnl for t in trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total = len(trades)

    ret = pd.Series(equity).pct_change().dropna()
    sharpe = float(np.sqrt(252) * ret.mean() / ret.std()) if len(ret) > 1 and ret.std() > 0 else 0.0

    peak = equity[0]
    max_dd = 0.0
    for eq in equity:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    avg_win = np.mean([t.pnl for t in wins]) if wins else 0.0
    avg_loss = np.mean([t.pnl for t in losses]) if losses else 0.0

    return {
        "commodity": commodity_key,
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 1) if total else 0.0,
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(total_pnl / bc["capital"] * 100, 1),
        "final_capital": round(capital + total_pnl, 2),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(max_dd, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(abs(sum(t.pnl for t in wins) / sum(abs(t.pnl) for t in losses)), 2) if losses and sum(abs(t.pnl) for t in losses) > 0 else float("inf"),
        "trade_list": trades,
        "equity_curve": equity,
    }


# ─── Report ────────────────────────────────────────

def print_results(results: Dict):
    if "error" in results:
        print(f"  ✗ {results['commodity']}: {results['error']}")
        return

    print(f"\n  {results['commodity'].replace('_', ' ').title()}")
    print(f"  {'─' * 42}")
    print(f"    Trades:      {results['trades']:>3d}  ({results['wins']}W / {results['losses']}L)")
    print(f"    Win rate:    {results['win_rate']:>5.1f}%")
    print(f"    Total P&L:   {results['total_pnl']:>+8.2f}")
    print(f"    Return:      {results['return_pct']:>+5.1f}%")
    print(f"    Sharpe:      {results['sharpe']:>5.2f}")
    print(f"    Max DD:      {results['max_dd_pct']:>5.1f}%")
    print(f"    Avg win:     {results['avg_win']:>+8.2f}")
    print(f"    Avg loss:    {results['avg_loss']:>+8.2f}")
    print(f"    Profit fact: {results['profit_factor']:>5.2f}")


def print_trade_journal(trades: List):
    if not trades:
        return
    print(f"\n    Trade Journal:")
    print(f"    {'Date':14s} {'Dir':5s} {'Entry':>8s} {'Exit':>8s} {'P&L':>8s} {'Reason'}")
    print(f"    {'─' * 56}")
    for t in trades:
        d = "LONG" if t.direction == 1 else "SHORT"
        ex = t.exit_date.strftime("%d-%b-%Y") if t.exit_date else "-"
        en = t.entry_date.strftime("%d-%b-%Y") if t.entry_date else "-"
        pnl_s = f"{t.pnl:+.1f}"
        print(f"    {en:14s} {d:5s} {t.entry_price:>8.2f} {float(t.exit_price or 0):>8.2f} {pnl_s:>8s} {t.exit_reason}")


# ─── Main ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Indo — Walk-forward backtester")
    parser.add_argument("--commodity", "-c", type=str, default="",
                        help="Backtest a single commodity (e.g. gold, crude_oil)")
    parser.add_argument("--journal", "-j", action="store_true",
                        help="Print trade journal")
    parser.add_argument("--plot", "-p", action="store_true",
                        help="Plot equity curve (requires matplotlib)")
    args = parser.parse_args()

    commodities = {}
    if args.commodity:
        key = args.commodity.lower().replace(" ", "_")
        if key in COMMODITIES:
            commodities = {key: COMMODITIES[key]}
        else:
            print(f"Unknown commodity: {key}. Choose from: {', '.join(COMMODITIES.keys())}")
            sys.exit(1)
    else:
        commodities = {k: v for k, v in COMMODITIES.items() if v.active}

    print("  Computing sentiment for each commodity...")
    sentiment_scores = {}
    for key in commodities:
        try:
            sent = analyze_sentiment(key)
            sentiment_scores[key] = sent.get("score", 0)
        except Exception:
            sentiment_scores[key] = 0

    all_results = []
    for key, cfg in commodities.items():
        label = f"⏳ Backtesting {cfg.name}..."
        print(label, end=" ", flush=True)
        df = _fetch_bt_data(key)
        if df is None or df.empty:
            print("✗ no data")
            continue
        result = run_backtest(key, df, sentiment_score=sentiment_scores.get(key, 0))
        all_results.append(result)
        if "error" in result:
            print(f"✗ {result['error']}")
        else:
            print(f"✓ {result['trades']} trades, {result['win_rate']}% WR, Sharpe {result['sharpe']}")

    print(f"\n{'=' * 50}")
    print("  BACKTEST RESULTS")
    print(f"{'=' * 50}")

    combined = {"trades": 0, "wins": 0, "losses": 0}
    print(f"\n  {'─' * 42}")
    for key in commodities:
        sent = sentiment_scores.get(key, 0)
        print(f"  Sentiment: {commodities[key].name:16s} {sent:+.0f}")
    for r in all_results:
        print_results(r)
        combined["trades"] += r.get("trades", 0)
        combined["wins"] += r.get("wins", 0)
        combined["losses"] += r.get("losses", 0)
        if args.journal and "trade_list" in r:
            print_trade_journal(r["trade_list"])

    if len(all_results) > 1:
        total = combined["trades"]
        wins = combined["wins"]
        print(f"\n  {'─' * 42}")
        print(f"  COMBINED:     {total:>3d} trades ({wins}W / {combined['losses']}L)")
        print(f"  Win rate:     {round(wins / total * 100, 1) if total else 0}%")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            for r in all_results:
                if "equity_curve" in r and len(r["equity_curve"]) > 1:
                    plt.plot(r["equity_curve"], label=r["commodity"])
            plt.title("Equity Curves")
            plt.xlabel("Day")
            plt.ylabel("Portfolio Value")
            plt.legend()
            plt.grid(True)
            plt.show()
        except ImportError:
            print("\n  ℹ Install matplotlib for plotting: pip install matplotlib")


if __name__ == "__main__":
    main()
