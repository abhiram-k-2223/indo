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


COMMODITIES: Dict[str, CommodityConfig] = {
    "natural_gas": CommodityConfig(
        key="natural_gas", name="Natural Gas",
        yfinance_ticker="NG=F", mcx_symbol="NG",
    ),
    "crude_oil": CommodityConfig(
        key="crude_oil", name="Crude Oil",
        yfinance_ticker="CL=F", mcx_symbol="CL",
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

WEIGHTS = {
    "technical": 0.55,
    "sentiment": 0.25,
    "fundamental": 0.20,
}

TELEGRAM = {
    "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
}

LLM = {
    "enabled": os.getenv("LLM_ENABLED", "false").lower() == "true",
    "provider": os.getenv("LLM_PROVIDER", "ollama"),
    "api_key": os.getenv("LLM_API_KEY", ""),
    "model": os.getenv("LLM_MODEL", "hermes3"),
    "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
}

EIA_API_KEY = os.getenv("EIA_API_KEY", "")
