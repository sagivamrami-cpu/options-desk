"""Management plans: the exit and adjustment rules that belong to a structure.

A proposed trade without an exit plan is not a proposal, it is a bet. This
module attaches, to every structure the scanner produces, the four decisions
that have to be made BEFORE entry:

    target      where you take profit
    stop        where you admit the thesis was wrong
    time exit   when you leave regardless, because gamma risk has grown
    adjustment  what you do if it goes against you but the thesis holds

The rules below are the conventional desk defaults, and they are conventions
rather than laws. Two of them are worth defending explicitly:

**Take profit early on credit structures.** The last portion of a credit
spread's maximum profit arrives in the final days, which is exactly when gamma
risk is highest. You are holding the riskiest part of the trade to collect the
slowest part of the reward. Closing at half of maximum gives up the worst-paid
segment.

**Leave before expiry week.** Around 21 days to expiry, gamma begins to
dominate: the position stops behaving like a probability distribution and
starts behaving like a coin flip that resets every morning. Exiting there is
not caution, it is refusing a bet whose odds have changed underneath you.

Rolling is NOT a way to avoid a loss. It is a new trade that happens to reuse
the same underlying, and it should be justified on its own terms. If you would
not open the rolled position fresh today, closing is the correct action.
"""

from __future__ import annotations

import math

__all__ = ["plan_for", "ManagementPlan"]

# Below this many days the position is gamma-dominated rather than
# probability-dominated. See the module docstring.
GAMMA_DANGER_DTE = 21


class ManagementPlan:
    __slots__ = ("target", "stop", "time_exit", "adjustment", "notes")

    def __init__(self, target, stop, time_exit, adjustment, notes=None):
        self.target = target
        self.stop = stop
        self.time_exit = time_exit
        self.adjustment = adjustment
        self.notes = notes or []

    def as_dict(self):
        return {"target": self.target, "stop": self.stop,
                "time_exit": self.time_exit, "adjustment": self.adjustment,
                "notes": self.notes}


def _family(name: str) -> str:
    n = (name or "").lower()
    if "condor" in n:
        return "condor"
    if "butterfly" in n:
        return "butterfly"
    if "calendar" in n:
        return "calendar"
    if "spread" in n:
        return "vertical"
    if "strangle" in n or "straddle" in n:
        return "undefined"
    return "other"


def plan_for(candidate: dict, spot: float) -> ManagementPlan:
    """Build the plan for one scanner candidate.

    `candidate` is a row from scanner.scan_symbol()['candidates'].
    All money figures are per contract.
    """
    name = str(candidate.get("name", ""))
    fam = _family(name)
    cost = float(candidate.get("cost", 0.0))          # <0 = credit received
    max_p = float(candidate.get("max_profit", float("nan")))
    max_l = float(candidate.get("max_loss", float("nan")))
    dte = float(candidate.get("dte", float("nan")))
    is_credit = cost < 0
    credit = abs(cost) if is_credit else 0.0
    debit = cost if not is_credit else 0.0

    notes = []
    time_exit = (
        f"close at {GAMMA_DANGER_DTE} DTE regardless of P&L"
        if math.isfinite(dte) and dte > GAMMA_DANGER_DTE
        else "already inside the gamma-dominated window -- manage actively or size small"
    )
    if math.isfinite(dte) and dte <= 7:
        notes.append("under a week to expiry: this can move from most of max profit "
                     "to full max loss inside a single session")

    if fam in ("vertical", "condor") and is_credit:
        target = f"close at 50% of the credit (~${credit * 0.5:,.0f} of ${credit:,.0f})"
        stop = f"close if the loss reaches 2x the credit (~${credit * 2:,.0f})"
        if fam == "vertical":
            adjustment = (
                "if the short strike is tested with more than a week left, roll the "
                "whole spread out in time and further out of the money -- but only "
                "for a net credit. Rolling for a debit is paying to stay wrong.")
        else:
            adjustment = (
                "manage the tested side only: roll that vertical out and away for a "
                "credit and leave the untested side alone. Closing both halves "
                "because one is under pressure gives up the premium that is working.")
        notes.append("this is a short-premium position: a gap moves it further than "
                     "the greeks suggest, because the greeks are local and a gap is not")

    elif fam == "butterfly":
        target = f"close at 25-50% of maximum (~${max_p * 0.35:,.0f} of ${max_p:,.0f})" \
            if math.isfinite(max_p) else "close at 25-50% of maximum"
        stop = (f"the debit is the maximum loss (${abs(debit):,.0f}); no stop is "
                f"required, but leaving early preserves capital when the body is missed")
        adjustment = (
            "a butterfly only pays near the body. If the underlying leaves the wings "
            "early there is nothing to repair -- close it and stop paying theta on a "
            "structure that now needs a round trip to work.")
        notes.append("value concentrates in the final days, so patience is the "
                     "position -- but only while price is still near the body")

    elif fam == "calendar":
        target = f"close at 25-40% of the debit (~${abs(debit) * 0.3:,.0f})"
        stop = f"the debit is the maximum loss (${abs(debit):,.0f})"
        adjustment = (
            "a calendar wants the underlying to sit still AND the front leg to decay "
            "faster than the back. Two things break it: a large move away from the "
            "strike, or a collapse in back-month implied vol. If either happens the "
            "thesis is gone -- close rather than adjust.")
        notes.append("this position is long vega: falling implied volatility hurts it "
                     "even if the underlying does exactly what you wanted")

    elif fam == "undefined":
        target = f"close at 50% of the credit (~${credit * 0.5:,.0f})"
        stop = f"close at 2x the credit (~${credit * 2:,.0f}) -- mechanically, no negotiation"
        adjustment = (
            "roll the tested side out and away for a credit, or close. Do NOT add "
            "size to a losing undefined-risk position.")
        notes.append("UNDEFINED RISK: there is no maximum loss. Size this on a 3-4 "
                     "standard deviation gap, not on the margin requirement, which is "
                     "calibrated to normal conditions and gets raised exactly when you "
                     "can least afford it")

    else:
        target = "define a profit target before entry"
        stop = "define a maximum loss before entry"
        adjustment = "no standard adjustment for this structure"

    return ManagementPlan(target, stop, time_exit, adjustment, notes)


# ----------------------------------------------------------------------
# Hebrew rendering of a plan, for the Telegram message.
# ----------------------------------------------------------------------

FAMILY_HE = {
    "vertical": "ספרד אנכי",
    "condor": "איירון קונדור",
    "butterfly": "פרפר",
    "calendar": "ספרד קלנדרי",
    "undefined": "סיכון בלתי מוגבל",
    "other": "מבנה",
}


def plan_he(candidate: dict, spot: float) -> dict:
    """Same plan, phrased in Hebrew. Returns plain strings for the formatter."""
    name = str(candidate.get("name", ""))
    fam = _family(name)
    cost = float(candidate.get("cost", 0.0))
    max_p = float(candidate.get("max_profit", float("nan")))
    dte = float(candidate.get("dte", float("nan")))
    is_credit = cost < 0
    credit = abs(cost) if is_credit else 0.0
    debit = cost if not is_credit else 0.0

    if fam in ("vertical", "condor") and is_credit:
        target = f"סגירה ב‑50% מהקרדיט (~${credit*0.5:,.0f})"
        stop = f"סגירה בהפסד של פי 2 מהקרדיט (~${credit*2:,.0f})"
        adjust = ("אם הסטרייק הקצר נבחן ונשאר יותר משבוע — לגלגל את כל הספרד "
                  "קדימה בזמן והרחק יותר מהכסף, אבל **רק תמורת קרדיט נטו**. "
                  "גלגול בחיוב הוא תשלום על להישאר בטעות."
                  if fam == "vertical" else
                  "לטפל רק בצד שנבחן: לגלגל אותו החוצה תמורת קרדיט ולהשאיר את "
                  "הצד השני. סגירת שני הצדדים בגלל אחד מוותרת על פרמיה שעובדת.")
    elif fam == "butterfly":
        target = (f"סגירה ב‑25%–50% מהמקסימום (~${max_p*0.35:,.0f})"
                  if math.isfinite(max_p) else "סגירה ב‑25%–50% מהמקסימום")
        stop = f"החיוב הוא ההפסד המקסימלי (${abs(debit):,.0f}) — אין צורך בסטופ"
        adjust = ("פרפר משלם רק ליד הגוף. אם המחיר יוצא מהכנפיים מוקדם — אין מה "
                  "לתקן. לסגור ולא להמשיך לשלם תטא על מבנה שדורש חזרה הלוך ושוב.")
    elif fam == "calendar":
        target = f"סגירה ב‑25%–40% מהחיוב (~${abs(debit)*0.3:,.0f})"
        stop = f"החיוב הוא ההפסד המקסימלי (${abs(debit):,.0f})"
        adjust = ("קלנדר רוצה שהמחיר יעמוד במקום **וגם** שהרגל הקרובה תישחק מהר "
                  "יותר. שני דברים שוברים אותו: תנועה גדולה מהסטרייק, או קריסת "
                  "תנודתיות ברגל הרחוקה. אם אחד מהם קרה — התזה מתה, לסגור.")
    elif fam == "undefined":
        target = f"סגירה ב‑50% מהקרדיט (~${credit*0.5:,.0f})"
        stop = f"סגירה בפי 2 מהקרדיט (~${credit*2:,.0f}) — מכנית, בלי משא ומתן"
        adjust = "לגלגל את הצד שנבחן החוצה תמורת קרדיט, או לסגור. **לא להוסיף גודל.**"
    else:
        target = "להגדיר יעד רווח לפני הכניסה"
        stop = "להגדיר הפסד מקסימלי לפני הכניסה"
        adjust = "אין כלל תיקון סטנדרטי למבנה הזה"

    time_exit = (f"לסגור ב‑{GAMMA_DANGER_DTE} ימים לפקיעה ללא קשר לרווח"
                 if math.isfinite(dte) and dte > GAMMA_DANGER_DTE
                 else "כבר בתוך אזור הגאמה — לנהל בקפידה או להקטין גודל")

    warn = None
    if fam == "undefined":
        warn = ("סיכון בלתי מוגבל — אין הפסד מקסימלי. לגדל לפי תרחיש קיצון של "
                "3–4 סטיות תקן, לא לפי דרישת המרווח.")
    elif math.isfinite(dte) and dte <= 7:
        warn = ("פחות משבוע לפקיעה — יכול לעבור מרוב הרווח להפסד מלא "
                "בתוך יום מסחר אחד.")
    elif fam in ("vertical", "condor") and is_credit:
        warn = "מכירת פרמיה — פער פתיחה מזיז את זה יותר ממה שהיוונים מרמזים."

    return {"family_he": FAMILY_HE.get(fam, "מבנה"), "target": target,
            "stop": stop, "time_exit": time_exit, "adjust": adjust, "warn": warn}
