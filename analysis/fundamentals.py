from typing import Dict, Any, Optional, List, Tuple
import requests
from datetime import datetime, timedelta
import numpy as np

from config import EIA_API_KEY, FUNDAMENTAL_CONFIG


def analyze_fundamentals(commodity_key: str) -> Dict[str, Any]:
    result = {
        "signal": "NEUTRAL",
        "direction": 0,
        "score": 0,
        "details": [],
        "components": {},
    }

    components = []
    if commodity_key == "natural_gas" and EIA_API_KEY:
        price = _eia_natural_gas_price()
        if price:
            components.append(("price_trend", price))
        storage = _eia_natural_gas_storage()
        if storage:
            components.append(("storage", storage))
    elif commodity_key == "crude_oil" and EIA_API_KEY:
        production = _eia_crude_production()
        if production:
            components.append(("production", production))
        inventory = _eia_crude_inventory()
        if inventory:
            components.append(("inventory", inventory))
    else:
        if not EIA_API_KEY:
            result["details"].append("Set EIA_API_KEY env var for fundamental data")
        else:
            result["details"].append(f"No EIA data for {commodity_key}")

    if components:
        composite_score = 0.0
        total_weight = 0.0
        for name, comp in components:
            w = comp.get("weight", 1.0)
            composite_score += comp["score"] * w
            total_weight += w
            result["components"][name] = comp

        if total_weight > 0:
            composite_score /= total_weight

        result["score"] = round(composite_score, 1)
        if composite_score >= FUNDAMENTAL_CONFIG["mom_change_threshold_pct"]:
            result["signal"] = "BULLISH"
            result["direction"] = 1
        elif composite_score <= -FUNDAMENTAL_CONFIG["mom_change_threshold_pct"]:
            result["signal"] = "BEARISH"
            result["direction"] = -1

    return result


def _eia_natural_gas_price() -> Optional[Dict[str, Any]]:
    if not EIA_API_KEY:
        return None
    try:
        url = (
            f"https://api.eia.gov/v2/natural-gas/pri/sum/data/"
            f"?api_key={EIA_API_KEY}"
            f"&frequency=weekly"
            f"&data[0]=value"
            f"&sort[0][column]=period&sort[0][direction]=desc"
            f"&length=5"
        )
        resp = requests.get(url, timeout=15)
        data = resp.json()
        series = data.get("response", {}).get("data", [])
        if len(series) >= 2:
            curr = float(series[0]["value"])
            prev = float(series[1]["value"])
            change_pct = ((curr - prev) / prev) * 100
            detail = f"EIA nat gas price: ${curr:.2f} (prev: ${prev:.2f}, change: {change_pct:+.1f}%)"
            return {
                "value": curr,
                "change_pct": round(change_pct, 1),
                "score": round(change_pct, 1),
                "weight": FUNDAMENTAL_CONFIG["price_change_weight"],
                "detail": detail,
            }
    except Exception:
        pass
    return None


def _eia_natural_gas_storage() -> Optional[Dict[str, Any]]:
    if not EIA_API_KEY:
        return None
    try:
        url = (
            f"https://api.eia.gov/v2/natural-gas/stor/wkly/data/"
            f"?api_key={EIA_API_KEY}"
            f"&frequency=weekly"
            f"&data[0]=value"
            f"&sort[0][column]=period&sort[0][direction]=desc"
            f"&length=55"
        )
        resp = requests.get(url, timeout=15)
        data = resp.json()
        series = data.get("response", {}).get("data", [])
        if len(series) >= 5:
            current = float(series[0]["value"])
            lookback = FUNDAMENTAL_CONFIG["eia_storage_lookback"]
            recent = [float(s["value"]) for s in series[:min(len(series), lookback)]]
            avg_storage = np.mean(recent)
            std_storage = np.std(recent)
            z_score = (current - avg_storage) / std_storage if std_storage > 0 else 0

            woW = ((current - float(series[1]["value"])) / float(series[1]["value"])) * 100

            score = -z_score * 5
            score = max(-100, min(100, score))

            detail = (
                f"Storage: {current:.1f} Bcf (vs 5yr avg {avg_storage:.0f}, "
                f"z={z_score:+.2f}, WoW: {woW:+.1f}%)"
            )
            return {
                "value": current,
                "z_score": round(z_score, 2),
                "woW_pct": round(woW, 1),
                "score": round(score, 1),
                "weight": FUNDAMENTAL_CONFIG["storage_vs_avg_weight"],
                "detail": detail,
            }
    except Exception:
        pass
    return None


def _eia_crude_production() -> Optional[Dict[str, Any]]:
    if not EIA_API_KEY:
        return None
    try:
        url = (
            f"https://api.eia.gov/v2/petroleum/crd/crpdn/data/"
            f"?api_key={EIA_API_KEY}"
            f"&frequency=monthly"
            f"&data[0]=value"
            f"&sort[0][column]=period&sort[0][direction]=desc"
            f"&length=3"
        )
        resp = requests.get(url, timeout=15)
        data = resp.json()
        series = data.get("response", {}).get("data", [])
        if len(series) >= 2:
            curr = float(series[0]["value"])
            prev = float(series[1]["value"])
            change_pct = ((curr - prev) / prev) * 100
            score = -change_pct
            detail = f"US crude production: {curr:.1f} mbpd ({change_pct:+.1f}% MoM)"
            return {
                "value": curr,
                "change_pct": round(change_pct, 1),
                "score": round(score, 1),
                "weight": 1.0,
                "detail": detail,
            }
    except Exception:
        pass
    return None


def _eia_crude_inventory() -> Optional[Dict[str, Any]]:
    if not EIA_API_KEY:
        return None
    try:
        url = (
            f"https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
            f"?api_key={EIA_API_KEY}"
            f"&frequency=weekly"
            f"&data[0]=value"
            f"&facets[duoarea][]=NUS"
            f"&facets[product][]=EPC0"
            f"&sort[0][column]=period&sort[0][direction]=desc"
            f"&length=55"
        )
        resp = requests.get(url, timeout=15)
        data = resp.json()
        series = data.get("response", {}).get("data", [])
        if len(series) >= 5:
            current = float(series[0]["value"])
            lookback = FUNDAMENTAL_CONFIG["eia_storage_lookback"]
            recent = [float(s["value"]) for s in series[:min(len(series), lookback)]]
            avg_inv = np.mean(recent)
            std_inv = np.std(recent)
            z_score = (current - avg_inv) / std_inv if std_inv > 0 else 0

            score = -z_score * 5
            score = max(-100, min(100, score))

            detail = (
                f"US crude inventory: {current:.1f} mbbl (vs 1yr avg {avg_inv:.0f}, "
                f"z={z_score:+.2f})"
            )
            return {
                "value": current,
                "z_score": round(z_score, 2),
                "score": round(score, 1),
                "weight": FUNDAMENTAL_CONFIG["storage_vs_avg_weight"],
                "detail": detail,
            }
    except Exception:
        pass
    return None
