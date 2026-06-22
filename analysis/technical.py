from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np

from config import TECHNICAL_CONFIG


def signal_from_score(score: int) -> Tuple[str, int]:
    if score >= 25:
        return "STRONG_BUY", 1
    elif score >= 8:
        return "BUY", 1
    elif score <= -25:
        return "STRONG_SELL", -1
    elif score <= -8:
        return "SELL", -1
    else:
        return "NEUTRAL", 0


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

    if "adx" in latest and pd.notna(latest["adx"]):
        adx_val = latest["adx"]
        result["metrics"]["adx"] = round(adx_val, 1)
        if adx_val < cfg["adx_threshold"]:
            result["details"].append(f"ADX {adx_val:.1f} — ranging market, signal suppressed")
            return result

    # ── Volume/OI confirmation ────────────────
    if "volume_ratio" in latest and pd.notna(latest["volume_ratio"]):
        vol_ratio = latest["volume_ratio"]
        price_up = latest["close"] > prev["close"]
        result["metrics"]["vol_ratio"] = round(vol_ratio, 2)

        if vol_ratio >= cfg["volume_high_threshold"]:
            if price_up:
                score += 8
                result["details"].append(f"Volume {vol_ratio:.1f}x avg — bullish confirmation")
            else:
                score -= 8
                result["details"].append(f"Volume {vol_ratio:.1f}x avg — bearish confirmation")
        elif vol_ratio <= cfg["volume_low_threshold"]:
            if price_up:
                score -= 4
                result["details"].append(f"Volume {vol_ratio:.1f}x avg — weak uptrend (divergence)")
            else:
                score += 4
                result["details"].append(f"Volume {vol_ratio:.1f}x avg — weak downtrend (divergence)")

    has_oi = "oi_change" in latest and pd.notna(latest.get("oi_change"))
    if has_oi:
        oi_chg = latest["oi_change"]
        price_up = latest["close"] > prev["close"]
        result["metrics"]["oi_chg"] = int(oi_chg)

        if oi_chg > 0:
            if price_up:
                score += 6
                result["details"].append("OI rising + price up — new longs entering")
            else:
                score -= 6
                result["details"].append("OI rising + price down — new shorts entering")
        elif oi_chg < 0:
            if price_up:
                score += 3
                result["details"].append("OI falling + price up — shorts covering")
            else:
                score -= 3
                result["details"].append("OI falling + price down — longs exiting")

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

    result["score"] = score
    sig, direction = signal_from_score(score)
    result["signal"] = sig
    result["direction"] = direction
    return result


def analyze_multi_timeframe(
    df_daily: pd.DataFrame,
    df_hourly: pd.DataFrame,
    daily_result: Dict[str, Any],
) -> Dict[str, Any]:
    cfg = TECHNICAL_CONFIG
    daily_score = daily_result["score"]

    daily_direction = 1 if daily_score > 0 else -1 if daily_score < 0 else 0

    result = {
        "status": "neutral",
        "adjustment": 0,
        "details": "",
    }

    if daily_direction == 0 or not cfg.get("mtf_enabled", True):
        return result

    latest_h = df_hourly.iloc[-1]
    sma_s = f"sma_{cfg['sma_short']}"
    rsi_k = f"rsi_{cfg['rsi_period']}"
    rsi_val = latest_h.get(rsi_k, 50)
    rsi_val = rsi_val if pd.notna(rsi_val) else 50

    price = latest_h["close"]
    near_sma_s = False
    if sma_s in latest_h and pd.notna(latest_h[sma_s]):
        tol = cfg.get("mtf_sma_tolerance", 0.015)
        near_sma_s = abs(price - latest_h[sma_s]) / latest_h[sma_s] < tol

    hourly_macd_bullish = False
    if "macd" in latest_h and "macd_signal" in latest_h:
        if pd.notna(latest_h["macd"]) and pd.notna(latest_h["macd_signal"]):
            hourly_macd_bullish = latest_h["macd"] > latest_h["macd_signal"]

    if daily_direction > 0:
        pulled_back = near_sma_s or (30 <= rsi_val <= 55)
        momentum_aligning = hourly_macd_bullish

        if pulled_back and momentum_aligning:
            result["status"] = "confirmed"
            result["adjustment"] = 15
            result["details"] = (
                f"MTF ✓ hourly pullback entry: RSI {rsi_val:.0f}, "
                f"near {cfg['sma_short']}-SMA, momentum turning bullish"
            )
        elif pulled_back:
            result["status"] = "confirmed"
            result["adjustment"] = 8
            result["details"] = (
                f"MTF ✓ daily bullish, hourly pullback to {cfg['sma_short']}-SMA "
                f"(RSI {rsi_val:.0f})"
            )
        elif rsi_val > cfg.get("rsi_overbought", 70):
            result["status"] = "caution"
            result["adjustment"] = -5
            result["details"] = (
                f"MTF ⚠ daily bullish but hourly extended "
                f"(RSI {rsi_val:.0f}, overbought)"
            )

    else:
        pulled_back = near_sma_s or (45 <= rsi_val <= 70)
        momentum_aligning = not hourly_macd_bullish

        if pulled_back and momentum_aligning:
            result["status"] = "confirmed"
            result["adjustment"] = 15
            result["details"] = (
                f"MTF ✓ hourly pullback entry: RSI {rsi_val:.0f}, "
                f"near {cfg['sma_short']}-SMA, momentum turning bearish"
            )
        elif pulled_back:
            result["status"] = "confirmed"
            result["adjustment"] = 8
            result["details"] = (
                f"MTF ✓ daily bearish, hourly pullback to {cfg['sma_short']}-SMA "
                f"(RSI {rsi_val:.0f})"
            )
        elif rsi_val < cfg.get("rsi_oversold", 30):
            result["status"] = "caution"
            result["adjustment"] = -5
            result["details"] = (
                f"MTF ⚠ daily bearish but hourly oversold "
                f"(RSI {rsi_val:.0f})"
            )

    return result


def _neutral(reason: str) -> Dict[str, Any]:
    return {
        "signal": "NEUTRAL",
        "direction": 0,
        "score": 0,
        "details": [reason],
        "metrics": {},
    }
