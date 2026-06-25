"""
Paper trading engine — simulates trade execution, P&L tracking, and trailing stops
using signals from the live agent. State persisted in JSON/CSV.
"""

import os
import json
import csv
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field, asdict

from config import COMMODITIES, DATA_SOURCE
from utils.log import setup_logger

logger = setup_logger()

STATE_DIR = "data"
STATE_FILE = os.path.join(STATE_DIR, "paper_state.json")
JOURNAL_FILE = os.path.join(STATE_DIR, "paper_journal.csv")

PAPER_CFG = {
    "capital": 100_000,
    "position_pct": 0.15,
    "trail_activation_atr": 4.0,
    "trail_distance_atr": 3.0,
    "sl_atr_mult": 2.0,
    "tp_atr_mult": 3.0,
}


@dataclass
class Position:
    commodity: str
    direction: int
    entry_date: str
    entry_price: float
    units: float
    atr: float
    stop_loss: float
    take_profit: float
    trail_activated: bool = False
    best_price: float = 0.0

    def __post_init__(self):
        self.best_price = self.entry_price


def _load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"capital": PAPER_CFG["capital"], "positions": {}}
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"capital": PAPER_CFG["capital"], "positions": {}}


def _save_state(state: Dict[str, Any]):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _append_journal(entry: Dict[str, Any]):
    os.makedirs(STATE_DIR, exist_ok=True)
    exists = os.path.exists(JOURNAL_FILE)
    with open(JOURNAL_FILE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "date", "commodity", "action", "direction", "price",
            "units", "pnl", "reason", "capital",
        ])
        if not exists:
            w.writeheader()
        w.writerow(entry)


def _print_positions(state: Dict[str, Any]):
    pos = state.get("positions", {})
    if not pos:
        print("  No open positions.")
        return
    print(f"  Open Positions ({len(pos)}):")
    print(f"  {'Commodity':15s} {'Dir':5s} {'Entry':>10s} {'Price':>10s} {'P&L':>10s} {'Stop':>10s}")
    print(f"  {'─' * 62}")
    for key, p in pos.items():
        pnl = (p["best_price"] - p["entry_price"]) * p["direction"] * p["units"]
        cur_price_str = f"{p['best_price']:.2f}"
        print(f"  {key:15s} {'LONG' if p['direction']==1 else 'SHORT':5s} "
              f"{p['entry_price']:>10.2f} {cur_price_str:>10s} "
              f"{pnl:>+10.2f} {p['stop_loss']:>10.2f}")


def update(results: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    state = _load_state()
    capital = state["capital"]
    positions: Dict[str, dict] = state.get("positions", {})
    today = datetime.now().strftime("%Y-%m-%d")
    is_mcx = DATA_SOURCE == "angel_one"
    currency = "₹" if is_mcx else "$"

    logger.info("Paper trader checking signals...")
    closed_any = False

    for key, res in results.items():
        if "error" in res:
            continue

        cfg = COMMODITIES.get(key)
        if not cfg or not cfg.active:
            continue

        price = res.get("price", 0)
        if not price or price == "N/A":
            continue

        tech = res.get("technical", {})
        combined = res.get("combined", {})
        signal = combined.get("signal", "NEUTRAL")
        combined_score = combined.get("score", 0)
        direction = tech.get("direction", 0)
        atr = tech.get("metrics", {}).get("atr", 0)
        if not atr or atr == "N/A":
            atr = 0

        has_position = key in positions

        # ── Check exit for existing positions ──────────
        if has_position:
            p = positions[key]
            pnl = 0.0
            exit_reason = None

            # Reversal: opposite direction signal
            if direction != 0 and direction != p["direction"]:
                exit_reason = f"reversal ({signal})"
            # Stop loss hit
            elif (p["direction"] == 1 and price <= p["stop_loss"]) or \
                 (p["direction"] == -1 and price >= p["stop_loss"]):
                exit_reason = "trailing_stop" if p.get("trail_activated") else "stop_loss"
            # Take profit hit
            elif p.get("take_profit", 0) > 0 and \
                 ((p["direction"] == 1 and price >= p["take_profit"]) or \
                  (p["direction"] == -1 and price <= p["take_profit"])):
                exit_reason = "take_profit"

            if exit_reason:
                pnl = (price - p["entry_price"]) * p["direction"] * p["units"]
                capital += pnl
                _append_journal({
                    "date": today,
                    "commodity": key,
                    "action": "EXIT",
                    "direction": "LONG" if p["direction"] == 1 else "SHORT",
                    "price": round(price, 2),
                    "units": round(p["units"], 4),
                    "pnl": round(pnl, 2),
                    "reason": exit_reason,
                    "capital": round(capital, 2),
                })
                logger.info("%s EXIT %s at %s%s — %s (P&L: %s%+.2f)",
                           cfg.name,
                           "LONG" if p["direction"] == 1 else "SHORT",
                           currency, price,
                           exit_reason, currency, pnl)
                del positions[key]
                closed_any = True

        # ── Update trailing stops for remaining positions ──
        if key in positions:
            p = positions[key]
            if p["direction"] == 1:
                if price > p["best_price"]:
                    p["best_price"] = price
                if not p.get("trail_activated") and atr > 0:
                    profit_atr = (price - p["entry_price"]) / atr
                    if profit_atr >= PAPER_CFG["trail_activation_atr"]:
                        p["trail_activated"] = True
                        p["take_profit"] = 0.0
                if p.get("trail_activated") and atr > 0:
                    new_sl = p["best_price"] - atr * PAPER_CFG["trail_distance_atr"]
                    if new_sl > p["stop_loss"]:
                        p["stop_loss"] = new_sl
            else:
                if price < p["best_price"]:
                    p["best_price"] = price
                if not p.get("trail_activated") and atr > 0:
                    profit_atr = (p["entry_price"] - price) / atr
                    if profit_atr >= PAPER_CFG["trail_activation_atr"]:
                        p["trail_activated"] = True
                        p["take_profit"] = 0.0
                if p.get("trail_activated") and atr > 0:
                    new_sl = p["best_price"] + atr * PAPER_CFG["trail_distance_atr"]
                    if new_sl < p["stop_loss"]:
                        p["stop_loss"] = new_sl

        # ── Entry: STRONG_BUY or STRONG_SELL ────────────
        if not has_position and direction != 0 and signal in ("STRONG_BUY", "STRONG_SELL") and atr > 0:
            pos_value = capital * PAPER_CFG["position_pct"]
            units = pos_value / price
            sl = price - atr * PAPER_CFG["sl_atr_mult"] if direction == 1 else \
                 price + atr * PAPER_CFG["sl_atr_mult"]
            tp = price + atr * PAPER_CFG["tp_atr_mult"] if direction == 1 else \
                 price - atr * PAPER_CFG["tp_atr_mult"]

            positions[key] = {
                "commodity": key,
                "direction": direction,
                "entry_date": today,
                "entry_price": price,
                "units": units,
                "atr": atr,
                "stop_loss": sl,
                "take_profit": tp,
                "trail_activated": False,
                "best_price": price,
            }
            capital -= pos_value  # Set aside the position capital
            _append_journal({
                "date": today,
                "commodity": key,
                "action": "ENTRY",
                "direction": "LONG" if direction == 1 else "SHORT",
                "price": round(price, 2),
                "units": round(units, 4),
                "pnl": 0.0,
                "reason": f"signal {signal} ({combined_score:+.0f})",
                "capital": round(capital, 2),
            })
            logger.info("%s ENTRY %s at %s%s (%s, score %+.0f)",
                       cfg.name,
                       "LONG" if direction == 1 else "SHORT",
                       currency, price,
                       signal, combined_score)

    # ── Save state ──
    state["capital"] = capital
    state["positions"] = positions
    _save_state(state)

    # ── Print summary ──
    print()
    print(f"  {'═' * 50}")
    print(f"  PAPER TRADING SUMMARY")
    print(f"  {'═' * 50}")
    print(f"  Capital: {currency}{capital:,.2f}")
    total_open_pnl = sum(
        (p["best_price"] - p["entry_price"]) * p["direction"] * p["units"]
        for p in positions.values()
    )
    eq = capital + max(total_open_pnl, 0)
    print(f"  Available: {currency}{capital:,.2f}")
    if positions:
        print(f"  Open P&L: {currency}{total_open_pnl:+,.2f}")
        print(f"  Equity:   {currency}{eq:,.2f}")
    _print_positions(state)
    print(f"  Journal: {JOURNAL_FILE}")
    print(f"  State:   {STATE_FILE}")

    return {"capital": capital, "positions": {k: dict(v) for k, v in positions.items()}}
