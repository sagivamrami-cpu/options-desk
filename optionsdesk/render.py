"""Render an analysis dict into a self-contained HTML dashboard.

Design intent: this is an instrument panel, not an essay. It is scanned in two
minutes before the open. The regime verdict reads first, the numbers that
support it read second, and the chart that would change your mind reads third.

No external assets -- charts are hand-built inline SVG so the page works under
a strict CSP and in both light and dark themes.
"""

from __future__ import annotations

import datetime as _dt
import html
import math

__all__ = ["render_dashboard"]


# ======================================================================
# small helpers
# ======================================================================

def _f(v, digits=2, dash="—"):
    if v is None:
        return dash
    try:
        v = float(v)
    except (TypeError, ValueError):
        return dash
    return dash if not math.isfinite(v) else f"{v:,.{digits}f}"


def _pct(v, digits=1, dash="—", signed=False):
    if v is None:
        return dash
    try:
        v = float(v)
    except (TypeError, ValueError):
        return dash
    if not math.isfinite(v):
        return dash
    return f"{v:+.{digits}f}%" if signed else f"{v:.{digits}f}%"


def _usd_compact(v, dash="—"):
    """$2.05B / $480M / $12.4K -- magnitudes matter more than digits here."""
    if v is None:
        return dash
    try:
        v = float(v)
    except (TypeError, ValueError):
        return dash
    if not math.isfinite(v):
        return dash
    sign = "-" if v < 0 else ""
    a = abs(v)
    for cut, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= cut:
            return f"{sign}${a / cut:.2f}{suf}"
    return f"{sign}${a:.0f}"


def _e(s):
    return html.escape(str(s), quote=True)


# ======================================================================
# charts
# ======================================================================

def _gex_chart(analysis: dict, window: float = 0.08) -> str:
    """Horizontal GEX-by-strike bars with spot and flip markers.

    The single most decision-relevant picture in the report: it shows where the
    hedging walls are and which side of the flip price is sitting on.
    """
    spot = analysis["spot"]
    flip = analysis["gex"]["flip_level"]
    rows = [
        r for r in analysis["gex"]["profile"]
        if r.get("strike") is not None
        and abs(float(r["strike"]) - spot) <= spot * window
        and r.get("gex") is not None and math.isfinite(float(r["gex"]))
    ]
    if not rows:
        return '<p class="empty">No gamma profile available for this window.</p>'

    rows.sort(key=lambda r: float(r["strike"]), reverse=True)
    peak = max(abs(float(r["gex"])) for r in rows) or 1.0

    row_h, gap = 15, 2
    pad_top, pad_bot, label_w = 22, 26, 62
    plot_w = 420
    h = pad_top + len(rows) * (row_h + gap) + pad_bot
    w = label_w + plot_w + 14
    mid = label_w + plot_w / 2.0

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" '
        f'aria-label="Gamma exposure by strike around spot {spot:.2f}">'
    ]
    # zero axis
    parts.append(
        f'<line x1="{mid:.1f}" y1="{pad_top - 8}" x2="{mid:.1f}" y2="{h - pad_bot + 4}" '
        f'class="axis-zero" />'
    )

    def y_of(strike):
        for i, r in enumerate(rows):
            if float(r["strike"]) == strike:
                return pad_top + i * (row_h + gap) + row_h / 2.0
        return None

    for i, r in enumerate(rows):
        k = float(r["strike"])
        g = float(r["gex"])
        y = pad_top + i * (row_h + gap)
        bar = (abs(g) / peak) * (plot_w / 2.0 - 6)
        x = mid if g >= 0 else mid - bar
        cls = "bar-pos" if g >= 0 else "bar-neg"
        near = ' bar-near' if abs(k - spot) <= spot * 0.006 else ''
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bar, 0.6):.1f}" height="{row_h}" '
            f'class="{cls}{near}" rx="1"><title>{k:,.2f}: {_usd_compact(g)} per 1%</title></rect>'
        )
        parts.append(
            f'<text x="{label_w - 8}" y="{y + row_h - 3.5:.1f}" text-anchor="end" '
            f'class="tick">{k:,.0f}</text>'
        )

    # spot marker
    ys = y_of(min((float(r["strike"]) for r in rows), key=lambda k: abs(k - spot)))
    if ys is not None:
        parts.append(
            f'<line x1="{label_w - 4}" y1="{ys:.1f}" x2="{label_w + plot_w:.1f}" y2="{ys:.1f}" '
            f'class="marker-spot" /><text x="{label_w + plot_w:.1f}" y="{ys - 4:.1f}" '
            f'text-anchor="end" class="marker-label">SPOT {spot:,.2f}</text>'
        )

    # flip marker
    if flip is not None and math.isfinite(float(flip)):
        flip = float(flip)
        strikes = [float(r["strike"]) for r in rows]
        if min(strikes) <= flip <= max(strikes):
            kf = min(strikes, key=lambda k: abs(k - flip))
            yf = y_of(kf)
            if yf is not None:
                parts.append(
                    f'<line x1="{label_w - 4}" y1="{yf:.1f}" x2="{label_w + plot_w:.1f}" '
                    f'y2="{yf:.1f}" class="marker-flip" />'
                    f'<text x="{label_w + plot_w:.1f}" y="{yf + 11:.1f}" text-anchor="end" '
                    f'class="marker-label flip">γ FLIP {flip:,.2f}</text>'
                )

    parts.append(
        f'<text x="{mid - 10:.1f}" y="{h - 8}" text-anchor="end" class="tick">'
        f'← short gamma</text>'
        f'<text x="{mid + 10:.1f}" y="{h - 8}" text-anchor="start" class="tick">'
        f'long gamma →</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def _term_chart(analysis: dict) -> str:
    """ATM IV against days to expiry. Shape is the message: up = calm,
    down = the market is paying for immediate protection."""
    ts = [t for t in analysis["vol"]["term_structure"]
          if t.get("atm_iv") is not None and math.isfinite(float(t["atm_iv"]))]
    if len(ts) < 2:
        return '<p class="empty">Not enough expiries for a term structure.</p>'

    w, h, pl, pr, pt, pb = 420, 150, 44, 14, 16, 30
    xs = [float(t["dte"]) for t in ts]
    ys = [float(t["atm_iv"]) * 100 for t in ts]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    span = max(y1 - y0, 1.0)
    y0, y1 = y0 - span * 0.25, y1 + span * 0.25

    def px(x):
        return pl + (x - x0) / max(x1 - x0, 1e-9) * (w - pl - pr)

    def py(y):
        return h - pb - (y - y0) / max(y1 - y0, 1e-9) * (h - pt - pb)

    pts = [(px(x), py(y)) for x, y in zip(xs, ys)]
    line = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(pts))
    area = (f"M{pts[0][0]:.1f},{h - pb} " +
            " ".join(f"L{x:.1f},{y:.1f}" for x, y in pts) +
            f" L{pts[-1][0]:.1f},{h - pb} Z")

    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="ATM implied volatility term structure">']
    for frac in (0.0, 0.5, 1.0):
        yv = y0 + (y1 - y0) * frac
        parts.append(f'<line x1="{pl}" y1="{py(yv):.1f}" x2="{w - pr}" y2="{py(yv):.1f}" class="grid" />')
        parts.append(f'<text x="{pl - 7}" y="{py(yv) + 3.5:.1f}" text-anchor="end" class="tick">{yv:.0f}%</text>')
    parts.append(f'<path d="{area}" class="term-area" />')
    parts.append(f'<path d="{line}" class="term-line" />')
    for (x, y), t in zip(pts, ts):
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="term-dot">'
            f'<title>{_e(t["expiry"])} · {float(t["dte"]):.0f}d · {float(t["atm_iv"])*100:.1f}%</title></circle>'
        )
    for x, t in zip([p[0] for p in pts], ts):
        parts.append(f'<text x="{x:.1f}" y="{h - 9}" text-anchor="middle" class="tick">{float(t["dte"]):.0f}d</text>')
    parts.append("</svg>")
    return "".join(parts)


# ======================================================================
# blocks
# ======================================================================

def _tile(label, value, sub="", tone="") -> str:
    tone_cls = f" tile-{tone}" if tone else ""
    sub_html = f'<div class="tile-sub">{_e(sub)}</div>' if sub else ""
    return (f'<div class="tile{tone_cls}"><div class="tile-label">{_e(label)}</div>'
            f'<div class="tile-value">{value}</div>{sub_html}</div>')


def _symbol_block(a: dict) -> str:
    read = a["read"]
    gex, vol, flows = a["gex"], a["vol"], a["flows"]
    spot = a["spot"]

    regime_tone = "good" if gex["regime"] == "long_gamma" else "critical"
    vrp = vol["vrp"]["vrp"]
    vrp_tone = "good" if (vrp is not None and math.isfinite(vrp or float("nan")) and vrp > 0) else "warn"

    iv_rank = vol["iv_rank"]
    iv_rank_txt = (_f(iv_rank, 0) if iv_rank is not None
                   else f'<span class="pending">building · {vol["iv_history_days"]}d</span>')

    tiles = "".join([
        _tile("Spot", _f(spot), f"{a['contracts_analyzed']:,} contracts priced"),
        _tile("Net GEX", _usd_compact(gex["total"]), "per 1% move", regime_tone),
        _tile("γ Flip", _f(gex["flip_level"]),
              f"spot {_pct(gex['spot_vs_flip_pct'], 2, signed=True)}",
              "good" if (gex["spot_vs_flip_pct"] or 0) > 0 else "critical"),
        _tile("IV 30d", _pct((vol["iv30"] or 0) * 100 if vol["iv30"] else None),
              f"IV rank {iv_rank_txt}"),
        _tile("RV 20d", _pct((vol["rv20"] or 0) * 100 if vol["rv20"] else None),
              f"{_f(vol['rv_cone']['percentile'], 0)} pctile 1y"),
        _tile("VRP", _pct((vrp or 0) * 100 if vrp is not None else None, 1, signed=True),
              "IV minus RV", vrp_tone),
        _tile("25Δ Skew", _pct((a["skew"]["front"]["skew"] or 0) * 100
                               if a["skew"]["front"]["skew"] is not None else None, 1, signed=True),
              "put over call, front"),
        _tile("P/C OI", _f(flows["put_call"]["oi_ratio"]), "open interest ratio"),
    ])

    signals = "".join(
        f'<tr><td class="sig-factor">{_e(s["factor"])}</td>'
        f'<td class="sig-state mono">{_e(s["state"])}</td>'
        f'<td class="sig-mean">{_e(s["meaning"])}</td>'
        f'<td><span class="pill pill-{_e(s["bias"])}">{_e(s["bias"])}</span></td></tr>'
        for s in read["signals"]
    )

    exp_rows = ""
    for e in a["expiries"]:
        em = e.get("expected_move") or {}
        walls = e.get("walls") or {}
        cw = walls.get("call_walls") or []
        pw = walls.get("put_walls") or []
        exp_rows += (
            f'<tr><td class="mono">{_e(e["expiry"])}</td>'
            f'<td class="mono num">{_f(e["dte"], 0)}</td>'
            f'<td class="mono num">{_pct((e["atm_iv"] or 0) * 100)}</td>'
            f'<td class="mono num">±{_pct(em.get("sigma_pct"))}</td>'
            f'<td class="mono num">{_f(em.get("straddle_price"))}</td>'
            f'<td class="mono num">{_f(e["max_pain"], 0)}'
            f'<span class="delta">{_pct(e["max_pain_dist_pct"], 1, signed=True)}</span></td>'
            f'<td class="mono num">{_f(cw[0]["strike"], 0) if cw else "—"}</td>'
            f'<td class="mono num">{_f(pw[0]["strike"], 0) if pw else "—"}</td>'
            f'<td class="mono num">{_f(e["total_oi"], 0)}</td></tr>'
        )

    warn_html = ""
    if a.get("warnings"):
        items = "".join(f"<li>{_e(w)}</li>" for w in a["warnings"])
        warn_html = f'<div class="warnbox"><span class="warnbox-label">Data notes</span><ul>{items}</ul></div>'

    return f"""
<section class="sym" id="sym-{_e(a['symbol'])}">
  <div class="sym-head">
    <div class="sym-id">
      <h2>{_e(a['symbol'])}</h2>
      <span class="src mono">{_e(a['source'])}</span>
    </div>
    <div class="verdict verdict-{regime_tone}">
      <span class="verdict-label">Regime</span>
      <strong>{_e(read['regime'])}</strong>
      <span class="verdict-tilt">tilt: {_e(read['tilt'])}</span>
    </div>
  </div>

  <p class="summary">{_e(read['summary'])}</p>
  {f'<div class="conflict"><span class="conflict-label">Signals in conflict</span>{_e(read["conflict"])}</div>' if read.get("conflict") else ""}

  <div class="tiles">{tiles}</div>

  <div class="charts">
    <figure>
      <figcaption>Gamma exposure by strike <span>dollars dealers must trade per 1% move</span></figcaption>
      <div class="chart-scroll">{_gex_chart(a)}</div>
    </figure>
    <figure>
      <figcaption>ATM implied vol term structure <span>{'inverted — stress' if vol['inverted'] else 'normal contango'}</span></figcaption>
      <div class="chart-scroll">{_term_chart(a)}</div>
    </figure>
  </div>

  <h3>What the mechanics say</h3>
  <div class="t-scroll">
    <table class="signals">
      <thead><tr><th>Factor</th><th>Reading</th><th>What it means</th><th>Bias</th></tr></thead>
      <tbody>{signals}</tbody>
    </table>
  </div>

  <h3>Expiration map</h3>
  <div class="t-scroll">
    <table class="expiries">
      <thead><tr>
        <th>Expiry</th><th class="num">DTE</th><th class="num">ATM IV</th>
        <th class="num">Exp. move</th><th class="num">Straddle</th><th class="num">Max pain</th>
        <th class="num">Call wall</th><th class="num">Put wall</th><th class="num">Open int.</th>
      </tr></thead>
      <tbody>{exp_rows}</tbody>
    </table>
  </div>

  {warn_html}
</section>"""


# ======================================================================
def render_dashboard(analyses: list[dict], title: str = "Options Desk") -> str:
    stamp = _dt.datetime.now().strftime("%A %d %B %Y · %H:%M")
    blocks = "".join(_symbol_block(a) for a in analyses)
    nav = "".join(
        f'<a href="#sym-{_e(a["symbol"])}"><span class="mono">{_e(a["symbol"])}</span>'
        f'<span class="nav-regime nav-{"good" if a["gex"]["regime"] == "long_gamma" else "critical"}">'
        f'{"long γ" if a["gex"]["regime"] == "long_gamma" else "short γ"}</span></a>'
        for a in analyses
    )
    caveat = analyses[0]["read"]["caveat"] if analyses else ""

    return f"""<title>{_e(title)}</title>
<style>
:root {{
  --bg:#EFF2F6; --panel:#FFFFFF; --panel-2:#E5EAF1; --line:#D3DAE4; --line-soft:#E3E8EF;
  --ink:#101623; --ink-2:#39445B; --muted:#657189;
  --accent:#4B3FA8; --accent-soft:rgba(75,63,168,.10);
  --good:#0B6E5A; --good-bg:rgba(11,110,90,.12);
  --critical:#A8342A; --critical-bg:rgba(168,52,42,.12);
  --warn:#9A6608; --warn-bg:rgba(154,102,8,.13);
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
  --sans:"Inter var","Segoe UI",system-ui,-apple-system,"Helvetica Neue",Arial,sans-serif;
}}
@media (prefers-color-scheme:dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#0C1017; --panel:#141A24; --panel-2:#1C2430; --line:#28323F; --line-soft:#1F2733;
    --ink:#E9EEF6; --ink-2:#BCC6D6; --muted:#8895AB;
    --accent:#9C90F0; --accent-soft:rgba(156,144,240,.14);
    --good:#3FBF9B; --good-bg:rgba(63,191,155,.15);
    --critical:#F0705C; --critical-bg:rgba(240,112,92,.15);
    --warn:#E0A83C; --warn-bg:rgba(224,168,60,.15);
  }}
}}
:root[data-theme="dark"] {{
  --bg:#0C1017; --panel:#141A24; --panel-2:#1C2430; --line:#28323F; --line-soft:#1F2733;
  --ink:#E9EEF6; --ink-2:#BCC6D6; --muted:#8895AB;
  --accent:#9C90F0; --accent-soft:rgba(156,144,240,.14);
  --good:#3FBF9B; --good-bg:rgba(63,191,155,.15);
  --critical:#F0705C; --critical-bg:rgba(240,112,92,.15);
  --warn:#E0A83C; --warn-bg:rgba(224,168,60,.15);
}}
*{{box-sizing:border-box}}
body{{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;
  line-height:1.6;margin:0;padding:0 20px 80px;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:1080px;margin:0 auto}}
.mono{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
a{{color:var(--accent)}}
a:focus-visible{{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}}

header.top{{padding:40px 0 24px;border-bottom:1px solid var(--line);margin-bottom:32px}}
.kicker{{font-family:var(--mono);font-size:11px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--muted);margin-bottom:12px}}
h1{{font-size:clamp(1.7rem,4vw,2.4rem);line-height:1.1;margin:0 0 8px;letter-spacing:-.02em;
  font-weight:700;text-wrap:balance}}
.stamp{{color:var(--muted);font-size:14px;margin:0}}
.nav{{display:flex;gap:8px;flex-wrap:wrap;margin-top:20px}}
.nav a{{display:flex;align-items:center;gap:8px;background:var(--panel);border:1px solid var(--line);
  border-radius:3px;padding:6px 12px;text-decoration:none;color:var(--ink);font-size:13px}}
.nav a:hover{{border-color:var(--accent)}}
.nav-regime{{font-family:var(--mono);font-size:10.5px;padding:1px 6px;border-radius:2px}}
.nav-good{{background:var(--good-bg);color:var(--good)}}
.nav-critical{{background:var(--critical-bg);color:var(--critical)}}

section.sym{{background:var(--panel);border:1px solid var(--line);border-radius:4px;
  padding:26px 26px 30px;margin-bottom:28px;scroll-margin-top:20px}}
.sym-head{{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;
  flex-wrap:wrap;margin-bottom:14px}}
.sym-id{{display:flex;align-items:baseline;gap:12px}}
.sym-id h2{{margin:0;font-size:1.7rem;letter-spacing:-.02em;font-weight:700}}
.src{{font-size:11px;color:var(--muted);background:var(--panel-2);padding:2px 7px;border-radius:2px}}
.verdict{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding:8px 14px;border-radius:3px;
  border-left:3px solid var(--muted);background:var(--panel-2)}}
.verdict-good{{border-left-color:var(--good);background:var(--good-bg)}}
.verdict-critical{{border-left-color:var(--critical);background:var(--critical-bg)}}
.verdict-label{{font-family:var(--mono);font-size:10px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--muted)}}
.verdict strong{{font-size:1rem}}
.verdict-tilt{{font-family:var(--mono);font-size:11.5px;color:var(--muted)}}
.summary{{color:var(--ink-2);max-width:74ch;margin:0 0 16px}}
.conflict{{background:var(--warn-bg);border-left:3px solid var(--warn);padding:11px 15px;
  border-radius:0 3px 3px 0;margin:0 0 22px;font-size:13.5px;color:var(--ink-2);max-width:74ch}}
.conflict-label{{font-family:var(--mono);font-size:10px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--warn);display:block;margin-bottom:4px}}

.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
  background:var(--line);border:1px solid var(--line);border-radius:3px;overflow:hidden;margin-bottom:26px}}
.tile{{background:var(--panel);padding:12px 14px 13px}}
.tile-label{{font-family:var(--mono);font-size:10px;letter-spacing:.11em;text-transform:uppercase;
  color:var(--muted);margin-bottom:5px}}
.tile-value{{font-family:var(--mono);font-size:1.32rem;font-weight:600;letter-spacing:-.01em;
  font-variant-numeric:tabular-nums;line-height:1.2}}
.tile-sub{{font-size:11.5px;color:var(--muted);margin-top:3px}}
.tile-good .tile-value{{color:var(--good)}}
.tile-critical .tile-value{{color:var(--critical)}}
.tile-warn .tile-value{{color:var(--warn)}}
.pending{{color:var(--muted);font-style:italic}}

.charts{{display:grid;grid-template-columns:1fr;gap:22px;margin-bottom:28px}}
@media(min-width:840px){{.charts{{grid-template-columns:1.15fr 1fr;align-items:start}}}}
figure{{margin:0}}
figcaption{{font-size:12.5px;color:var(--ink-2);margin-bottom:10px;font-weight:600;
  display:flex;flex-direction:column;gap:1px}}
figcaption span{{font-weight:400;color:var(--muted);font-size:11.5px}}
.chart-scroll{{overflow-x:auto;background:var(--panel-2);border:1px solid var(--line-soft);
  border-radius:3px;padding:10px}}
.chart-scroll svg{{display:block;width:100%;height:auto;min-width:340px}}
.axis-zero{{stroke:var(--muted);stroke-width:1;opacity:.5}}
.grid{{stroke:var(--line);stroke-width:1}}
.bar-pos{{fill:var(--good);opacity:.82}}
.bar-neg{{fill:var(--critical);opacity:.82}}
.bar-near{{opacity:1}}
.tick{{font-family:var(--mono);font-size:8.5px;fill:var(--muted)}}
.marker-spot{{stroke:var(--accent);stroke-width:1.6;stroke-dasharray:4 3}}
.marker-flip{{stroke:var(--warn);stroke-width:1.6;stroke-dasharray:2 3}}
.marker-label{{font-family:var(--mono);font-size:8.5px;fill:var(--accent);font-weight:700}}
.marker-label.flip{{fill:var(--warn)}}
.term-line{{fill:none;stroke:var(--accent);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}}
.term-area{{fill:var(--accent-soft);stroke:none}}
.term-dot{{fill:var(--panel);stroke:var(--accent);stroke-width:1.8}}
.empty{{color:var(--muted);font-size:13px;padding:16px}}

h3{{font-size:.95rem;font-weight:700;margin:26px 0 10px;letter-spacing:.01em}}
.t-scroll{{overflow-x:auto;border:1px solid var(--line);border-radius:3px}}
table{{border-collapse:collapse;width:100%;font-size:13.5px;min-width:560px}}
th,td{{text-align:left;padding:9px 13px;border-bottom:1px solid var(--line-soft);vertical-align:top}}
thead th{{font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--muted);font-weight:500;background:var(--panel-2);border-bottom:1px solid var(--line);
  white-space:nowrap;position:sticky;top:0}}
tbody tr:last-child td{{border-bottom:0}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.sig-factor{{font-weight:600;white-space:nowrap}}
.sig-state{{white-space:nowrap;color:var(--ink-2)}}
.sig-mean{{color:var(--ink-2);min-width:280px}}
.delta{{display:block;font-size:11px;color:var(--muted)}}
.pill{{font-family:var(--mono);font-size:10px;letter-spacing:.06em;text-transform:uppercase;
  padding:2px 7px;border-radius:2px;white-space:nowrap;background:var(--panel-2);color:var(--muted)}}
.pill-bullish{{background:var(--good-bg);color:var(--good)}}
.pill-bearish{{background:var(--critical-bg);color:var(--critical)}}
.pill-volatile{{background:var(--critical-bg);color:var(--critical)}}
.pill-range{{background:var(--good-bg);color:var(--good)}}
.pill-neutral{{background:var(--panel-2);color:var(--muted)}}

.warnbox{{margin-top:22px;background:var(--warn-bg);border-left:3px solid var(--warn);
  padding:12px 16px;border-radius:0 3px 3px 0}}
.warnbox-label{{font-family:var(--mono);font-size:10px;letter-spacing:.13em;text-transform:uppercase;
  color:var(--warn);display:block;margin-bottom:5px}}
.warnbox ul{{margin:0;padding-left:18px;font-size:13px;color:var(--ink-2)}}

footer.end{{border-top:1px solid var(--line);padding-top:22px;margin-top:12px;font-size:13px;
  color:var(--muted);max-width:78ch}}
footer.end p{{margin:0 0 10px}}
.glossary{{display:grid;grid-template-columns:1fr;gap:1px;background:var(--line);
  border:1px solid var(--line);border-radius:3px;overflow:hidden;margin:18px 0 24px}}
@media(min-width:700px){{.glossary{{grid-template-columns:1fr 1fr}}}}
.glossary div{{background:var(--panel);padding:11px 15px;font-size:12.5px;color:var(--ink-2)}}
.glossary b{{color:var(--ink);font-family:var(--mono);font-size:11.5px;display:block;margin-bottom:2px}}
</style>

<div class="wrap">
<header class="top">
  <div class="kicker">Options positioning · Gold &amp; Nasdaq</div>
  <h1>{_e(title)}</h1>
  <p class="stamp">{_e(stamp)}</p>
  <nav class="nav">{nav}</nav>
</header>

{blocks}

<footer class="end">
  <h3>How to read this</h3>
  <div class="glossary">
    <div><b>Net GEX</b>Dollars of underlying dealers must trade per 1% move. Positive = they dampen moves; negative = they amplify them.</div>
    <div><b>γ Flip</b>Modelled spot where net gamma crosses zero. Above it, dips get bought. Below it, dips get sold.</div>
    <div><b>VRP</b>IV minus realized vol. Positive pays option sellers. Negative means the market is moving more than options price.</div>
    <div><b>25Δ Skew</b>Put IV minus call IV at equal distance from spot. Steep = active downside hedging demand.</div>
    <div><b>Max pain</b>Strike where the least money is paid to option holders. A weak magnet into expiry, not a law.</div>
    <div><b>Vanna / Charm</b>Hedging flows generated by vol changing and by time passing — movement with no news behind it.</div>
  </div>
  <p>{_e(caveat)}</p>
  <p>Generated by options-desk. Educational and informational only — not investment advice,
     and not a recommendation to buy or sell anything.</p>
</footer>
</div>
"""
