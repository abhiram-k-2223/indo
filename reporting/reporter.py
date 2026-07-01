import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime
from textwrap import dedent

from config import TELEGRAM, COMMODITIES, WEIGHTS

logger = logging.getLogger(__name__)


def generate_report(
    results: Dict[str, Dict[str, Any]],
    usd_inr: Optional[float] = None,
    source: str = "yfinance",
) -> str:
    lines = []
    now = datetime.now().strftime("%d %b %Y %H:%M")
    is_mcx = source == "angel_one"
    currency = "₹" if is_mcx else "$"

    lines.append("=" * 54)
    lines.append(f"  INDIAN COMMODITY MARKET REPORT")
    lines.append(f"  {now}")
    lines.append(f"  Data source: {'Angel One MCX' if is_mcx else 'yfinance US futures'}")
    lines.append("=" * 54)

    if usd_inr:
        lines.append(f"")
        lines.append(f"  USD/INR: {usd_inr:.2f}")

    for key, cfg in COMMODITIES.items():
        if not cfg.active or key not in results:
            continue

        res = results[key]
        lines.append("")
        lines.append(f"{'─' * 54}")
        ticker = cfg.mcx_symbol if is_mcx else cfg.yfinance_ticker
        lines.append(f"  {cfg.name.upper()} ({currency}{res.get('price', '?')}) [{ticker}]")
        lines.append(f"{'─' * 54}")

        for component in ["technical", "sentiment"]:
            comp = res.get(component, {})
            sig = comp.get("signal", "N/A")
            score = comp.get("score", 0)
            direction = comp.get("direction", 0)

            arrow = "▲" if direction > 0 else "▼" if direction < 0 else "◆"
            metrics = comp.get("metrics", {})
            extra = ""
            if component == "technical":
                parts = []
                if "adx" in metrics:
                    parts.append(f"ADX:{metrics['adx']}")
                if "vol_ratio" in metrics:
                    parts.append(f"Vol:{metrics['vol_ratio']:.1f}x")
                if "oi_chg" in metrics:
                    oi_val = metrics['oi_chg']
                    parts.append(f"OI:{oi_val:+d}")
                mtf = comp.get("mtf", {})
                if mtf.get("status") == "confirmed":
                    parts.append(f"MTF:✓")
                elif mtf.get("status") == "caution":
                    parts.append(f"MTF:⚠")
                if parts:
                    extra = "  " + " ".join(parts)
            lines.append(
                f"    {component.capitalize():12s}  {arrow} {sig:12s}  "
                f"(score: {score:+.0f}){extra}"
            )

            details = comp.get("details", [])
            mtf_lines = [d for d in details if d.startswith("MTF")]
            other_details = [d for d in details if not d.startswith("MTF")]
            for detail in other_details[:3]:
                lines.append(f"              {detail}")
            for mtf in mtf_lines:
                lines.append(f"              {mtf}")

        combined = res.get("combined", {})
        final_sig = combined.get("signal", "NEUTRAL")
        final_score = combined.get("score", 0)

        lines.append("")
        arrow_big = "🟢" if final_sig == "STRONG_BUY" else "▲" if final_sig == "BUY" else "🔴" if final_sig == "STRONG_SELL" else "▼" if final_sig == "SELL" else "⚪"
        lines.append(f"    >>> COMBINED: {arrow_big} {final_sig:12s}  (score: {final_score:+.0f})")

        if res.get("headlines"):
            lines.append("")
            lines.append("    Top headlines:")
            for h in res["headlines"][:2]:
                lines.append(f"      · {h[:80]}")

    lines.append("")
    lines.append("=" * 54)
    lines.append("  DISCLAIMER: This is for informational purposes only.")
    lines.append("  Not financial advice. Trade at your own risk.")
    lines.append("=" * 54)

    return "\n".join(lines)


def send_telegram(message: str) -> bool:
    token = TELEGRAM.get("bot_token", "")
    chat_id = TELEGRAM.get("chat_id", "")

    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    MAX_TELEGRAM = 4096
    chunks = []
    while len(message) > MAX_TELEGRAM:
        split_at = message.rfind("\n", 0, MAX_TELEGRAM)
        if split_at < MAX_TELEGRAM // 2:
            split_at = MAX_TELEGRAM
        chunks.append(message[:split_at])
        message = message[split_at:].lstrip("\n")
    if message:
        chunks.append(message)

    for i, chunk in enumerate(chunks):
        payload = {"chat_id": chat_id, "text": chunk}
        if len(chunks) > 1:
            payload["text"] = f"[{i+1}/{len(chunks)}] {chunk}"

        for parse_mode in ("Markdown", None):
            try:
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                else:
                    payload.pop("parse_mode", None)

                resp = requests.post(url, json=payload, timeout=15)
                if resp.status_code == 200:
                    break
                logger.warning("Telegram API error (parse_mode=%s): %s", parse_mode, resp.text)
            except Exception as e:
                logger.warning("Telegram request failed (parse_mode=%s): %s", parse_mode, e)
        else:
            return False

    return True


def send_alert(
    results: Dict[str, Dict[str, Any]],
    usd_inr: Optional[float] = None,
) -> str:
    report = generate_report(results, usd_inr)

    sent = send_telegram(report)
    if sent:
        report += "\n\n✓ Sent via Telegram"
    else:
        report += "\n\n✗ Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID"

    return report
