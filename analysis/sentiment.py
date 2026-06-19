import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import re

from config import SENTIMENT_CONFIG

NEWS_SOURCES = [
    ("Google News", SENTIMENT_CONFIG["google_news_rss"]),
]

POSITIVE_WORDS = {
    "surge", "jump", "rally", "gain", "bullish", "outperform", "positive",
    "growth", "higher", "increase", "breakout", "shortage", "supply gap",
    "demand", "boom", "recovery", "strength", "upside", "profit",
    "upgrade", "accumulate", "buy", "overweight", "tight supply",
    "production cut", "sanctions", "geopolitical tension",
}

NEGATIVE_WORDS = {
    "crash", "plunge", "slump", "fall", "drop", "decline", "bearish",
    "negative", "loss", "lower", "decrease", "selloff", "oversupply",
    "glut", "weakness", "downside", "downgrade", "reduce", "sell",
    "underweight", "glut", "surplus", "recession", "slowdown",
    "demand destruction", "lockdown", "tariff", "trade war",
}


def _fetch_news(keywords: List[str], max_items: int = 5) -> List[Dict[str, str]]:
    articles = []
    seen_titles = set()

    for keyword in keywords:
        query = keyword.replace(" ", "+")
        url = SENTIMENT_CONFIG["google_news_rss"].format(query=query)

        try:
            resp = requests.get(url, timeout=10, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
            })
            if resp.status_code != 200:
                continue

            root = ET.fromstring(resp.content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}

            for entry in root.findall(".//item"):
                title_el = entry.find("title")
                if title_el is None:
                    title_el = entry.find("atom:title", ns)
                link_el = entry.find("link")
                if link_el is None:
                    link_el = entry.find("atom:link", ns)
                if title_el is not None and title_el.text:
                    title = title_el.text.strip()
                    if title not in seen_titles:
                        seen_titles.add(title)
                        link = link_el.text if link_el is not None else ""
                        articles.append({"title": title, "link": link})
                if len(articles) >= max_items:
                    break

            if len(articles) >= max_items:
                break
        except Exception:
            continue

    return articles


def _score_headline(title: str) -> int:
    title_lower = title.lower()
    score = 0

    for word in POSITIVE_WORDS:
        if word in title_lower:
            score += 1

    for word in NEGATIVE_WORDS:
        if word in title_lower:
            score -= 1

    return score


def analyze_sentiment(commodity_key: str) -> Dict[str, Any]:
    keywords = SENTIMENT_CONFIG["keywords"].get(commodity_key, [commodity_key])
    articles = _fetch_news(keywords, max_items=5)

    if not articles:
        return {
            "signal": "NEUTRAL",
            "direction": 0,
            "score": 0,
            "article_count": 0,
            "headlines": [],
            "details": ["No recent news found"],
        }

    total_score = 0
    for article in articles:
        article["sentiment_score"] = _score_headline(article["title"])
        total_score += article["sentiment_score"]

    avg_score = total_score / len(articles)

    normalized = max(-100, min(100, avg_score * 20))

    if normalized >= 20:
        signal = "BULLISH"
        direction = 1
        detail = f"Positive sentiment ({avg_score:+.1f} avg across {len(articles)} articles)"
    elif normalized <= -20:
        signal = "BEARISH"
        direction = -1
        detail = f"Negative sentiment ({avg_score:+.1f} avg across {len(articles)} articles)"
    else:
        signal = "NEUTRAL"
        direction = 0
        detail = f"Mixed/neutral sentiment ({avg_score:+.1f})"

    return {
        "signal": signal,
        "direction": direction,
        "score": normalized,
        "article_count": len(articles),
        "headlines": [a["title"] for a in articles[:3]],
        "details": [detail],
    }
