#!/usr/bin/env python3
"""
Backtester — walk-forward simulation over historical daily data.
Uses analysis/technical scoring with optimized risk params from stash.
"""

import sys
import argparse
from dataclasses import dataclass
from typing import Dict, List, Optional
from datetime import datetime

import pandas as pd
import numpy as np

from config import COMMODITIES, TECHNICAL_CONFIG, WEIGHTS, RISK_PARAMS
from data import compute_indicators_safe
from analysis import analyze_technicals, signal_from_score, validate_thresholds


BACKTEST_CFG = {
    "sl_atr_mult": RISK_PARAMS["sl_atr_mult"],
    "tp_atr_mult": RISK_PARAMS["tp_atr_mult"],
    "position_pct": 0.15,
    "capital": 100_000,
    "min_signals": ["STRONG_BUY", "STRONG_SELL"],
    "min_trade_days": RISK_PARAMS["min_trade_days"],
    "trailing_stop": True,
    "trail_activation_atr": RISK_PARAMS["trail_activation_atr"],
    "trail_distance_atr": RISK_PARAMS["trail_distance_atr"],
    "slippage_pct": 0.05,
    "commission_pct": 0.02,
}


def _fetch_bt_data(key: str):
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


@dataclass
class Trade:
    commodity: str
    entry_date: pd.Timestamp
    entry_price: float
    direction: int
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
    best_price: float = 0.0
    trailed: bool = False
    entry_cost: float = 0.0
    exit_cost: float = 0.0

    def __post_init__(self):
        self.best_price = self.entry_price
        if self.direction == 1:
            self.stop_loss = self.entry_price - self.atr * BACKTEST_CFG["sl_atr_mult"]
            self.take_profit = self.entry_price + self.atr * BACKTEST_CFG["tp_atr_mult"]
        else:
            self.stop_loss = self.entry_price + self.atr * BACKTEST_CFG["sl_atr_mult"]
            self.take_profit = self.entry_price - self.atr * BACKTEST_CFG["tp_atr_mult"]
        notional = self.units * self.entry_price
        self.entry_cost = notional * (BACKTEST_CFG["slippage_pct"] + BACKTEST_CFG["commission_pct"]) / 100

    def close(self, date: pd.Timestamp, price: float, reason: str):
        self.exit_date = date
        self.exit_price = price
        self.exit_reason = reason
        notional = self.units * price
        self.exit_cost = notional * (BACKTEST_CFG["slippage_pct"] + BACKTEST_CFG["commission_pct"]) / 100
        raw = (price - self.entry_price) * self.direction * self.units
        raw -= (self.entry_cost + self.exit_cost)
        self.pnl = round(raw, 2)
        cost_basis = self.units * self.entry_price
        self.pnl_pct = round(raw / cost_basis * 100, 2) if cost_basis > 0 else 0.0


def run_backtest(commodity_key: str, df: pd.DataFrame) -> Dict:
    cfg = TECHNICAL_CONFIG
    bc = BACKTEST_CFG
    warmup = max(cfg["sma_long"], cfg["ema_long"], cfg["adx_period"] * 2) + 10
    n = len(df)
    if n < warmup:
        return {"error": f"Need ≥{warmup} rows, got {n}"}

    df = compute_indicators_safe(df)
    trades: List[Trade] = []
    active: Optional[Trade] = None
    equity_curve = [float(bc["capital"])]
    capital = float(bc["capital"])

    for i in range(warmup, n):
        window = df.iloc[:i + 1]
        cur = df.iloc[i]
        date = df.index[i]

        if active is not None:
            price = cur["close"]
            atr = cur.get("atr", active.atr)
            atr = atr if pd.notna(atr) and atr > 0 else active.atr

            if active.direction == 1:
                if price > active.best_price:
                    active.best_price = price
                if bc.get("trailing_stop") and not active.trailed:
                    profit_atr = (price - active.entry_price) / atr
                    if profit_atr >= bc["trail_activation_atr"]:
                        active.trailed = True
                        active.take_profit = 0.0
                if active.trailed:
                    new_sl = active.best_price - atr * bc["trail_distance_atr"]
                    if new_sl > active.stop_loss:
                        active.stop_loss = new_sl
                if price <= active.stop_loss:
                    r = "trailing_stop" if active.trailed else "stop_loss"
                    active.close(date, price, r)
                    trades.append(active)
                    capital += active.pnl
                    active = None
                elif active.take_profit > 0 and price >= active.take_profit:
                    active.close(date, price, "take_profit")
                    trades.append(active)
                    capital += active.pnl
                    active = None
            else:
                if price < active.best_price:
                    active.best_price = price
                if bc.get("trailing_stop") and not active.trailed:
                    profit_atr = (active.entry_price - price) / atr
                    if profit_atr >= bc["trail_activation_atr"]:
                        active.trailed = True
                        active.take_profit = 0.0
                if active.trailed:
                    new_sl = active.best_price + atr * bc["trail_distance_atr"]
                    if new_sl < active.stop_loss:
                        active.stop_loss = new_sl
                if price >= active.stop_loss:
                    r = "trailing_stop" if active.trailed else "stop_loss"
                    active.close(date, price, r)
                    trades.append(active)
                    capital += active.pnl
                    active = None
                elif active.take_profit > 0 and price <= active.take_profit:
                    active.close(date, price, "take_profit")
                    trades.append(active)
                    capital += active.pnl
                    active = None

        tech = analyze_technicals(window, commodity_key)
        combined_signal, direction = signal_from_score(tech["score"])

        if active is not None and direction != 0 and direction != active.direction:
            active.close(date, cur["close"], "reversal")
            trades.append(active)
            capital += active.pnl
            active = None

        skip_end = bc["min_trade_days"]
        if active is None and direction != 0 and combined_signal in bc["min_signals"] and i < n - skip_end:
            atr = cur.get("atr", None)
            if atr is not None and pd.notna(atr) and atr > 0:
                pos_value = capital * bc["position_pct"]
                units = pos_value / cur["close"]
                active = Trade(commodity_key, date, cur["close"], direction, atr,
                               int(tech["score"]), units=units)

        current_equity = capital
        if active:
            unrealized = (cur["close"] - active.entry_price) * active.direction * active.units
            current_equity += unrealized
        equity_curve.append(current_equity)

    if active is not None:
        active.close(df.index[-1], df.iloc[-1]["close"], "end_of_data")
        trades.append(active)
        capital += active.pnl
        active = None

    total_pnl = sum(t.pnl for t in trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total = len(trades)

    ret = pd.Series(equity_curve).pct_change().dropna()
    sharpe = float(np.sqrt(252) * ret.mean() / ret.std()) if len(ret) > 1 and ret.std() > 0 else 0.0

    peak = equity_curve[0]
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100
        if dd > max_dd:
            max_dd = dd

    avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0.0
    avg_loss = float(np.mean([t.pnl for t in losses])) if losses else 0.0

    total_costs = sum(t.entry_cost + t.exit_cost for t in trades)

    return {
        "commodity": commodity_key,
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / total * 100, 1) if total else 0.0,
        "total_pnl": round(total_pnl, 2),
        "return_pct": round(total_pnl / bc["capital"] * 100, 1),
        "final_capital": round(capital, 2),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(max_dd, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(abs(sum(t.pnl for t in wins) / sum(abs(t.pnl) for t in losses)), 2) if losses and sum(abs(t.pnl) for t in losses) > 0 else float("inf"),
        "total_costs": round(total_costs, 2),
        "costs_pct": round(total_costs / abs(total_pnl) * 100, 1) if total_pnl != 0 else 0.0,
        "avg_bars_held": round(np.mean([(t.exit_date - t.entry_date).days for t in trades if t.exit_date]), 1) if trades else 0.0,
        "trade_list": trades,
        "equity_curve": equity_curve,
    }


def print_results(r: Dict):
    if "error" in r:
        print(f"  ✗ {r['commodity']}: {r['error']}")
        return
    name = r['commodity'].replace('_', ' ').title()
    print(f"\n  {name}")
    print(f"  {'─' * 48}")
    print(f"    Trades:      {r['trades']:>3d}  ({r['wins']}W / {r['losses']}L)")
    print(f"    Win rate:    {r['win_rate']:>5.1f}%")
    print(f"    Total P&L:   {r['total_pnl']:>+8.2f}  (costs: {r['total_costs']:.2f})")
    print(f"    Return:      {r['return_pct']:>+5.1f}%")
    print(f"    Sharpe:      {r['sharpe']:>5.2f}")
    print(f"    Max DD:      {r['max_dd_pct']:>5.1f}%")
    print(f"    Avg win:     {r['avg_win']:>+8.2f}")
    print(f"    Avg loss:    {r['avg_loss']:>+8.2f}")
    print(f"    Profit fact: {r['profit_factor']:>5.2f}")
    print(f"    Avg hold:    {r['avg_bars_held']:>5.1f} days")


def print_trade_journal(trades: List):
    if not trades:
        return
    print(f"\n    Trade Journal:")
    print(f"    {'Date':14s} {'Dir':5s} {'Entry':>8s} {'Exit':>8s} {'P&L':>9s} {'Score':>6s} {'Reason'}")
    print(f"    {'─' * 62}")
    for t in trades:
        d = "LONG" if t.direction == 1 else "SHORT"
        en = t.entry_date.strftime("%d-%b-%Y") if t.entry_date else "-"
        ex = t.exit_date.strftime("%d-%b-%Y") if t.exit_date else "-"
        pnl_s = f"{t.pnl:+.1f}"
        print(f"    {en:14s} {d:5s} {t.entry_price:>8.2f} {float(t.exit_price or 0):>8.2f} {pnl_s:>9s} {t.entry_score:>+5d} {t.exit_reason}")


def main():
    validate_thresholds()
    parser = argparse.ArgumentParser(description="Indo — Walk-forward backtester")
    parser.add_argument("--commodity", "-c", type=str, default="")
    parser.add_argument("--journal", "-j", action="store_true", help="Print trade journal")
    parser.add_argument("--plot", "-p", action="store_true", help="Plot equity curve")
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

    print(f"  Risk params: SL {BACKTEST_CFG['sl_atr_mult']}x ATR, TP {BACKTEST_CFG['tp_atr_mult']}x ATR")
    print(f"  Trailing: activate at {BACKTEST_CFG['trail_activation_atr']}x, distance {BACKTEST_CFG['trail_distance_atr']}x")
    print(f"  Slippage: {BACKTEST_CFG['slippage_pct']}% + Commission: {BACKTEST_CFG['commission_pct']}%")
    print()

    all_results = []
    for key, cfg in commodities.items():
        label = f"⏳ {cfg.name}..."
        print(label, end=" ", flush=True)
        df = _fetch_bt_data(key)
        if df is None or df.empty:
            print("✗ no data")
            continue
        result = run_backtest(key, df)
        all_results.append(result)
        if "error" in result:
            print(f"✗ {result['error']}")
        else:
            print(f"✓ {result['trades']} trades, {result['win_rate']}% WR, Sharpe {result['sharpe']}")
        if args.journal and "trade_list" in result:
            print_trade_journal(result["trade_list"])

    print(f"\n{'=' * 50}")
    print("  BACKTEST RESULTS")
    print(f"{'=' * 50}")

    combined = {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
    for r in all_results:
        if "error" not in r:
            print_results(r)
            combined["trades"] += r.get("trades", 0)
            combined["wins"] += r.get("wins", 0)
            combined["losses"] += r.get("losses", 0)
            combined["total_pnl"] += r.get("total_pnl", 0)

    if len(all_results) > 1:
        print(f"\n  {'─' * 48}")
        print(f"  PORTFOLIO TOTAL")
        print(f"  {'─' * 48}")
        print(f"    Trades:      {combined['trades']:>3d}")
        print(f"    Win rate:    {round(combined['wins'] / combined['trades'] * 100, 1) if combined['trades'] else 0}%")
        print(f"    Total P&L:   {combined['total_pnl']:>+8.2f}")

    if args.plot:
        try:
            import matplotlib.pyplot as plt
            for r in all_results:
                if "equity_curve" in r and len(r["equity_curve"]) > 1:
                    plt.plot(r["equity_curve"], label=r["commodity"])
            plt.title("Equity Curves")
            plt.xlabel("Day")
            plt.ylabel("Portfolio Value ($)")
            plt.legend()
            plt.grid(True)
            plt.show()
        except ImportError:
            print("\n  ℹ Install matplotlib: pip install matplotlib")


if __name__ == "__main__":
    main()
