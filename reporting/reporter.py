import requests
from typing import Dict, Any, Optional
from datetime import datetime
from textwrap import dedent

from config import TELEGRAM, COMMODITIES, WEIGHTS


def generate_report(
    results: Dict[str, Dict[str, Any]],
    usd_inr: Optional[float] = None,
) -> str:
    lines = []
    now = datetime.now().strftime("%d %b %Y %H:%M")

    lines.append("=" * 54)
    lines.append(f"  INDIAN COMMODITY MARKET REPORT")
    lines.append(f"  {now}")
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
        lines.append(f"  {cfg.name.upper()} (${res.get('price', '?')})")
        lines.append(f"{'─' * 54}")

        for component in ["technical", "sentiment", "fundamental"]:
            comp = res.get(component, {})
            sig = comp.get("signal", "N/A")
            score = comp.get("score", 0)
            direction = comp.get("direction", 0)

            arrow = "▲" if direction > 0 else "▼" if direction < 0 else "◆"
            lines.append(
                f"    {component.capitalize():12s}  {arrow} {sig:12s}  "
                f"(score: {score:+.0f})"
            )

            for detail in comp.get("details", [])[:2]:
                lines.append(f"              {detail}")

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

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        # Telegram has 4096 char limit, chunk if needed
        if len(message) > 4000:
            message = message[:2000] + "\n\n... (truncated)"

        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=15,
        )
        return resp.status_code == 200
    except Exception:
        return False


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
