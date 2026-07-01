import yfinance as yf
import pandas as pd
import numpy as np
from typing import Optional, Dict, Tuple
from datetime import datetime

from config import COMMODITIES, DATA_CONFIG, TECHNICAL_CONFIG, SIGNAL_SMOOTHING


def fetch_price_data(commodity_key: str) -> Optional[pd.DataFrame]:
    cfg = COMMODITIES.get(commodity_key)
    if not cfg or not cfg.active:
        return None

    try:
        ticker = yf.Ticker(cfg.yfinance_ticker)
        df = ticker.history(
            period=DATA_CONFIG["price_period"],
            interval=DATA_CONFIG["price_interval"],
        )
        if df.empty or len(df) < DATA_CONFIG["min_history_days"]:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return None


def fetch_all_prices() -> Dict[str, Optional[pd.DataFrame]]:
    return {
        key: fetch_price_data(key)
        for key, cfg in COMMODITIES.items()
        if cfg.active
    }


def fetch_hourly_data(commodity_key: str) -> Optional[pd.DataFrame]:
    cfg = COMMODITIES.get(commodity_key)
    if not cfg or not cfg.active:
        return None

    try:
        ticker = yf.Ticker(cfg.yfinance_ticker)
        df = ticker.history(
            period=TECHNICAL_CONFIG.get("mtf_hourly_period", "1mo"),
            interval="1h",
        )
        if df.empty or len(df) < 60:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df
    except Exception:
        return None


def fetch_usd_inr() -> Optional[float]:
    try:
        ticker = yf.Ticker("USDINR=X")
        hist = ticker.history(period="5d")
        if not hist.empty:
            return round(hist["Close"].iloc[-1], 2)
    except Exception:
        pass

    try:
        import requests
        resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=10)
        data = resp.json()
        if data.get("result") == "success":
            inr = data["rates"].get("INR")
            if inr:
                return round(inr, 2)
    except Exception:
        pass

    return None


def _add_sma(df: pd.DataFrame, period: int) -> pd.DataFrame:
    df[f"sma_{period}"] = df["close"].rolling(window=period).mean()
    return df


def _add_ema(df: pd.DataFrame, period: int) -> pd.DataFrame:
    df[f"ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    return df


def _add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return df


def _add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["macd"] = ema_fast - ema_slow
    df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    return df


def _add_bollinger(df: pd.DataFrame, period: int = 20, std: int = 2) -> pd.DataFrame:
    middle = df["close"].rolling(window=period).mean()
    std_dev = df["close"].rolling(window=period).std()
    df["bb_mid"] = middle
    df["bb_upper"] = middle + (std_dev * std)
    df["bb_lower"] = middle - (std_dev * std)
    return df


def _add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=period).mean()
    return df


def _add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    high_low = high - low
    high_close = (high - close.shift(1)).abs()
    low_close = (low - close.shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    def _wilder_smooth(series: pd.Series, n: int) -> pd.Series:
        smooth = series.copy().astype(float)
        first = series.iloc[:n].mean()
        smooth.iloc[n - 1] = first
        for i in range(n, len(series)):
            smooth.iloc[i] = smooth.iloc[i - 1] - (smooth.iloc[i - 1] / n) + (series.iloc[i] / n)
        return smooth

    smooth_pos_dm = _wilder_smooth(pd.Series(pos_dm, index=df.index), period)
    smooth_neg_dm = _wilder_smooth(pd.Series(neg_dm, index=df.index), period)
    smooth_tr = _wilder_smooth(tr, period)

    plus_di = 100 * smooth_pos_dm / smooth_tr.replace(0, np.nan)
    minus_di = 100 * smooth_neg_dm / smooth_tr.replace(0, np.nan)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = _wilder_smooth(dx, period)

    df["adx"] = adx
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    return df


def _add_volume_indicators(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    vol = df["volume"]
    vol_sma = vol.rolling(window=period).mean()
    df[f"volume_sma_{period}"] = vol_sma
    df["volume_ratio"] = vol / vol_sma.replace(0, pd.NA)

    if "open_interest" in df.columns:
        oi = df["open_interest"]
        df["oi_change"] = oi.diff()
        oi_sma = oi.rolling(window=period).mean()
        df[f"oi_sma_{period}"] = oi_sma
        df["oi_ratio"] = oi / oi_sma.replace(0, pd.NA)

    return df


NEEDED_SMAS = {5, 9, 20, 21, 50, 100, 200}


def validate_bar_sequence(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        return df
    df = df.sort_index()
    dups = df.index.duplicated(keep="last")
    if dups.any():
        df = df[~dups]
    return df


def compute_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = validate_bar_sequence(df)
    cfg = TECHNICAL_CONFIG
    for p in sorted(NEEDED_SMAS):
        df = _add_sma(df, p)
    df = _add_ema(df, cfg["ema_short"])
    df = _add_ema(df, cfg["ema_long"])
    df = _add_rsi(df, cfg["rsi_period"])
    df = _add_macd(df, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"])
    df = _add_bollinger(df, cfg["bb_period"], cfg["bb_std"])
    df = _add_atr(df, cfg["atr_period"])
    df = _add_adx(df, cfg["adx_period"])
    df = _add_volume_indicators(df, cfg.get("volume_period", 20))
    return df


def compute_indicators_safe(df: pd.DataFrame, min_bars: int = 60) -> pd.DataFrame:
    df = compute_all_indicators(df)
    if len(df) < min_bars:
        return df
    return df
