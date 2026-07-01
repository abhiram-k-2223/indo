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

from config import COMMODITIES, WEIGHTS, SIGNAL_THRESHOLDS, DATA_CONFIG, ALERT_CONFIG, DATA_SOURCE, TECHNICAL_CONFIG
from data import (
    fetch_price_data, fetch_all_prices, fetch_usd_inr,
    fetch_both_timeframes,
    compute_all_indicators, compute_indicators_safe, mcx_login, mcx_refresh_tokens,
)
from analysis import (
    analyze_technicals, analyze_multi_timeframe, signal_from_score, validate_thresholds,
    analyze_sentiment,
)
from reporting import generate_report, send_telegram, send_alert
from utils.log import setup_logger

logger = setup_logger()


def combine_signals(
    technical: Dict[str, Any],
    sentiment: Dict[str, Any],
    thresholds: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    if thresholds is None:
        thresholds = SIGNAL_THRESHOLDS
    combined_score = (
        technical.get("score", 0) * WEIGHTS["technical"]
        + sentiment.get("score", 0) * WEIGHTS["sentiment"]
    )

    sig, direction = signal_from_score(combined_score, thresholds)

    return {
        "signal": sig,
        "direction": direction,
        "score": round(combined_score, 1),
        "technical_weight": WEIGHTS["technical"],
        "sentiment_weight": WEIGHTS["sentiment"],
    }


def analyze_commodity(commodity_key: str) -> Dict[str, Any]:
    cfg = COMMODITIES.get(commodity_key)
    if not cfg or not cfg.active:
        return {}

    from data import fetch_hourly_data

    daily_df = fetch_price_data(commodity_key)
    if daily_df is None:
        logger.warning("%s: No price data available", cfg.name)
        return {"error": "No data", "price": "N/A"}

    daily_df = compute_indicators_safe(daily_df)
    latest = daily_df.iloc[-1]

    technical = analyze_technicals(daily_df, commodity_key)

    if TECHNICAL_CONFIG.get("mtf_enabled", True):
        hourly_df = fetch_hourly_data(commodity_key)
        if hourly_df is not None and len(hourly_df) >= 60:
            hourly_df = compute_indicators_safe(hourly_df)
            mtf = analyze_multi_timeframe(daily_df, hourly_df, technical, commodity_key)
            technical["score"] += mtf["adjustment"]
            if mtf["details"]:
                technical["details"].append(mtf["details"])
            technical["mtf"] = mtf
            sig, direction = signal_from_score(technical["score"])
            technical["signal"] = sig
            technical["direction"] = direction

    sentiment = analyze_sentiment(commodity_key)

    combined = combine_signals(technical, sentiment)

    return {
        "price": round(latest.get("close", 0), 2) if "close" in latest else "N/A",
        "technical": technical,
        "sentiment": sentiment,
        "combined": combined,
        "headlines": sentiment.get("headlines", []),
    }


def run_analysis() -> Dict[str, Dict[str, Any]]:
    is_mcx = DATA_SOURCE == "angel_one"
    source_label = "Angel One MCX data" if is_mcx else "yfinance US futures"
    logger.info("Fetching price data (%s)...", source_label)

    if is_mcx:
        mcx_login()
        mcx_refresh_tokens()

    usd_inr = fetch_usd_inr() if not is_mcx else None
    if usd_inr:
        logger.info("USD/INR: %.2f", usd_inr)
    elif not is_mcx:
        logger.warning("Could not fetch USD/INR")

    currency = "₹" if is_mcx else "$"
    results = {}
    for key, cfg in COMMODITIES.items():
        if not cfg.active:
            continue
        label = f"{cfg.name} (MCX: {cfg.mcx_symbol})" if is_mcx else f"{cfg.name} ({cfg.yfinance_ticker})"
        logger.info("Analyzing %s...", label)
        result = analyze_commodity(key)
        results[key] = result

        if "error" not in result:
            c = result["combined"]
            arrow = "🟢" if c["signal"] == "STRONG_BUY" else "📈" if c["signal"] == "BUY" else "🔴" if c["signal"] == "STRONG_SELL" else "📉" if c["signal"] == "SELL" else "⚪"
            logger.info("Price: %s%s  |  Signal: %s %s  |  Score: %+.1f", currency, result['price'], arrow, c['signal'], c['score'])

    return results, usd_inr


def llm_analysis(results: Dict[str, Dict[str, Any]], usd_inr: Optional[float]) -> Optional[str]:
    from config import LLM, DATA_SOURCE

    if not LLM["enabled"]:
        return None

    is_mcx = DATA_SOURCE == "angel_one"
    currency = "₹" if is_mcx else "$"

    logger.info("Requesting LLM narrative analysis...")

    prompt = "You are an Indian commodity market analyst. Based on this data, provide a concise "
    prompt += "trading outlook for each commodity. Mention key drivers and risks.\n\n"

    for key, res in results.items():
        if "error" in res:
            continue
        prompt += f"### {key.replace('_', ' ').title()}\n"
        prompt += f"Price: {currency}{res.get('price', 'N/A')}\n"
        prompt += f"Technical: {res['technical']['signal']} (score: {res['technical']['score']})\n"
        prompt += f"Sentiment: {res['sentiment']['signal']} (score: {res['sentiment']['score']})\n"
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
        logger.warning("LLM analysis failed: %s", e)
        return None

    return None


def _run_monitor(interval_minutes: int, paper: bool = False):
    threshold = ALERT_CONFIG["threshold_score"]
    notify_signals = set(ALERT_CONFIG["notify_on"])
    last_alerts: Dict[str, str] = {}

    is_mcx = DATA_SOURCE == "angel_one"
    source_label = "Angel One MCX data" if is_mcx else "yfinance US futures"
    currency = "₹" if is_mcx else "$"

    logger.info("Alert mode: checking every %dmin | threshold: |score| >= %d | source: %s", interval_minutes, threshold, source_label)
    logger.info("Only pushing Telegram alerts for: %s", ', '.join(notify_signals))
    if paper:
        logger.info("Paper trading enabled: tracking positions and P&L")

    if is_mcx:
        mcx_login()
        mcx_refresh_tokens()

    usd_inr = fetch_usd_inr() if not is_mcx else None
    if usd_inr:
        logger.info("USD/INR: %.2f", usd_inr)

    while True:
        now = datetime.now().strftime("%d %b %H:%M")
        triggered = []
        paper_results = {} if paper else None

        for key, cfg in COMMODITIES.items():
            if not cfg.active:
                continue
            result = analyze_commodity(key)
            if "error" in result:
                continue

            if paper:
                paper_results[key] = result

            c = result["combined"]
            score = c["score"]
            signal = c["signal"]

            alert_key = f"{key}|{signal}|{score:.0f}"
            prev = last_alerts.get(key)

            if signal in notify_signals and alert_key != prev:
                triggered.append((key, result))
                last_alerts[key] = alert_key

        if paper:
            from paper_trader import update as paper_update
            paper_update(paper_results)

        if triggered:
            msg_lines = [
                f"╔══ COMMODITY ALERT — {now} ══╗",
                "",
            ]
            for key, result in triggered:
                msg_lines.append(_build_alert_message(key, result, currency))
                msg_lines.append("")
            if usd_inr:
                msg_lines.append(f"USD/INR: {usd_inr:.2f}")
            msg_lines.append("╚══════════════════════════╝")

            alert = "\n".join(msg_lines)
            logger.info("\n%s — %d alert(s)\n%s", now, len(triggered), alert)

            if not send_telegram(alert):
                logger.warning("Alert Telegram send failed")
        else:
            logger.info("%s — no alerts (threshold: %d)", now, threshold)

        time.sleep(interval_minutes * 60)


def _build_alert_message(key: str, result: Dict[str, Any], currency: str = "$") -> str:
    cfg = COMMODITIES[key]
    c = result["combined"]
    tech = result["technical"]

    lines = []
    lines.append(f"🚨 {cfg.name} — {c['signal']} ({c['score']:+.0f})")
    lines.append(f"   Price: {currency}{result.get('price', '?')}")
    lines.append(f"   Technical: {tech['signal']} ({tech['score']:+.0f})")
    metrics = tech.get("metrics", {})
    extra_parts = []
    if "vol_ratio" in metrics:
        extra_parts.append(f"Vol:{metrics['vol_ratio']:.1f}x")
    if "oi_chg" in metrics:
        extra_parts.append(f"OI:{metrics['oi_chg']:+d}")
    mtf = tech.get("mtf", {})
    if mtf.get("status") == "confirmed":
        extra_parts.append("MTF:✓")
    elif mtf.get("status") == "caution":
        extra_parts.append("MTF:⚠")
    if extra_parts:
        lines.append(f"   {' '.join(extra_parts)}")
    mtf_detail = None
    for d in reversed(tech.get("details", [])):
        if d.startswith("MTF"):
            mtf_detail = d
            break
    top_details = tech.get("details", [])[:2]
    for d in top_details:
        lines.append(f"   {d}")
    if mtf_detail:
        lines.append(f"   {mtf_detail}")
    if result.get("headlines"):
        lines.append(f"   📰 {result['headlines'][0][:80]}")
    return "\n".join(lines)


def main():
    validate_thresholds()
    parser = argparse.ArgumentParser(description="Indian Commodity Market Agent")
    parser.add_argument("--telegram", action="store_true", help="Send report via Telegram")
    parser.add_argument("--schedule", type=int, default=0, metavar="HOURS",
                        help="Run on a schedule every N hours")
    parser.add_argument("--monitor", type=int, default=0, metavar="MINUTES",
                        help="Alert mode: check every N minutes, only push on high-confidence signals")
    parser.add_argument("--llm", action="store_true", help="Enable LLM narrative analysis")
    parser.add_argument("--paper", action="store_true", help="Paper trading mode: track positions and P&L")
    args = parser.parse_args()

    if args.llm:
        import os
        os.environ["LLM_ENABLED"] = "true"

    if args.monitor > 0:
        _run_monitor(args.monitor, paper=args.paper)
    elif args.schedule > 0:
        logger.info("Schedule mode: running every %d hours", args.schedule)
        while True:
            run_once(args.telegram, paper=args.paper)
            logger.info("Sleeping for %d hours...", args.schedule)
            time.sleep(args.schedule * 3600)
    else:
        run_once(args.telegram, paper=args.paper)


def run_once(send_telegram_flag: bool = False, paper: bool = False):
    results_dict = run_analysis()
    if isinstance(results_dict, tuple):
        results, usd_inr = results_dict
    else:
        results = results_dict
        usd_inr = None

    narrative = llm_analysis(results, usd_inr)
    is_mcx = DATA_SOURCE == "angel_one"

    report = generate_report(results, usd_inr, source=DATA_SOURCE)

    if narrative:
        report += "\n\n" + "=" * 54
        report += "\n  LLM NARRATIVE ANALYSIS"
        report += "\n" + "=" * 54
        report += "\n" + narrative

    print("\n\n" + report)

    if paper:
        from paper_trader import update as paper_update
        paper_update(results)

    if send_telegram_flag:
        sent = send_telegram(report)
        if sent:
            logger.info("Report sent via Telegram")
        else:
            logger.warning("Telegram send failed (check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)")


if __name__ == "__main__":
    main()
