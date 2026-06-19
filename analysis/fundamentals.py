from typing import Dict, Any, Optional
import requests
from datetime import datetime, timedelta

from config import EIA_API_KEY


def analyze_fundamentals(commodity_key: str) -> Dict[str, Any]:
    result = {
        "signal": "NEUTRAL",
        "direction": 0,
        "score": 0,
        "details": [],
    }

    if commodity_key == "natural_gas" and EIA_API_KEY:
        result = _eia_natural_gas()
    elif commodity_key == "crude_oil" and EIA_API_KEY:
        result = _eia_crude_oil()
    else:
        if not EIA_API_KEY:
            result["details"].append("EIA API key not configured")
        else:
            result["details"].append(f"No EIA data for {commodity_key}")

    return result


def _eia_natural_gas() -> Dict[str, Any]:
    if not EIA_API_KEY:
        return _no_key()

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

            if change_pct > 3:
                direction = 1
                signal = "BULLISH"
            elif change_pct < -3:
                direction = -1
                signal = "BEARISH"
            else:
                direction = 0
                signal = "NEUTRAL"

            return {
                "signal": signal,
                "direction": direction,
                "score": round(change_pct, 1),
                "details": [
                    f"EIA nat gas price: ${curr:.2f} (prev: ${prev:.2f}, "
                    f"change: {change_pct:+.1f}%)"
                ],
            }
    except Exception:
        pass

    return _error("Failed to fetch EIA natural gas data")


def _eia_crude_oil() -> Dict[str, Any]:
    if not EIA_API_KEY:
        return _no_key()

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

            if change_pct > 2:
                direction = -1
                signal = "BEARISH"
                detail = f"Production rising ({change_pct:+.1f}%) — bearish for prices"
            elif change_pct < -2:
                direction = 1
                signal = "BULLISH"
                detail = f"Production declining ({change_pct:+.1f}%) — bullish for prices"
            else:
                direction = 0
                signal = "NEUTRAL"
                detail = f"Production stable ({change_pct:+.1f}%)"

            return {
                "signal": signal,
                "direction": direction,
                "score": round(-change_pct, 1),
                "details": [detail],
            }
    except Exception:
        pass

    return _error("Failed to fetch EIA crude oil data")


def _no_key() -> Dict[str, Any]:
    return {
        "signal": "NEUTRAL", "direction": 0, "score": 0,
        "details": ["Set EIA_API_KEY env var for fundamental data"],
    }


def _error(msg: str) -> Dict[str, Any]:
    return {
        "signal": "NEUTRAL", "direction": 0, "score": 0,
        "details": [msg],
    }
