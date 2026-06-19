from typing import Dict, Any, Optional
import pandas as pd

from config import TECHNICAL_CONFIG


def analyze_technicals(df: pd.DataFrame) -> Dict[str, Any]:
    if df is None or df.empty or len(df) < 30:
        return _neutral("Insufficient price history")

    cfg = TECHNICAL_CONFIG
    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else latest

    result = {
        "signal": "NEUTRAL",
        "direction": 0,
        "score": 0,
        "details": [],
        "metrics": {},
    }

    score = 0

    sma_s = f"sma_{cfg['sma_short']}"
    sma_l = f"sma_{cfg['sma_long']}"
    ema_s = f"ema_{cfg['ema_short']}"
    ema_l = f"ema_{cfg['ema_long']}"
    rsi_c = f"rsi_{cfg['rsi_period']}"

    if sma_s in latest and sma_l in latest:
        if pd.notna(latest[sma_s]) and pd.notna(latest[sma_l]):
            if latest[sma_s] > latest[sma_l]:
                score += 15
                result["details"].append("Bullish SMA crossover (short > long)")
            else:
                score -= 15
                result["details"].append("Bearish SMA crossover (short < long)")

    if ema_s in latest and ema_l in latest:
        if pd.notna(latest[ema_s]) and pd.notna(latest[ema_l]):
            if latest[ema_s] > latest[ema_l]:
                score += 10
                result["details"].append("Bullish EMA alignment")
            else:
                score -= 10
                result["details"].append("Bearish EMA alignment")

    if rsi_c in latest and pd.notna(latest[rsi_c]):
        rsi_val = latest[rsi_c]
        result["metrics"]["rsi"] = round(rsi_val, 1)
        if rsi_val > cfg["rsi_overbought"]:
            score -= 20
            result["details"].append(f"Overbought RSI ({rsi_val:.1f})")
        elif rsi_val < cfg["rsi_oversold"]:
            score += 20
            result["details"].append(f"Oversold RSI ({rsi_val:.1f})")
        elif rsi_val > 50:
            score += 8
            result["details"].append(f"RSI bullish ({rsi_val:.1f})")
        else:
            score -= 8
            result["details"].append(f"RSI bearish ({rsi_val:.1f})")

    if "macd" in latest and "macd_signal" in latest:
        macd_val = latest["macd"]
        signal_val = latest["macd_signal"]
        if pd.notna(macd_val) and pd.notna(signal_val):
            if macd_val > signal_val:
                score += 12
                result["details"].append("MACD above signal (bullish)")
            else:
                score -= 12
                result["details"].append("MACD below signal (bearish)")
        if "macd_hist" in latest and "macd_hist" in prev:
            if pd.notna(latest["macd_hist"]) and pd.notna(prev["macd_hist"]):
                if latest["macd_hist"] > prev["macd_hist"]:
                    score += 5
                    result["details"].append("MACD momentum increasing")
                else:
                    score -= 5
                    result["details"].append("MACD momentum decreasing")

    if "bb_upper" in latest and "bb_lower" in latest:
        close = latest["close"]
        upper = latest["bb_upper"]
        lower = latest["bb_lower"]
        if pd.notna(upper) and pd.notna(lower):
            if close >= upper:
                score -= 10
                result["details"].append("Price at upper Bollinger Band")
            elif close <= lower:
                score += 10
                result["details"].append("Price at lower Bollinger Band")
            else:
                bb_pos = (close - lower) / (upper - lower)
                if bb_pos > 0.7:
                    score -= 4
                elif bb_pos < 0.3:
                    score += 4

    result["metrics"]["price"] = round(latest["close"], 2)
    if "atr" in latest and pd.notna(latest["atr"]):
        result["metrics"]["atr"] = round(latest["atr"], 3)

    if score >= 25:
        result["signal"] = "STRONG_BUY"
        result["direction"] = 1
    elif score >= 8:
        result["signal"] = "BUY"
        result["direction"] = 1
    elif score <= -25:
        result["signal"] = "STRONG_SELL"
        result["direction"] = -1
    elif score <= -8:
        result["signal"] = "SELL"
        result["direction"] = -1
    else:
        result["signal"] = "NEUTRAL"
        result["direction"] = 0

    result["score"] = score
    return result


def _neutral(reason: str) -> Dict[str, Any]:
    return {
        "signal": "NEUTRAL",
        "direction": 0,
        "score": 0,
        "details": [reason],
        "metrics": {},
    }
