import os
import time
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from urllib.parse import urlencode

import requests
import pandas as pd
import pyotp

from config import COMMODITIES, ANGEL_ONE, DATA_CONFIG, TECHNICAL_CONFIG

BASE_URL = "https://apiconnect.angelone.in"
ROUTES = {
    "login": "/rest/auth/angelbroking/user/v1/loginByClientCode",
    "search": "/rest/secure/angelbroking/market/v1/searchscrip",
    "candle": "/rest/secure/angelbroking/historical/v1/getCandleData",
}

_headers = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-UserType": "USER",
    "X-SourceID": "WEB",
    "X-ClientLocalIP": "127.0.0.1",
    "X-ClientPublicIP": "127.0.0.1",
    "X-MACAddress": "00:00:00:00:00:00",
}

_session: Optional[dict] = None


def _get_local_ip() -> str:
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _get_public_ip() -> str:
    try:
        return requests.get("https://api.ipify.org", timeout=5).text.strip()
    except Exception:
        return "127.0.0.1"


def _mac_address() -> str:
    try:
        import uuid
        return ":".join(format(b, "02x") for b in uuid.getnode().to_bytes(6, "big"))
    except Exception:
        return "00:00:00:00:00:00"


def _build_headers(api_key: str, jwt_token: str = "") -> dict:
    h = dict(_headers)
    h["X-PrivateKey"] = api_key
    if jwt_token:
        h["Authorization"] = f"Bearer {jwt_token}"
    return h


def login() -> bool:
    global _session
    api_key = ANGEL_ONE.get("api_key", "")
    client_id = ANGEL_ONE.get("client_id", "")
    password = ANGEL_ONE.get("password", "")
    totp_secret = ANGEL_ONE.get("totp_secret", "")

    if not all([api_key, client_id, password, totp_secret]):
        return False

    try:
        local_ip = _get_local_ip()
        public_ip = _get_public_ip()
        mac = _mac_address()

        headers = _build_headers(api_key)
        headers["X-ClientLocalIP"] = local_ip
        headers["X-ClientPublicIP"] = public_ip
        headers["X-MACAddress"] = mac

        totp = pyotp.TOTP(totp_secret).now()

        payload = {
            "clientcode": client_id,
            "password": password,
            "totp": totp,
        }

        resp = requests.post(
            f"{BASE_URL}{ROUTES['login']}",
            json=payload,
            headers=headers,
            timeout=15,
        )
        data = resp.json()

        if data.get("status"):
            _session = {
                "jwt_token": data["data"]["jwtToken"],
                "refresh_token": data["data"]["refreshToken"],
                "feed_token": data["data"].get("feedToken", ""),
                "api_key": api_key,
                "client_id": client_id,
                "local_ip": local_ip,
                "public_ip": public_ip,
                "mac": mac,
            }
            return True

        print(f"  ⚠ Angel One login failed: {data.get('message', 'unknown error')}")
        return False
    except Exception as e:
        print(f"  ⚠ Angel One login error: {e}")
        return False


def _headers() -> dict:
    if not _session:
        return {}
    h = _build_headers(_session["api_key"], _session["jwt_token"])
    h["X-ClientLocalIP"] = _session["local_ip"]
    h["X-ClientPublicIP"] = _session["public_ip"]
    h["X-MACAddress"] = _session["mac"]
    return h


def search_scrip(symbol: str) -> List[dict]:
    if not _session:
        return []

    try:
        resp = requests.post(
            f"{BASE_URL}{ROUTES['search']}",
            json={"exchange": "MCX", "searchscrip": symbol},
            headers=_headers(),
            timeout=15,
        )
        data = resp.json()
        if data.get("status") and data.get("data"):
            return data["data"]
        return []
    except Exception:
        return []


def _parse_timestamp(ts) -> pd.Timestamp:
    if isinstance(ts, (int, float)):
        return pd.to_datetime(ts, unit="ms")
    return pd.to_datetime(str(ts), errors="coerce")


def fetch_candle_data(
    symbol_token: str,
    interval: str = "ONE_DAY",
    days: int = 90,
) -> Optional[pd.DataFrame]:
    if not _session:
        return None

    to_date = datetime.now()
    from_date = to_date - timedelta(days=days)

    try:
        resp = requests.post(
            f"{BASE_URL}{ROUTES['candle']}",
            json={
                "exchange": "MCX",
                "symboltoken": symbol_token,
                "interval": interval,
                "fromdate": from_date.strftime("%Y-%m-%d %H:%M"),
                "todate": to_date.strftime("%Y-%m-%d %H:%M"),
            },
            headers=_headers(),
            timeout=15,
        )
        data = resp.json()

        if not data.get("status"):
            return None

        candles = data.get("data", [])
        if not candles:
            return None

        rows = []
        for c in candles:
            row = {
                "date": _parse_timestamp(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": int(c[5]),
            }
            if len(c) > 6:
                row["open_interest"] = int(c[6])
            rows.append(row)

        df = pd.DataFrame(rows)
        df = df.sort_values("date").reset_index(drop=True)
        df.set_index("date", inplace=True)
        return df

    except Exception:
        return None


def _find_near_month_token(symbol: str) -> Optional[str]:
    results = search_scrip(symbol)
    if not results:
        return None

    now = datetime.now()
    best_token = None
    best_expiry = None

    for scrip in results:
        token = scrip.get("symboltoken") or scrip.get("token")
        expiry_str = scrip.get("expiry") or ""
        symbol_name = scrip.get("symbol", "").upper()

        if not token:
            continue

        if expiry_str:
            try:
                expiry = pd.to_datetime(expiry_str, errors="coerce")
                if pd.isna(expiry):
                    continue
                if expiry < now:
                    continue
                if best_expiry is None or expiry < best_expiry:
                    best_expiry = expiry
                    best_token = token
            except Exception:
                continue
        else:
            if best_token is None:
                best_token = token

    return best_token


MCX_TOKENS: Dict[str, Optional[str]] = {}


def resolve_token(commodity_key: str) -> Optional[str]:
    if commodity_key in MCX_TOKENS:
        return MCX_TOKENS[commodity_key]

    cfg = COMMODITIES.get(commodity_key)
    if not cfg:
        return None

    mcx_symbol = cfg.mcx_symbol or cfg.yfinance_ticker.replace("=F", "")

    token = _find_near_month_token(mcx_symbol)
    MCX_TOKENS[commodity_key] = token
    return token


def refresh_all_tokens() -> Dict[str, Optional[str]]:
    for key, cfg in COMMODITIES.items():
        if cfg.active:
            resolve_token(key)
    return dict(MCX_TOKENS)


def fetch_mcx_price_data(commodity_key: str) -> Optional[pd.DataFrame]:
    if not _session:
        if not login():
            return None

    token = resolve_token(commodity_key)
    if not token:
        print(f"  ⚠ Could not resolve MCX token for {commodity_key}")
        return None

    df = fetch_candle_data(token, days=DATA_CONFIG.get("mcx_history_days", 90))
    if df is None or len(df) < DATA_CONFIG.get("min_history_days", 30):
        return None

    df.columns = [c.lower() for c in df.columns]
    return df


def fetch_mcx_hourly_data(commodity_key: str) -> Optional[pd.DataFrame]:
    if not _session:
        if not login():
            return None

    token = resolve_token(commodity_key)
    if not token:
        return None

    df = fetch_candle_data(
        token,
        interval="ONE_HOUR",
        days=TECHNICAL_CONFIG.get("mtf_hourly_days", 30),
    )
    if df is None or len(df) < 60:
        return None

    df.columns = [c.lower() for c in df.columns]
    return df


def fetch_all_mcx_prices() -> Dict[str, Optional[pd.DataFrame]]:
    if not _session:
        if not login():
            return {}

    refresh_all_tokens()
    return {
        key: fetch_mcx_price_data(key)
        for key, cfg in COMMODITIES.items()
        if cfg.active
    }
