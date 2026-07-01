import os
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from dotenv import load_dotenv

load_dotenv()


@dataclass
class CommodityConfig:
    key: str
    name: str
    yfinance_ticker: str
    mcx_symbol: str = ""
    position_size: float = 1.0
    active: bool = True
    tech_overrides: Optional[Dict[str, Any]] = None


COMMODITIES: Dict[str, CommodityConfig] = {
    "natural_gas": CommodityConfig(
        key="natural_gas", name="Natural Gas",
        yfinance_ticker="NG=F", mcx_symbol="NATURALGAS",
        tech_overrides={"ma_slow_period": 100},
    ),
    "crude_oil": CommodityConfig(
        key="crude_oil", name="Crude Oil",
        yfinance_ticker="CL=F", mcx_symbol="CRUDEOIL",
        tech_overrides={"ma_slow_period": 100},
    ),
    "gold": CommodityConfig(
        key="gold", name="Gold",
        yfinance_ticker="GC=F", mcx_symbol="GOLD",
    ),
    "silver": CommodityConfig(
        key="silver", name="Silver",
        yfinance_ticker="SI=F", mcx_symbol="SILVER",
    ),
    "copper": CommodityConfig(
        key="copper", name="Copper",
        yfinance_ticker="HG=F", mcx_symbol="COPPER",
    ),
}

DATA_CONFIG = {
    "price_period": "3mo",
    "price_interval": "1d",
    "min_history_days": 30,
    "mcx_history_days": 90,
}

# ─── Data Source (yfinance or angel_one) ────────
DATA_SOURCE = os.getenv("DATA_SOURCE", "yfinance").lower()

# ─── Angel One SmartAPI (for MCX data) ──────────
ANGEL_ONE = {
    "api_key": os.getenv("ANGEL_API_KEY", ""),
    "client_id": os.getenv("ANGEL_CLIENT_ID", ""),
    "password": os.getenv("ANGEL_PASSWORD", ""),
    "totp_secret": os.getenv("ANGEL_TOTP_SECRET", ""),
}

TECHNICAL_CONFIG = {
    "sma_short": 9,
    "sma_long": 21,
    "ema_short": 9,
    "ema_long": 21,
    "rsi_period": 14,
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "bb_period": 20,
    "bb_std": 2,
    "atr_period": 14,
    "adx_period": 14,
    "adx_threshold": 25,
    "volume_period": 20,
    "volume_high_threshold": 1.3,
    "volume_low_threshold": 0.7,
    "mtf_enabled": True,
    "mtf_hourly_period": "1mo",
    "mtf_hourly_days": 30,
    "mtf_sma_tolerance": 0.015,
    "ma_fast_period": 50,
    "ma_slow_period": 200,
    "max_extension_pct": 25,
}

SENTIMENT_CONFIG = {
    "google_news_rss": "https://news.google.com/rss/search?q={query}+commodity+India+MCX&hl=en-IN&gl=IN&ceid=IN:en",
    "keywords": {
        "natural_gas": ["natural+gas", "LNG"],
        "crude_oil": ["crude+oil", "petroleum"],
        "gold": ["gold+price", "gold+market"],
        "silver": ["silver+price", "silver+market"],
        "copper": ["copper+price", "copper+market"],
    },
}

SIGNAL_THRESHOLDS = {
    "strong_buy": 25,
    "buy": 8,
    "sell": -8,
    "strong_sell": -25,
}

SIGNAL_SMOOTHING = {
    "window": 3,
    "min_consensus_pct": 0.5,
    "use_median": True,
}

WEIGHTS = {
    "technical": 0.65,
    "sentiment": 0.35,
}

SENTIMENT_WEIGHTS = {
    "phrase_match": 2.0,
    "single_word": 1.0,
    "llm_boost": 1.5,
    "confidence_threshold": 0.3,
}

TELEGRAM = {
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
}

LLM = {
    "enabled": os.getenv("LLM_ENABLED", "false").lower() == "true",
    "provider": os.getenv("LLM_PROVIDER", "llamacpp"),
    "api_key": os.getenv("LLM_API_KEY", ""),
    "model": os.getenv("LLM_MODEL", "default"),
    "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
    "llamacpp_url": os.getenv("LLMCPP_URL", "http://localhost:8080/v1"),
}

EIA_API_KEY = os.getenv("EIA_API_KEY", "")

ALERT_CONFIG = {
    "threshold_score": int(os.getenv("ALERT_THRESHOLD", "15")),
    "check_interval_minutes": int(os.getenv("ALERT_INTERVAL", "60")),
    "notify_on": ["STRONG_BUY", "STRONG_SELL"],
}
