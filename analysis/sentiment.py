import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import re
import json

from config import SENTIMENT_CONFIG, LLM

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


def _llm_score_headline(title: str, commodity_name: str) -> int:
    if not LLM["enabled"]:
        return None

    prompt = (
        f"Classify this news headline as BULLISH, BEARISH, or NEUTRAL "
        f"for {commodity_name} prices. Reply with only one word.\n"
        f"Headline: {title}"
    )

    try:
        if LLM["provider"] == "ollama":
            url = f"{LLM['ollama_url']}/api/generate"
            resp = requests.post(url, json={
                "model": LLM["model"], "prompt": prompt,
                "stream": False, "options": {"temperature": 0.1},
            }, timeout=15)
            answer = resp.json().get("response", "").strip().upper()

        elif LLM["provider"] in ("llamacpp", "llama.cpp"):
            import openai
            client = openai.OpenAI(base_url=LLM["llamacpp_url"], api_key="not-needed")
            resp = client.chat.completions.create(
                model=LLM["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=10,
            )
            answer = resp.choices[0].message.content.strip().upper()

        elif LLM["provider"] == "openai":
            import openai
            client = openai.OpenAI(api_key=LLM["api_key"])
            resp = client.chat.completions.create(
                model=LLM["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1, max_tokens=10,
            )
            answer = resp.choices[0].message.content.strip().upper()

        elif LLM["provider"] == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=LLM["api_key"])
            resp = client.messages.create(
                model=LLM["model"], max_tokens=10,
                messages=[{"role": "user", "content": prompt}],
            )
            answer = resp.content[0].text.strip().upper()
        else:
            return None

        if "BULLISH" in answer:
            return 2
        elif "BEARISH" in answer:
            return -2
        return 0

    except Exception:
        return None


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

    cfg = __import__("config").COMMODITIES.get(commodity_key)
    commodity_name = cfg.name if cfg else commodity_key

    total_score = 0
    llm_used = False
    for article in articles:
        llm_score = _llm_score_headline(article["title"], commodity_name)
        if llm_score is not None:
            article["sentiment_score"] = llm_score
            llm_used = True
        else:
            article["sentiment_score"] = _score_headline(article["title"])
        total_score += article["sentiment_score"]

    avg_score = total_score / len(articles)

    normalized = max(-100, min(100, avg_score * 20))

    method = "LLM" if llm_used else "keywords"
    if normalized >= 20:
        signal = "BULLISH"
        direction = 1
        detail = f"Positive sentiment ({method}, {avg_score:+.1f} avg across {len(articles)} articles)"
    elif normalized <= -20:
        signal = "BEARISH"
        direction = -1
        detail = f"Negative sentiment ({method}, {avg_score:+.1f} avg across {len(articles)} articles)"
    else:
        signal = "NEUTRAL"
        direction = 0
        detail = f"Mixed/neutral sentiment ({method}, {avg_score:+.1f})"

    return {
        "signal": signal,
        "direction": direction,
        "score": normalized,
        "article_count": len(articles),
        "headlines": [a["title"] for a in articles[:3]],
        "details": [detail],
    }
