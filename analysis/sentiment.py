import requests
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import re
import json

from config import SENTIMENT_CONFIG, LLM, SENTIMENT_WEIGHTS

NEWS_SOURCES = [
    ("Google News", SENTIMENT_CONFIG["google_news_rss"]),
]

PHRASES = [
    ("supply disruption", 1, 3.0),
    ("production cut", 1, 3.0),
    ("supply glut", -1, 3.0),
    ("oversupply", -1, 3.0),
    ("tight supply", 1, 2.5),
    ("supply shortage", 1, 2.5),
    ("demand destruction", -1, 2.5),
    ("geopolitical tension", 1, 2.5),
    ("trade war", -1, 2.5),
    ("production increase", -1, 2.0),
    ("inventory build", -1, 2.0),
    ("inventory draw", 1, 2.0),
    ("supply gap", 1, 2.0),
    ("demand recovery", 1, 2.0),
    ("demand slowdown", -1, 2.0),
    ("output cut", -0.5, 2.0),
    ("export ban", 1, 2.0),
    ("export restriction", 1, 2.0),
    ("price cap", -1, 1.5),
    ("price surge", 1, 1.5),
]

POSITIVE_WORDS = {
    "surge", "jump", "rally", "gain", "bullish", "outperform", "positive",
    "growth", "higher", "increase", "breakout", "shortage", "recovery",
    "strength", "upside", "profit", "upgrade", "accumulate", "buy",
    "overweight", "boom", "tight", "rebound", "uptick", "acceleration",
}

NEGATIVE_WORDS = {
    "crash", "plunge", "slump", "fall", "drop", "decline", "bearish",
    "negative", "loss", "lower", "decrease", "selloff", "glut",
    "weakness", "downside", "downgrade", "reduce", "sell",
    "underweight", "surplus", "recession", "slowdown",
    "lockdown", "tariff", "deficit", "contraction",
}


def _score_headline(title: str) -> Tuple[int, float]:
    title_lower = title.lower()
    score = 0
    matches = 0

    for phrase, direction, weight in PHRASES:
        if phrase in title_lower:
            score += direction * weight * SENTIMENT_WEIGHTS["phrase_match"]
            matches += 1

    for word in POSITIVE_WORDS:
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, title_lower):
            score += SENTIMENT_WEIGHTS["single_word"]
            matches += 1

    for word in NEGATIVE_WORDS:
        pattern = r'\b' + re.escape(word) + r'\b'
        if re.search(pattern, title_lower):
            score -= SENTIMENT_WEIGHTS["single_word"]
            matches += 1

    confidence = min(1.0, matches / 5.0) if matches > 0 else 0.0
    return int(score), confidence


def _llm_score_headline(title: str, commodity_name: str) -> Optional[Tuple[int, float]]:
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
            return (2, 0.8)
        elif "BEARISH" in answer:
            return (-2, 0.8)
        return (0, 0.3)

    except Exception:
        return None


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


def analyze_sentiment(commodity_key: str) -> Dict[str, Any]:
    keywords = SENTIMENT_CONFIG["keywords"].get(commodity_key, [commodity_key])
    articles = _fetch_news(keywords, max_items=5)

    if not articles:
        return {
            "signal": "NEUTRAL",
            "direction": 0,
            "score": 0,
            "confidence": 0.0,
            "article_count": 0,
            "headlines": [],
            "details": ["No recent news found"],
        }

    cfg = __import__("config").COMMODITIES.get(commodity_key)
    commodity_name = cfg.name if cfg else commodity_key

    total_score = 0
    total_confidence = 0.0
    llm_used = False
    for article in articles:
        llm_result = _llm_score_headline(article["title"], commodity_name)
        if llm_result is not None:
            llm_score, llm_conf = llm_result
            article["sentiment_score"] = int(llm_score * SENTIMENT_WEIGHTS["llm_boost"])
            article["confidence"] = llm_conf
            llm_used = True
        else:
            kw_score, kw_conf = _score_headline(article["title"])
            article["sentiment_score"] = kw_score
            article["confidence"] = kw_conf
        total_score += article["sentiment_score"]
        total_confidence += article["confidence"]

    avg_score = total_score / len(articles)
    avg_confidence = total_confidence / len(articles)

    normalized = max(-100, min(100, avg_score * 15 / (1 + avg_confidence)))

    method = "LLM" if llm_used else "keywords"
    if normalized >= SENTIMENT_WEIGHTS["confidence_threshold"] * 100:
        signal = "BULLISH"
        direction = 1
        detail = f"Positive sentiment ({method}, score {avg_score:+.1f}, conf {avg_confidence:.2f}, {len(articles)} articles)"
    elif normalized <= -SENTIMENT_WEIGHTS["confidence_threshold"] * 100:
        signal = "BEARISH"
        direction = -1
        detail = f"Negative sentiment ({method}, score {avg_score:+.1f}, conf {avg_confidence:.2f}, {len(articles)} articles)"
    else:
        signal = "NEUTRAL"
        direction = 0
        detail = f"Mixed/neutral sentiment ({method}, score {avg_score:+.1f}, conf {avg_confidence:.2f})"

    return {
        "signal": signal,
        "direction": direction,
        "score": normalized,
        "confidence": round(avg_confidence, 2),
        "article_count": len(articles),
        "headlines": [a["title"] for a in articles[:3]],
        "details": [detail],
    }
