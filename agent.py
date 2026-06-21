#!/usr/bin/env python3
"""
Indo — Indian Commodity Market Trading Agent.

Usage:
  python agent.py                     # run once and print report
  python agent.py --telegram          # run once and send via Telegram
  python agent.py --schedule 8        # run every 8 hours (loop)
  python agent.py --monitor 60        # alert mode: check every 60min, only push
                                       # on high-confidence signals (STRONG_BUY/SELL)
  python agent.py --llm               # include LLM analysis (requires Ollama/llama.cpp)

Environment variables:
  LLM_PROVIDER=ollama     Provider: ollama, openai, anthropic, llamacpp
  LLM_MODEL=hermes3       Model name
  OLLAMA_URL              Ollama server (default: http://localhost:11434)
  LLMCPP_URL              llama.cpp server (default: http://localhost:8080/v1)
  TELEGRAM_BOT_TOKEN      Telegram bot token (optional)
  TELEGRAM_CHAT_ID        Telegram chat ID (optional)
  EIA_API_KEY             EIA.gov API key for fundamentals (optional)
"""

import sys
import time
import argparse
import json
from datetime import datetime
from typing import Dict, Any, Optional

from config import COMMODITIES, WEIGHTS, DATA_CONFIG, ALERT_CONFIG
from data import fetch_price_data, fetch_all_prices, fetch_usd_inr, compute_all_indicators
from analysis import analyze_technicals, analyze_sentiment, analyze_fundamentals
from reporting import generate_report, send_telegram, send_alert


def combine_signals(
    technical: Dict[str, Any],
    sentiment: Dict[str, Any],
    fundamental: Dict[str, Any],
) -> Dict[str, Any]:
    combined_score = (
        technical.get("score", 0) * WEIGHTS["technical"]
        + sentiment.get("score", 0) * WEIGHTS["sentiment"]
        + fundamental.get("score", 0) * WEIGHTS["fundamental"]
    )

    if combined_score >= 20:
        signal = "STRONG_BUY"
    elif combined_score >= 6:
        signal = "BUY"
    elif combined_score <= -20:
        signal = "STRONG_SELL"
    elif combined_score <= -6:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    return {
        "signal": signal,
        "score": round(combined_score, 1),
        "technical_weight": WEIGHTS["technical"],
        "sentiment_weight": WEIGHTS["sentiment"],
        "fundamental_weight": WEIGHTS["fundamental"],
    }


def analyze_commodity(commodity_key: str) -> Dict[str, Any]:
    cfg = COMMODITIES.get(commodity_key)
    if not cfg or not cfg.active:
        return {}

    df = fetch_price_data(commodity_key)
    if df is None:
        print(f"  ⚠ {cfg.name}: No price data available", file=sys.stderr)
        return {"error": "No data", "price": "N/A"}

    df = compute_all_indicators(df)
    latest = df.iloc[-1]

    technical = analyze_technicals(df)
    sentiment = analyze_sentiment(commodity_key)
    fundamental = analyze_fundamentals(commodity_key)

    combined = combine_signals(technical, sentiment, fundamental)

    return {
        "price": round(latest.get("close", 0), 2) if "close" in latest else "N/A",
        "technical": technical,
        "sentiment": sentiment,
        "fundamental": fundamental,
        "combined": combined,
        "headlines": sentiment.get("headlines", []),
    }


def run_analysis() -> Dict[str, Dict[str, Any]]:
    print("🔄 Fetching price data...")
    usd_inr = fetch_usd_inr()
    if usd_inr:
        print(f"   USD/INR: {usd_inr:.2f}")
    else:
        print("   ⚠ Could not fetch USD/INR")

    results = {}
    for key, cfg in COMMODITIES.items():
        if not cfg.active:
            continue
        print(f"\n📊 Analyzing {cfg.name} ({cfg.yfinance_ticker})...")
        result = analyze_commodity(key)
        results[key] = result

        if "error" not in result:
            c = result["combined"]
            arrow = "🟢" if c["signal"] == "STRONG_BUY" else "📈" if c["signal"] == "BUY" else "🔴" if c["signal"] == "STRONG_SELL" else "📉" if c["signal"] == "SELL" else "⚪"
            print(f"   Price: ${result['price']}  |  Signal: {arrow} {c['signal']}  |  Score: {c['score']:+.1f}")

    return results, usd_inr


def llm_analysis(results: Dict[str, Dict[str, Any]], usd_inr: Optional[float]) -> Optional[str]:
    from config import LLM

    if not LLM["enabled"]:
        return None

    print("\n🧠 Requesting LLM narrative analysis...")

    prompt = "You are an Indian commodity market analyst. Based on this data, provide a concise "
    prompt += "trading outlook for each commodity. Mention key drivers and risks.\n\n"

    for key, res in results.items():
        if "error" in res:
            continue
        prompt += f"### {key.replace('_', ' ').title()}\n"
        prompt += f"Price: ${res.get('price', 'N/A')}\n"
        prompt += f"Technical: {res['technical']['signal']} (score: {res['technical']['score']})\n"
        prompt += f"Sentiment: {res['sentiment']['signal']} (score: {res['sentiment']['score']})\n"
        prompt += f"Fundamental: {res['fundamental']['signal']} (score: {res['fundamental']['score']})\n"
        prompt += f"Combined: {res['combined']['signal']} (score: {res['combined']['score']})\n\n"

    if usd_inr:
        prompt += f"USD/INR: {usd_inr}\n"
    prompt += "\nProvide a brief actionable outlook for each commodity in 1-2 sentences."

    try:
        if LLM["provider"] == "ollama":
            url = f"{LLM['ollama_url']}/api/generate"
            payload = {
                "model": LLM["model"],
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3},
            }
            import requests
            resp = requests.post(url, json=payload, timeout=60)
            data = resp.json()
            return data.get("response", "").strip()

        elif LLM["provider"] == "openai":
            import openai
            client = openai.OpenAI(api_key=LLM["api_key"])
            resp = client.chat.completions.create(
                model=LLM["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return resp.choices[0].message.content.strip()

        elif LLM["provider"] == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=LLM["api_key"])
            resp = client.messages.create(
                model=LLM["model"],
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()

        elif LLM["provider"] in ("llamacpp", "llama.cpp"):
            import openai
            client = openai.OpenAI(
                base_url=LLM["llamacpp_url"],
                api_key="not-needed",
            )
            resp = client.chat.completions.create(
                model=LLM["model"],
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1000,
            )
            return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"   ⚠ LLM analysis failed: {e}", file=sys.stderr)
        return None

    return None


def _run_monitor(interval_minutes: int):
    threshold = ALERT_CONFIG["threshold_score"]
    notify_signals = set(ALERT_CONFIG["notify_on"])
    last_alerts: Dict[str, str] = {}

    print(f"🔍 Alert mode: checking every {interval_minutes}min | threshold: |score| ≥ {threshold}")
    print(f"   Only pushing Telegram alerts for: {', '.join(notify_signals)}")

    usd_inr = fetch_usd_inr()
    if usd_inr:
        print(f"   USD/INR: {usd_inr:.2f}")

    while True:
        now = datetime.now().strftime("%d %b %H:%M")
        triggered = []

        for key, cfg in COMMODITIES.items():
            if not cfg.active:
                continue
            result = analyze_commodity(key)
            if "error" in result:
                continue

            c = result["combined"]
            score = c["score"]
            signal = c["signal"]

            alert_key = f"{key}|{signal}|{score:.0f}"
            prev = last_alerts.get(key)

            if signal in notify_signals and alert_key != prev:
                triggered.append((key, result))
                last_alerts[key] = alert_key

        if triggered:
            msg_lines = [
                f"╔══ COMMODITY ALERT — {now} ══╗",
                "",
            ]
            for key, result in triggered:
                msg_lines.append(_build_alert_message(key, result))
                msg_lines.append("")
            msg_lines.append(f"USD/INR: {usd_inr:.2f}" if usd_inr else "")
            msg_lines.append("╚══════════════════════════╝")

            alert = "\n".join(msg_lines)
            print(f"\n{now} — {len(triggered)} alert(s)")
            print(alert)

            send_telegram(alert)
        else:
            print(f"{now} — no alerts (threshold: {threshold})", file=sys.stderr)

        time.sleep(interval_minutes * 60)


def _build_alert_message(key: str, result: Dict[str, Any]) -> str:
    cfg = COMMODITIES[key]
    c = result["combined"]
    tech = result["technical"]

    lines = []
    lines.append(f"🚨 {cfg.name} — {c['signal']} ({c['score']:+.0f})")
    lines.append(f"   Price: ${result.get('price', '?')}")
    lines.append(f"   Technical: {tech['signal']} ({tech['score']:+.0f})")
    top_details = tech.get("details", [])[:2]
    for d in top_details:
        lines.append(f"   {d}")
    if result.get("headlines"):
        lines.append(f"   📰 {result['headlines'][0][:80]}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Indian Commodity Market Agent")
    parser.add_argument("--telegram", action="store_true", help="Send report via Telegram")
    parser.add_argument("--schedule", type=int, default=0, metavar="HOURS",
                        help="Run on a schedule every N hours")
    parser.add_argument("--monitor", type=int, default=0, metavar="MINUTES",
                        help="Alert mode: check every N minutes, only push on high-confidence signals")
    parser.add_argument("--llm", action="store_true", help="Enable LLM narrative analysis")
    args = parser.parse_args()

    if args.llm:
        import os
        os.environ["LLM_ENABLED"] = "true"

    if args.monitor > 0:
        _run_monitor(args.monitor)
    elif args.schedule > 0:
        print(f"⏰ Schedule mode: running every {args.schedule} hours")
        while True:
            run_once(args.telegram)
            print(f"\n💤 Sleeping for {args.schedule} hours...")
            time.sleep(args.schedule * 3600)
    else:
        run_once(args.telegram)


def run_once(send_telegram_flag: bool = False):
    results_dict = run_analysis()
    if isinstance(results_dict, tuple):
        results, usd_inr = results_dict
    else:
        results = results_dict
        usd_inr = None

    narrative = llm_analysis(results, usd_inr)

    report = generate_report(results, usd_inr)

    if narrative:
        report += "\n\n" + "=" * 54
        report += "\n  LLM NARRATIVE ANALYSIS"
        report += "\n" + "=" * 54
        report += "\n" + narrative

    print("\n\n" + report)

    if send_telegram_flag:
        sent = send_telegram(report)
        if sent:
            print("\n✓ Report sent via Telegram")
        else:
            print("\n✗ Telegram send failed (check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")


if __name__ == "__main__":
    main()
