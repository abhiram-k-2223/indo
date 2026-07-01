import numpy as np
import pandas as pd
from typing import Optional


def oi_divergence_signal(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    has_oi = "open_interest" in df.columns and df["open_interest"].notna().sum() > lookback
    if not has_oi:
        return pd.Series(0.0, index=df.index)

    price_ret = df["close"].pct_change()
    oi_ret = df["open_interest"].pct_change()

    divergence = price_ret * oi_ret
    rolling_mean = divergence.rolling(lookback, min_periods=lookback // 2).mean()
    rolling_std = divergence.rolling(lookback, min_periods=lookback // 2).std()
    rolling_std = rolling_std.replace(0, np.nan)

    z = (divergence - rolling_mean) / rolling_std
    return z.clip(-3, 3).fillna(0.0)
