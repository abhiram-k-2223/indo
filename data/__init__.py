from config import DATA_SOURCE

from .fetcher import (
    fetch_price_data as _fetch_yf,
    fetch_all_prices as _fetch_all_yf,
    fetch_hourly_data as _fetch_yf_hourly,
    fetch_usd_inr,
    compute_all_indicators,
)

from .mcx_fetcher import (
    fetch_mcx_price_data as _fetch_mcx,
    fetch_all_mcx_prices as _fetch_all_mcx,
    fetch_mcx_hourly_data as _fetch_mcx_hourly,
    login as mcx_login,
    refresh_all_tokens as mcx_refresh_tokens,
)


def fetch_price_data(commodity_key: str, source: str = ""):
    src = (source or DATA_SOURCE).lower()
    if src == "angel_one":
        return _fetch_mcx(commodity_key)
    return _fetch_yf(commodity_key)


def fetch_all_prices(source: str = ""):
    src = (source or DATA_SOURCE).lower()
    if src == "angel_one":
        return _fetch_all_mcx()
    return _fetch_all_yf()


def fetch_hourly_data(commodity_key: str, source: str = ""):
    src = (source or DATA_SOURCE).lower()
    if src == "angel_one":
        return _fetch_mcx_hourly(commodity_key)
    return _fetch_yf_hourly(commodity_key)


def fetch_both_timeframes(commodity_key: str, source: str = ""):
    daily = fetch_price_data(commodity_key, source)
    hourly = fetch_hourly_data(commodity_key, source)
    return daily, hourly
