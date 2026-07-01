import numpy as np
import pandas as pd


def time_series_momentum(df: pd.DataFrame, lookback: int = 60) -> pd.Series:
    ret = df["close"] / df["close"].shift(lookback) - 1

    if "atr" in df.columns:
        atr = df["atr"]
    else:
        atr = df["close"].diff().abs().rolling(14).mean()

    atr_pct = atr / df["close"]
    atr_pct = atr_pct.replace(0, np.nan)

    vol_norm = ret / (atr_pct * np.sqrt(lookback))
    return vol_norm.clip(-3, 3).fillna(0.0)
