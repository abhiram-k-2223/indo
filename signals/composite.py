import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from config import SIGNAL_SMOOTHING


def combine_z_scores(signals: Dict[str, pd.Series], weights: Dict[str, float]) -> pd.Series:
    common_idx = None
    for s in signals.values():
        if common_idx is None:
            common_idx = s.index
        else:
            common_idx = common_idx.intersection(s.index)

    total_weight = sum(weights.values())
    if total_weight == 0:
        return pd.Series(0.0, index=common_idx)

    result = pd.Series(0.0, index=common_idx)
    for name, signal in signals.items():
        w = weights.get(name, 0)
        if w == 0:
            continue
        aligned = signal.reindex(common_idx).fillna(0.0)
        result += w * aligned

    return result / total_weight


def _active_signals(df: pd.DataFrame, weights: Dict[str, float]) -> Dict[str, pd.Series]:
    from .oi import oi_divergence_signal
    from .momentum import time_series_momentum

    signals = {}
    if weights.get("oi", 0) != 0:
        sig = oi_divergence_signal(df)
        if sig.abs().max() > 0.01:
            signals["oi"] = sig
    if weights.get("momentum", 0) != 0:
        lookback = weights.get("momentum_lookback", 60)
        sig = time_series_momentum(df, lookback=lookback)
        if sig.abs().max() > 0.01:
            signals["momentum"] = sig

    return signals


def compute_composite_score(df: pd.DataFrame, weights: Dict[str, float]) -> float:
    signals = _active_signals(df, weights)
    if not signals:
        return 0.0

    active_keys = list(signals.keys())
    total_w = sum(weights.get(k, 0) for k in active_keys)
    if total_w == 0:
        return 0.0

    result = 0.0
    for name, sig in signals.items():
        w = weights.get(name, 0)
        result += w * float(sig.iloc[-1]) if len(sig) > 0 else 0.0

    return result / total_w


def compute_smoothed_score(df: pd.DataFrame, weights: Dict[str, float]) -> Dict[str, float]:
    signals = _active_signals(df, weights)
    if not signals:
        return {"composite": 0.0, "stability": 0.0, "consensus": 0.0, "smoothed": 0.0}

    active_keys = list(signals.keys())
    total_w = sum(weights.get(k, 0) for k in active_keys)
    if total_w == 0:
        return {"composite": 0.0, "stability": 0.0, "consensus": 0.0, "smoothed": 0.0}

    window = SIGNAL_SMOOTHING["window"]
    use_median = SIGNAL_SMOOTHING["use_median"]

    full_series = pd.Series(0.0, index=df.index)
    for name, sig in signals.items():
        w = weights.get(name, 0)
        aligned = sig.reindex(df.index).fillna(0.0)
        full_series += w * aligned
    full_series /= total_w

    raw_composite = float(full_series.iloc[-1])

    if len(full_series) >= window:
        if use_median:
            smoothed = float(full_series.iloc[-window:].median())
        else:
            smoothed = float(full_series.iloc[-window:].mean())
    else:
        smoothed = raw_composite

    recent = full_series.iloc[-window:] if len(full_series) >= window else full_series
    stability = float(recent.std()) if len(recent) > 1 else 0.0

    direction_signs = []
    for name, sig in signals.items():
        if len(sig) > 0:
            direction_signs.append(np.sign(sig.iloc[-1]))
    consensus_pct = abs(np.mean(direction_signs)) if direction_signs else 0.0

    return {
        "composite": round(raw_composite, 3),
        "smoothed": round(smoothed, 3),
        "stability": round(stability, 3),
        "consensus": round(consensus_pct, 2),
    }


def signal_details(df: pd.DataFrame, weights: Dict[str, float]) -> Dict[str, float]:
    signals = _active_signals(df, weights)
    details = {}
    for name, sig in signals.items():
        details[name] = float(sig.iloc[-1]) if len(sig) > 0 else 0.0

    smoothed = compute_smoothed_score(df, weights)
    details.update(smoothed)
    return details
