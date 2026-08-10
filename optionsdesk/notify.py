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

    live = [a for a in analyses if not a.get("degraded")]
    dead = [a for a in analyses if a.get("degraded")]
    if not live:
        msg = [f"<b>⚠️ Options Desk — {_esc(date)}</b>", "",
               "<b>No report today — the data is not usable.</b>", ""]
        for a in dead:
            msg.append(f"<b>{_esc(a['symbol'])}</b>")
            for pr in (a.get("data_quality") or {}).get("problems") or []:
                msg.append(f"• {_esc(pr)}")
            msg.append("")
        msg.append("<i>Open interest is published by OCC before the open. Before "
                   "that the provider returns zeros and every positioning metric "
                   "would be meaningless.</i>")
        return "\n".join(msg)

    out = [f"<b>📈 Options Desk — {_esc(date)}</b>", f"<i>source: {_esc(src)}</i>", ""]
    if dead:
        out.append(f"⚠️ <i>data unusable for "
                   f"{_esc(', '.join(a['symbol'] for a in dead))} — omitted.</i>")
        out.append("")

    for a in live:
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


def format_strategies_en(strategies: dict, per_symbol: int = 2) -> str:
    """English mirror of format_strategies_he. Same rule: only structures with
    genuinely positive expectancy after costs are proposed."""
    from .management import plan_for, has_bounded_max_profit

    out = ["━" * 20, "<b>🎯 Structure candidates</b>", ""]
    any_found = False
    for sym, scan in strategies.items():
        c = scan.get("candidates")
        if c is None or len(c) == 0 or "ev_empirical" not in c:
            continue
        good = c[c["ev_empirical"] > 0]
        if not len(good):
            continue
        any_found = True
        for _, row in good.head(per_symbol).iterrows():
            p = plan_for(row.to_dict(), scan.get("spot", float("nan")))
            cost = float(row["cost"])
            out.append(f"<b>{_esc(sym)} — {_esc(row['name'])}</b>")
            out.append(f"  expiry {_esc(row['expiry'])} ({_n(row['dte'], 0)}d)")
            out.append(f"  {'credit' if cost < 0 else 'debit'} ${_n(abs(cost), 0)}"
                       f" · slippage ${_n(row.get('slippage', 0), 0)}")
            profit_txt = (f"${_n(row['max_profit'], 0)}"
                         if has_bounded_max_profit(row['name'])
                         else "unbounded (theoretical)")
            out.append(f"  max profit {profit_txt} · "
                       f"max loss ${_n(abs(row['max_loss']), 0)}")
            out.append(f"  EV ${_sn(row['ev_empirical'], 2)} · "
                       f"POP {_n(float(row['pop_empirical'])*100, 0)}%")
            th, ve, de = row.get("theta_dollars_per_day"), row.get("vega_dollars"), row.get("delta_shares")
            if th is not None and th == th:
                out.append(f"  greeks: theta ${_sn(th, 1)}/day · "
                           f"vega ${_sn(ve, 1) if ve==ve else 'n/a'} · "
                           f"delta {_sn(de, 1) if de==de else 'n/a'}")
            out.append(f"  target: {_esc(p.target)}")
            out.append(f"  stop: {_esc(p.stop)}")
            out.append(f"  time: {_esc(p.time_exit)}")
            out.append(f"  adjust: {_esc(p.adjustment)}")
            for note in p.notes:
                out.append(f"  ⚠️ <i>{_esc(note)}</i>")
            out.append("")

    if not any_found:
        out.append("<b>Nothing clears the cost test today.</b>")
        out.append("<i>That is the most common correct answer in liquid options, "
                   "not a failure of the scan.</i>")
        out.append("")
    return "\n".join(out)


def send_report(analyses: list[dict], artifact_url: str | None = None,
                strategies: dict | None = None,
                cfg: TelegramConfig | None = None) -> bool:
    text = format_report(analyses, artifact_url)
    if strategies:
        text += "\n\n" + format_strategies_en(strategies)
    return send(text, cfg)


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


# ======================================================================
# Hebrew rendering
# ======================================================================
#
# Telegram renders bidirectional text correctly only if the numeric and Latin
# runs are isolated. Without isolates a line like "flip 709.65 (+1.85%)" inside
# a Hebrew sentence reorders on screen and the minus sign can end up attached to
# the wrong number -- which in a trading message is not cosmetic.

RLM = "‏"          # right-to-left mark: pins a line as RTL
LRI, PDI = "⁦", "⁩"   # isolate a left-to-right run inside RTL text


def _lt(s) -> str:
    """Isolate a Latin/numeric run so bidi cannot reorder it."""
    return f"{LRI}{s}{PDI}"


REGIME_HE = {
    "Pinned / vol-suppressed": "מרותק — תנודתיות מדוכאת",
    "Pinned but underpriced": "מרותק אך מתומחר בחסר",
    "Stressed / trend-amplifying": "לחוץ — מגביר מגמה",
    "Unstable": "לא יציב",
    "Mixed": "מעורב",
}


def format_report_he(analyses: list[dict], artifact_url: str | None = None,
                     strategies: dict | None = None,
                     desk_status: dict | None = None,
                     upcoming_events: list | None = None) -> str:
    """The daily digest in Hebrew, with concrete structures and a plan."""
    if not analyses:
        return f"{RLM}<b>שולחן האופציות</b>\nלא התקבל דוח לאף נכס."

    date = str(analyses[0].get("asof", ""))[:10]

    # Refuse to render a positioning report over empty inputs. Every headline
    # number here -- GEX, the flip, max pain, the walls -- comes from open
    # interest, so with none of it the report is not "approximate", it is
    # fiction with a timestamp. Say that instead.
    live = [a for a in analyses if not a.get("degraded")]
    dead = [a for a in analyses if a.get("degraded")]

    if not live:
        msg = [f"{RLM}<b>⚠️ שולחן האופציות — {_lt(date)}</b>", "",
               f"{RLM}<b>אין דוח היום — הנתונים אינם תקינים.</b>", ""]
        for a in dead:
            probs = (a.get("data_quality") or {}).get("problems") or []
            msg.append(f"{RLM}<b>{_lt(_esc(a['symbol']))}</b>")
            for pr in probs:
                msg.append(f"{RLM}• {_esc(pr)}")
            msg.append("")
        msg.append(f"{RLM}<i>ריבית פתוחה מתפרסמת ע\"י OCC לפני הפתיחה. לפני כן "
                   f"הספק מחזיר אפסים, וכל מדדי המיצוב היו יוצאים חסרי משמעות. "
                   f"עדיף לא לשלוח דוח מאשר לשלוח דוח שגוי.</i>")
        return "\n".join(msg)

    out = [f"{RLM}<b>📈 שולחן האופציות — {_lt(date)}</b>", ""]
    if dead:
        out.append(f"{RLM}⚠️ <i>נתונים חסרים עבור "
                   f"{_lt(', '.join(a['symbol'] for a in dead))} — הושמט.</i>")
        out.append("")

    if upcoming_events:
        out.append(f"{RLM}<b>🗓️ אירועים השבוע:</b>")
        for e in upcoming_events:
            icon = "🔴" if e.impact == "high" else "🟡"
            out.append(f"{RLM}{icon} {_lt(e.date.strftime('%a %d/%m'))} "
                       f"{_lt(e.time_et)} ET — {e.kind}: {_esc(e.label)}")
        out.append("")

    for a in live:
        gex, vol, read = a.get("gex", {}), a.get("vol", {}), a.get("read", {})
        flip, dist = gex.get("flip_level"), gex.get("spot_vs_flip_pct")
        vrp = (vol.get("vrp") or {}).get("vrp")

        out.append(f"{RLM}<b>{_lt(_esc(a['symbol']))}  {_lt(_n(a.get('spot')))}</b>")
        out.append(f"{RLM}{_esc(REGIME_HE.get(read.get('regime'), read.get('regime', '?')))}")

        long_g = gex.get("regime") == "long_gamma"
        out.append(f"{RLM}גאמה: {'לונג' if long_g else '<b>שורט</b>'} · "
                   f"נטו {_lt('$' + _n(gex.get('total'), 0))} לכל 1%")

        if flip is not None and math.isfinite(float(flip or float("nan"))):
            near = abs(float(dist)) < 1.0 if dist is not None else False
            out.append(f"{RLM}רמת היפוך: {_lt(_n(flip))} "
                       f"({_lt(_sn(dist) + '%')}){'  ⚠️ קרוב' if near else ''}")

        iv30, rv20 = vol.get("iv30"), vol.get("rv20")
        if iv30 and rv20:
            warn = "  ⚠️" if (vrp is not None and vrp < 0) else ""
            out.append(f"{RLM}תנודתיות: גלומה {_lt(_n(float(iv30)*100, 1) + '%')} מול "
                       f"ממומשת {_lt(_n(float(rv20)*100, 1) + '%')} · "
                       f"פרמיה {_lt(_sn((vrp or 0)*100, 1))}{warn}")
            if vrp is not None and vrp < 0:
                out.append(f"{RLM}<i>הממומשת גבוהה מהגלומה — לא משלמים לך למכור פרמיה.</i>")

        exps = a.get("expiries") or []
        if exps:
            e = exps[0]
            em = (e.get("expected_move") or {}).get("sigma_pct")
            out.append(f"{RLM}פקיעה {_lt(_esc(e['expiry']))} "
                       f"({_lt(_n(e.get('dte'), 0))} ימים): "
                       f"כאב מקסימלי {_lt(_n(e.get('max_pain'), 1))} "
                       f"({_lt(_sn(e.get('max_pain_dist_pct'), 1) + '%')}) · "
                       f"תנועה צפויה {_lt('±' + _n(em, 2) + '%')}")
        out.append("")

    # Desk status (the tracked daily/weekly recommendations) is the primary,
    # actionable content, so it renders before the broader multi-expiry
    # candidate list, which is context rather than a second set of instructions.
    if desk_status:
        out.append(format_desk_status_he(desk_status))
    if strategies:
        out.append(format_strategies_he(strategies))

    if artifact_url:
        out.append(f'{RLM}<a href="{_esc(artifact_url)}">הדוח המלא ←</a>')
    out.append(f"{RLM}<i>קריאת מיצוב, לא תחזית. אין באמור ייעוץ השקעות.</i>")
    return "\n".join(out)


def _render_legs_he(legs: list) -> list[str]:
    """One line per leg, execution-ticket style: action, right, strike, and
    the price at the side of the market you would actually cross -- the ask
    to buy, the bid to sell, matching price_structure()'s own convention
    rather than showing mid (which nobody can actually transact at).

    Buys are listed before sells (qty descending), which is also the natural
    reading order for a credit spread: "buy the protection, sell the credit".
    """
    ordered = sorted(legs, key=lambda l: -l["qty"])
    lines = []
    for i, l in enumerate(ordered, 1):
        qty = l["qty"]
        action = "קנייה" if qty > 0 else "מכירה"
        mult = f" ×{abs(qty)}" if abs(qty) != 1 else ""

        if l["right"] == "S":
            lines.append(f"{RLM}  {i}. {action} — 100 מניות במחיר השוק{mult}")
            continue

        right_he = "קול" if l["right"] == "C" else "פוט"
        strike = _lt(_n(l["strike"], 2))
        bid, ask, mid = l.get("bid"), l.get("ask"), l.get("mid")
        px = (ask if qty > 0 else bid)
        px = px if px is not None else mid
        price_txt = (f"{_lt('$' + _n(px, 2))} ליחידה ({_lt('$' + _n(px * 100, 0))} לחוזה)"
                    if px is not None else "מחיר לא זמין כרגע")
        lines.append(f"{RLM}  {i}. {action} — {right_he} {strike}{mult} — {price_txt}")
    return lines


def format_strategies_he(strategies: dict, per_symbol: int = 2) -> str:
    """Concrete structures with strikes, cost, P&L and a management plan.

    Only structures with genuinely POSITIVE expectancy after costs are
    proposed. A positive `edge` alone means a structure is priced better than
    the market's own measure implies -- it does not mean the trade makes money,
    and presenting one as a suggestion would be exactly the confusion this
    project exists to avoid.
    """
    from .management import has_bounded_max_profit, plan_he

    out = [f"{RLM}━━━━━━━━━━━━━━━━━━━━", f"{RLM}<b>🎯 הצעות מבנה</b>", ""]
    any_found = False

    for sym, scan in strategies.items():
        c = scan.get("candidates")
        if c is None or len(c) == 0 or "ev_empirical" not in c:
            continue
        good = c[c["ev_empirical"] > 0]
        if not len(good):
            continue
        any_found = True
        spot = scan.get("spot", float("nan"))

        for _, row in good.head(per_symbol).iterrows():
            p = plan_he(row.to_dict(), spot)
            cost = float(row["cost"])
            is_credit = cost < 0

            out.append(f"{RLM}<b>{_lt(_esc(sym))} · {_esc(p['family_he'])}</b>")
            out.append(f"{RLM}פקיעה: {_lt(_esc(row['expiry']))} "
                       f"({_lt(_n(row['dte'], 0))} ימים)")
            out.append(f"{RLM}<b>לביצוע:</b>")
            legs = row.get("_legs")
            if legs:
                out.extend(_render_legs_he(legs))
            else:
                out.append(f"{RLM}  {_lt(_esc(row['name']))}")
            out.append(f"{RLM}נטו: {'קרדיט' if is_credit else 'חיוב'} "
                       f"{_lt('$' + _n(abs(cost), 0))}"
                       f"  ·  עלות מרווח (bid/ask) {_lt('$' + _n(row.get('slippage', 0), 0))}")
            # A long straddle's (and similar families') scanner-reported
            # max_profit is a grid-truncation artifact -- the payoff grows
            # monotonically toward the edge of whatever probability grid was
            # used, with no real interior maximum, unlike a butterfly's or a
            # calendar's. Showing a specific dollar figure there states a
            # technical parameter as if it were a fact about the structure.
            profit_txt = (_lt('$' + _n(row['max_profit'], 0))
                         if has_bounded_max_profit(row['name'])
                         else "בלתי מוגבל (תיאורטית)")
            out.append(f"{RLM}רווח מקסימלי: {profit_txt}"
                       f"  ·  הפסד מקסימלי: {_lt('$' + _n(abs(row['max_loss']), 0))}")
            out.append(f"{RLM}תוחלת: {_lt('$' + _sn(row['ev_empirical'], 2))}"
                       f"  ·  סיכוי לרווח: {_lt(_n(float(row['pop_empirical'])*100, 0) + '%')}")

            # Greeks: what actually generates or erodes the P&L day to day,
            # not just the terminal payoff. Theta on a credit structure is the
            # daily rent you collect; on a debit structure it is what you pay
            # to hold the view. Vega says how much a pure IV move -- with spot
            # unchanged -- helps or hurts.
            th = row.get("theta_dollars_per_day")
            ve = row.get("vega_dollars")
            de = row.get("delta_shares")
            if th is not None and th == th:
                out.append(f"{RLM}יווניות: תטא {_lt('$' + _sn(th, 1))}/יום"
                           f"  ·  וגא {_lt('$' + _sn(ve, 1) if ve==ve else 'n/a')}"
                           f"  ·  דלתא {_lt(_sn(de, 1) if de==de else 'n/a')}")

            out.append(f"{RLM}<b>ניהול:</b>")
            out.append(f"{RLM}• יעד: {_esc(p['target'])}")
            out.append(f"{RLM}• עצירה: {_esc(p['stop'])}")
            out.append(f"{RLM}• זמן: {_esc(p['time_exit'])}")
            out.append(f"{RLM}• תיקון: {_esc(p['adjust'])}")
            if p["warn"]:
                out.append(f"{RLM}⚠️ <i>{_esc(p['warn'])}</i>")
            out.append("")

    if not any_found:
        out.append(f"{RLM}<b>אין מבנה שעובר את מבחן העלויות היום.</b>")
        out.append(f"{RLM}<i>זו התשובה הנפוצה ביותר באופציות נזילות, ולא כישלון "
                   f"של הסריקה. מבנה שנראה טוב לפני המרווח ומפסיד אחריו הוא "
                   f"עסקה גרועה.</i>")
        out.append("")

    return "\n".join(out)


BUCKET_LABEL_HE = {"daily": "אסטרטגיה יומית", "weekly": "אסטרטגיה עד סופ\"ש"}


def _event_line_he(event_risk: dict | None) -> str | None:
    if not event_risk or not event_risk.get("events"):
        return None
    tags = ", ".join(f"{e.kind} {_lt(e.date.strftime('%d/%m'))}" for e in event_risk["events"])
    icon = "🔴" if event_risk["has_high_impact"] else "🟡"
    return f"{RLM}{icon} <i>אירוע מאקרו בטווח הפקיעה: {tags}</i>"


def format_desk_status_he(status_by_symbol: dict) -> str:
    """The daily + weekly bucket status per symbol: a fresh recommendation,
    or a mark-to-market update on the one already tracked, with a management
    verdict -- exactly the "is it still on track, does it need fixing"
    question a desk asks every morning, plus whatever moved since the market
    started trading.
    """
    from .management import plan_he

    out = [f"{RLM}━━━━━━━━━━━━━━━━━━━━", f"{RLM}<b>📋 מעקב אסטרטגיות</b>", ""]

    for sym, buckets in status_by_symbol.items():
        for bucket in ("daily", "weekly"):
            info = buckets.get(bucket)
            if info is None:
                continue
            label = BUCKET_LABEL_HE[bucket]
            out.append(f"{RLM}<b>{_lt(_esc(sym))} · {label}</b>")

            for closed in info.get("just_closed", []):
                p = closed["position"]
                reason = {"target": "הגיע ליעד ✅", "stop": "הגיע לעצירה ⛔",
                         "expired": "פקע"}.get(p.close_reason, p.close_reason)
                out.append(f"{RLM}  נסגר: {_lt(_esc(p.name))} — {reason} "
                           f"(P&L סופי {_lt('$' + _sn(closed['pnl'], 0))})")

            if info["status"] == "existing":
                m = info["mark"]
                p = m["position"]
                out.append(f"{RLM}  {_lt(_esc(p.name))}  ({_lt(_esc(p.expiry))}, "
                           f"נפתח {_lt(_esc(p.opened_at[:10]))})")
                out.append(f"{RLM}  P&L נוכחי: {_lt('$' + _sn(m['pnl'], 0))}"
                           f"  ·  ספוט זז {_lt(_sn(m['spot_move_pct'], 2) + '%')} מהכניסה"
                           f"  ·  {_lt(_n(m['dte_left'], 0))} ימים לפקיעה")
                if m["strike_crossings"]:
                    for c in m["strike_crossings"]:
                        out.append(f"{RLM}  ⚠️ <b>המחיר חצה את הסטרייק {_lt(_n(c['strike'],0))} "
                                   f"({_esc(c['from'])}→{_esc(c['to'])}) — התזה נבחנת</b>")
                if m["hit_target"]:
                    out.append(f"{RLM}  ✅ <b>הגיע ליעד הרווח — מומלץ לסגור</b>")
                elif m["hit_stop"]:
                    out.append(f"{RLM}  ⛔ <b>הגיע לעצירה — מומלץ לסגור, אל תוסיף גודל</b>")
                elif m["strike_crossings"]:
                    plan = plan_he({"name": p.name, "cost": p.entry_cost,
                                    "max_profit": p.max_profit, "max_loss": p.max_loss,
                                    "dte": m["dte_left"]}, m["spot"])
                    out.append(f"{RLM}  תיקון אפשרי: {_esc(plan['adjust'])}")
                else:
                    out.append(f"{RLM}  סטטוס: בתוך התוואי, ללא צורך בפעולה")

            elif info["status"] == "new":
                pos, cand = info["position"], info["candidate"]
                cost = pos.entry_cost
                out.append(f"{RLM}  <b>המלצה חדשה — {_lt(_esc(pos.name))}</b>")
                out.append(f"{RLM}  פקיעה {_lt(_esc(pos.expiry))}")
                out.append(f"{RLM}  <b>לביצוע:</b>")
                if pos.legs:
                    out.extend(_render_legs_he(pos.legs))
                out.append(f"{RLM}  נטו: {'קרדיט' if cost<0 else 'חיוב'} {_lt('$' + _n(abs(cost),0))}")
                out.append(f"{RLM}  יעד {_lt('$' + _n(pos.target_pnl,0))}"
                           f"  ·  עצירה {_lt('$' + _n(abs(pos.stop_pnl),0))}"
                           f"  ·  סיכוי לרווח {_lt(_n(float(cand.get('pop_empirical',0))*100,0)+'%')}")

            else:
                out.append(f"{RLM}  אין מבנה שעובר את מבחן העלויות לפקיעה זו כרגע")

            ev_line = _event_line_he(info.get("event_risk"))
            if ev_line:
                out.append(ev_line)
            out.append("")

    return "\n".join(out)


def send_report_he(analyses: list[dict], artifact_url: str | None = None,
                   strategies: dict | None = None,
                   cfg: TelegramConfig | None = None,
                   desk_status: dict | None = None,
                   upcoming_events: list | None = None) -> bool:
    text = format_report_he(analyses, artifact_url, strategies, desk_status, upcoming_events)
    return send(text, cfg)


# ======================================================================
# Hebrew intraday alerts (watch.py --telegram)
# ======================================================================

ALERT_KIND_HE = {
    "gamma_flip_crossed": "חצייית רמת ההיפוך",
    "at_gamma_flip": "צמוד לרמת ההיפוך",
    "gamma_regime_change": "שינוי משטר גאמה",
    "vrp_sign_change": "היפוך סימן בפרמיית התנודתיות",
    "positive_expectancy": "מבנה עם תוחלת חיובית",
    "opportunity_gone": "ההזדמנות נעלמה",
    "term_structure_inverted": "היפוך במבנה העתי",
    "fit_quality": "כיסוי חלקי של המשטח",
    "scan_failed": "הסריקה נכשלה",
    "position_stop": "פוזיציה הגיעה לעצירה",
    "position_target": "פוזיציה הגיעה ליעד",
    "position_expired": "פוזיציה פקעה",
    "strike_crossed": "חצייית סטרייק",
    "new_recommendation": "המלצה חדשה",
}

_IMPLICATION_HE = {
    # Keyed on crossed_down: True means spot just fell below the flip.
    ("gamma_flip_crossed", True): (
        "הגידור של הסוחרים עכשיו <b>מגביר</b> תנועות: קונים בעליות, מוכרים בירידות. "
        "צפו לטווח רחב יותר וסיכון פערים גבוה יותר; להקטין גודל במכירת פרמיה."),
    ("gamma_flip_crossed", False): (
        "הגידור של הסוחרים עכשיו <b>מדכא</b> תנועות: מוכרים בעליות, קונים בירידות. "
        "הטווח אמור להחזיק טוב יותר, וסטרייקים גדולים הופכים למגנטים."),
}


def _alert_message_he(d: dict) -> str:
    """Rebuild the alert message in Hebrew from its structured detail dict
    rather than translating the English sentence -- the numbers and their
    meaning are what matter, and they are already sitting in `detail`."""
    kind, det = d["kind"], d.get("detail") or {}
    sym = d["symbol"]

    if kind == "gamma_flip_crossed":
        crossed_down = det.get("to_pct", 0) < 0
        where = "מתחת לרמת" if crossed_down else "מעל רמת"
        return (f"הספוט חצה {where} ההיפוך "
               f"ב-{_lt(_n(det.get('flip')))} (עכשיו {_lt(_sn(det.get('to_pct')) + '%')})")
    if kind == "at_gamma_flip":
        return (f"הספוט במרחק {_lt(_sn(det.get('distance_pct')) + '%')} בלבד מרמת ההיפוך "
               f"({_lt(_n(det.get('flip')))}) — המשטר יכול להתהפך בתנודה רגילה")
    if kind == "gamma_regime_change":
        return f"הגאמה הנטו התהפכה: {_esc(det.get('from'))} ← {_esc(det.get('to'))}"
    if kind == "vrp_sign_change":
        neg = det.get("vrp", 0) < 0
        return (f"פרמיית התנודתיות עברה ל{'שלילי' if neg else 'חיובי'} "
               f"({_lt(_sn((det.get('vrp') or 0)*100, 1))} נק')")
    if kind == "positive_expectancy":
        best = det.get("best", {})
        return (f"{det.get('count')} מבנה/ים עוברים את מבחן העלויות ({_esc(det.get('reason'))}); "
               f"הטוב ביותר: {_lt(_esc(best.get('name','')))} {_lt(_esc(best.get('expiry','')))} "
               f"תוחלת {_lt('$' + _sn(best.get('ev_empirical'), 2))}")
    if kind == "opportunity_gone":
        return f"ה-{det.get('was')} מבנה/ים שעברו את מבחן העלויות כבר לא עוברים"
    if kind == "term_structure_inverted":
        return "התנודתיות הקרובה יקרה מהרחוקה — סימן ללחץ בשוק"
    if kind == "fit_quality":
        return f"{len(det.get('rejected', {}))} פקיעות לא הותאמו — כיסוי המשטח חלקי"
    if kind == "scan_failed":
        return f"הסריקה נכשלה: {_esc(d.get('message',''))}"
    if kind in ("position_stop", "position_target", "position_expired"):
        verb = {"position_stop": "הגיעה לעצירה", "position_target": "הגיעה ליעד",
               "position_expired": "פקעה"}[kind]
        bucket = "יומית" if det.get("bucket") == "daily" else "שבועית"
        return f"פוזיציה {bucket} {verb} — P&L {_lt('$' + _sn(det.get('pnl'), 0))}"
    if kind == "strike_crossed":
        bucket = "יומית" if det.get("bucket") == "daily" else "שבועית"
        return (f"פוזיציה {bucket}: המחיר חצה את הסטרייק {_lt(_n(det.get('strike'), 0))} "
               f"— התזה נבחנת")
    if kind == "new_recommendation":
        bucket = "יומית" if det.get("bucket") == "daily" else "שבועית"
        return f"הצעה {bucket} חדשה נרשמה למעקב"
    return _esc(d.get("message", ""))          # unmapped kind: fall back rather than drop it


def format_alerts_he(alerts: list) -> str:
    """Hebrew mirror of format_alerts, used by watch.py --telegram."""
    if not alerts:
        return ""
    icon = {"critical": "🔴", "warning": "🟠", "info": "🔵"}
    out = [f"{RLM}<b>שולחן האופציות — {len(alerts)} התראות</b>", ""]
    for a in alerts:
        d = a.to_dict() if hasattr(a, "to_dict") else dict(a)
        label = ALERT_KIND_HE.get(d["kind"], d["kind"])
        out.append(f"{RLM}{icon.get(d['severity'], '•')} <b>{_lt(_esc(d['symbol']))}</b> "
                   f"— {_esc(label)}")
        out.append(f"{RLM}   {_alert_message_he(d)}")
        # crossed_down must match the SAME test _alert_message_he used above,
        # or the implication text ends up describing the opposite crossing.
        key = (d["kind"], (d.get("detail") or {}).get("to_pct", 0) < 0) \
            if d["kind"] == "gamma_flip_crossed" else None
        imp_he = _IMPLICATION_HE.get(key)
        if imp_he:
            out.append(f"{RLM}   <i>{imp_he}</i>")
        out.append("")
    return "\n".join(out)


def send_alerts_he(alerts: list, cfg: TelegramConfig | None = None) -> bool:
    if not alerts:
        return False
    critical = any((a.to_dict() if hasattr(a, "to_dict") else a)["severity"] == "critical"
                   for a in alerts)
    return send(format_alerts_he(alerts), cfg, silent=not critical)
