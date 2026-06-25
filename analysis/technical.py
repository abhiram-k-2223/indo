from typing import Dict, Any, Optional, Tuple
import pandas as pd
import numpy as np

from config import TECHNICAL_CONFIG, COMMODITIES


def _config_for(commodity_key: str) -> dict:
    cfg = dict(TECHNICAL_CONFIG)
    commodity = COMMODITIES.get(commodity_key)
    if commodity and commodity.tech_overrides:
        cfg.update(commodity.tech_overrides)
    return cfg


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


def analyze_technicals(df: pd.DataFrame, commodity_key: str = "") -> Dict[str, Any]:
    """Trend-following indicator: dual MA crossover + ADX filter + volume confirmation."""
    if df is None or df.empty or len(df) < 60:
        return _neutral("Insufficient price history")

    cfg = _config_for(commodity_key)
    latest = df.iloc[-1]

    result = {
        "signal": "NEUTRAL",
        "direction": 0,
        "score": 0,
        "details": [],
        "metrics": {},
    }
    score = 0

    # ── 1) ADX regime filter ──────────────
    if "adx" in latest and pd.notna(latest["adx"]):
        adx_val = latest["adx"]
        result["metrics"]["adx"] = round(adx_val, 1)
        if adx_val < cfg["adx_threshold"]:
            result["details"].append(f"ADX {adx_val:.1f} < {cfg['adx_threshold']} — ranging, no signal")
            return result

    # ── 2) Dual MA crossover ───
    ma_fast = cfg.get("ma_fast_period", 50)
    ma_slow = cfg.get("ma_slow_period", 200)
    sma_f = f"sma_{ma_fast}"
    sma_s = f"sma_{ma_slow}"
    if sma_f in latest and sma_s in latest:
        sma_fv = latest[sma_f]
        sma_sv = latest[sma_s]
        if pd.notna(sma_fv) and pd.notna(sma_sv):
            if sma_fv > sma_sv:
                score += 40
                result["details"].append(
                    f"{ma_fast}-SMA ({sma_fv:.1f}) above {ma_slow}-SMA ({sma_sv:.1f}) — uptrend"
                )
            else:
                score -= 40
                result["details"].append(
                    f"{ma_fast}-SMA ({sma_fv:.1f}) below {ma_slow}-SMA ({sma_sv:.1f}) — downtrend"
                )

    # ── 3) Price vs slow-SMA (trend alignment + extension check) ──
    if sma_s in latest and pd.notna(latest[sma_s]):
        price = latest["close"]
        sma_sv = latest[sma_s]
        result["metrics"]["trend_sma"] = round(sma_sv, 2)
        dist_pct = (price - sma_sv) / sma_sv * 100
        result["metrics"]["trend_dist_pct"] = round(dist_pct, 2)
        max_ext = cfg.get("max_extension_pct", 25)
        if price > sma_sv:
            if dist_pct > max_ext:
                result["details"].append(
                    f"Price {dist_pct:+.1f}% above {ma_slow}-SMA — overextended, skip long"
                )
                return result
            score += 15
            result["details"].append(f"Price {dist_pct:+.1f}% above {ma_slow}-SMA — macro bullish")
        else:
            if abs(dist_pct) > max_ext:
                result["details"].append(
                    f"Price {dist_pct:+.1f}% below {ma_slow}-SMA — overextended, skip short"
                )
                return result
            score -= 15
            result["details"].append(f"Price {dist_pct:+.1f}% below {ma_slow}-SMA — macro bearish")

    # ── 4) Short-term momentum (5 vs 20 SMA) ──
    sma5 = "sma_5"
    sma20 = "sma_20"
    if sma5 in latest and sma20 in latest:
        sma5v = latest[sma5]
        sma20v = latest[sma20]
        if pd.notna(sma5v) and pd.notna(sma20v):
            if sma5v > sma20v:
                score += 10
                result["details"].append("Short-term momentum bullish (5-SMA > 20-SMA)")
            else:
                score -= 10
                result["details"].append("Short-term momentum bearish (5-SMA < 20-SMA)")

    # ── 5) Volume confirmation ────────────
    if "volume_ratio" in latest and pd.notna(latest["volume_ratio"]):
        vol_ratio = latest["volume_ratio"]
        result["metrics"]["vol_ratio"] = round(vol_ratio, 2)
        price_up = latest["close"] > df.iloc[-2]["close"]
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
                result["details"].append(f"Volume {vol_ratio:.1f}x avg — weak uptrend")
            else:
                score += 4
                result["details"].append(f"Volume {vol_ratio:.1f}x avg — weak downtrend")

    # ── 6) RSI directional ────────────────
    rsi_c = f"rsi_{cfg['rsi_period']}"
    if rsi_c in latest and pd.notna(latest[rsi_c]):
        rsi_val = latest[rsi_c]
        result["metrics"]["rsi"] = round(rsi_val, 1)
        if rsi_val > 50:
            score += 8
            result["details"].append(f"RSI bullish ({rsi_val:.1f})")
        else:
            score -= 8
            result["details"].append(f"RSI bearish ({rsi_val:.1f})")

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
    commodity_key: str = "",
) -> Dict[str, Any]:
    cfg = _config_for(commodity_key)
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
