"""Telegram delivery for the daily report and intraday alerts.

CREDENTIALS NEVER LIVE IN THIS REPOSITORY. It is public. The bot token and chat
id are read from `~/.config/options-desk/.env` (mode 0600) or from the
environment, and nothing here ever writes them to stdout, to a log, or to a
committed file. `scripts/setup_telegram.py` creates that file interactively so
the token is typed into your own terminal rather than pasted into a chat.

Messages are formatted for a phone: the regime and the number that matters
first, detail after, no tables. A daily report you have to pinch-zoom is a
daily report you stop reading.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

__all__ = ["TelegramConfig", "load_config", "send", "send_report", "send_alerts"]

CONFIG_PATH = Path.home() / ".config" / "options-desk" / ".env"
API = "https://api.telegram.org/bot{token}/{method}"
# Telegram hard-limits a message at 4096 characters.
MAX_LEN = 4000


class TelegramConfig:
    __slots__ = ("token", "chat_id")

    def __init__(self, token: str, chat_id: str):
        self.token, self.chat_id = token, chat_id

    def __repr__(self):                    # never leak the token in a traceback
        tail = self.token[-4:] if self.token else "?"
        return f"TelegramConfig(token=...{tail}, chat_id={self.chat_id})"


def load_config(path: Path | None = None) -> TelegramConfig | None:
    """Environment first, then the config file. None when not set up."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")

    path = Path(path) if path else CONFIG_PATH
    if (not token or not chat) and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            v = v.strip().strip('"').strip("'")
            if k.strip() == "TELEGRAM_BOT_TOKEN" and not token:
                token = v
            elif k.strip() == "TELEGRAM_CHAT_ID" and not chat:
                chat = v

    return TelegramConfig(token, chat) if token and chat else None


def _post(cfg: TelegramConfig, method: str, payload: dict) -> dict:
    data = urllib.parse.urlencode(payload).encode()
    req = urllib.request.Request(API.format(token=cfg.token, method=method), data=data)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        # Strip the token if the API ever echoes the URL back in an error.
        raise RuntimeError(f"telegram {method} failed: {e.code} "
                           f"{body.replace(cfg.token, '<token>')}") from None


def send(text: str, cfg: TelegramConfig | None = None, silent: bool = False) -> bool:
    """Send one message, splitting if it exceeds Telegram's limit."""
    cfg = cfg or load_config()
    if cfg is None:
        return False

    chunks, cur = [], ""
    for para in text.split("\n\n"):
        if len(cur) + len(para) + 2 > MAX_LEN:
            if cur:
                chunks.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        chunks.append(cur)

    for chunk in chunks:
        _post(cfg, "sendMessage", {
            "chat_id": cfg.chat_id, "text": chunk, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
            "disable_notification": "true" if silent else "false",
        })
    return True


def _esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _sn(x, nd=2, default="n/a"):
    """Signed: a distance from the flip is meaningless without its direction."""
    try:
        v = float(x)
        return f"{v:+,.{nd}f}" if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _n(x, nd=2, default="n/a"):
    try:
        v = float(x)
        return f"{v:,.{nd}f}" if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def format_report(analyses: list[dict], artifact_url: str | None = None) -> str:
    """The daily digest, written to be read on a phone."""
    if not analyses:
        return "<b>Options Desk</b>\nNo symbol produced a report."

    date = str(analyses[0].get("asof", ""))[:10]
    src = analyses[0].get("source", "?")
    out = [f"<b>📈 Options Desk — {_esc(date)}</b>", f"<i>source: {_esc(src)}</i>", ""]

    for a in analyses:
        gex, vol, read = a.get("gex", {}), a.get("vol", {}), a.get("read", {})
        flip = gex.get("flip_level")
        dist = gex.get("spot_vs_flip_pct")
        vrp = (vol.get("vrp") or {}).get("vrp")

        out.append(f"<b>{_esc(a['symbol'])}  {_n(a.get('spot'))}</b>")
        out.append(f"  {_esc(read.get('regime', '?'))}")

        regime_word = "long γ" if gex.get("regime") == "long_gamma" else "SHORT γ"
        out.append(f"  {regime_word} · net GEX ${_n(gex.get('total'), 0)}/1%")

        if flip is not None and math.isfinite(float(flip or float('nan'))):
            near = abs(float(dist)) < 1.0 if dist is not None else False
            out.append(f"  flip {_n(flip)} ({_sn(dist)}%){'  ⚠️ close' if near else ''}")

        iv30, rv20 = vol.get("iv30"), vol.get("rv20")
        if iv30 and rv20:
            warn = "  ⚠️" if (vrp is not None and vrp < 0) else ""
            out.append(f"  IV30 {_n(float(iv30)*100, 1)}% vs RV20 {_n(float(rv20)*100, 1)}%"
                       f" · VRP {_sn((vrp or 0)*100, 1)}{warn}")

        exps = a.get("expiries") or []
        if exps:
            e = exps[0]
            em = (e.get("expected_move") or {}).get("sigma_pct")
            out.append(f"  {_esc(e['expiry'])} ({_n(e.get('dte'), 0)}d): "
                       f"max pain {_n(e.get('max_pain'), 1)} "
                       f"({_sn(e.get('max_pain_dist_pct'), 1)}%) · EM ±{_n(em, 2)}%")
        out.append("")

    summary = (analyses[0].get("read") or {}).get("summary")
    if summary:
        out.append(f"<i>{_esc(summary)}</i>")
        out.append("")

    if artifact_url:
        out.append(f'<a href="{_esc(artifact_url)}">Full dashboard →</a>')
    out.append("<i>Positioning read, not a forecast. Not financial advice.</i>")
    return "\n".join(out)


def format_alerts(alerts: list) -> str:
    """Intraday alerts. Only called when something actually fired."""
    if not alerts:
        return ""
    icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
    out = [f"<b>Options Desk — {len(alerts)} alert(s)</b>", ""]
    for a in alerts:
        d = a.to_dict() if hasattr(a, "to_dict") else dict(a)
        out.append(f"{icon.get(d['severity'], '•')} <b>{_esc(d['symbol'])}</b> "
                   f"{_esc(d['kind'])}")
        out.append(f"   {_esc(d['message'])}")
        imp = (d.get("detail") or {}).get("implication")
        if imp:
            out.append(f"   <i>{_esc(imp)}</i>")
        out.append("")
    return "\n".join(out)


def send_report(analyses: list[dict], artifact_url: str | None = None,
                cfg: TelegramConfig | None = None) -> bool:
    return send(format_report(analyses, artifact_url), cfg)


def send_alerts(alerts: list, cfg: TelegramConfig | None = None) -> bool:
    if not alerts:
        return False
    critical = any((a.to_dict() if hasattr(a, "to_dict") else a)["severity"] == "critical"
                   for a in alerts)
    return send(format_alerts(alerts), cfg, silent=not critical)


def verify(cfg: TelegramConfig | None = None) -> dict:
    """Confirm the token works and return the bot identity."""
    cfg = cfg or load_config()
    if cfg is None:
        raise RuntimeError("no Telegram config -- run scripts/setup_telegram.py")
    return _post(cfg, "getMe", {}).get("result", {})
