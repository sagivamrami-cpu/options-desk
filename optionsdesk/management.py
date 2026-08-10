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
    # Order matters: "iron butterfly" contains "butterfly", so it must be
    # checked first or it silently gets the wrong (debit-butterfly) plan
    # instead of the credit-structure plan it actually needs.
    if "covered call" in n:
        return "covered_call"
    if "protective put" in n:
        return "protective_put"
    if "cash-secured" in n or "cash secured" in n:
        return "csp"
    if "pmcc" in n:
        return "pmcc"
    if "diagonal" in n:
        return "diagonal"
    if "iron butterfly" in n:
        return "iron_butterfly"
    if "condor" in n:
        return "condor"
    if "butterfly" in n:
        return "butterfly"
    if "calendar" in n:
        return "calendar"
    if "long straddle" in n:
        return "straddle_long"
    if "short straddle" in n or "short strangle" in n or "strangle" in n:
        return "undefined"
    if "spread" in n:
        return "vertical"
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

    if fam in ("vertical", "condor", "iron_butterfly") and is_credit:
        target = f"close at 50% of the credit (~${credit * 0.5:,.0f} of ${credit:,.0f})"
        stop = f"close if the loss reaches 2x the credit (~${credit * 2:,.0f})"
        if fam == "vertical":
            adjustment = (
                "if the short strike is tested with more than a week left, roll the "
                "whole spread out in time and further out of the money -- but only "
                "for a net credit. Rolling for a debit is paying to stay wrong.")
        elif fam == "iron_butterfly":
            adjustment = (
                "an iron butterfly is a tighter, higher-premium condor -- it needs the "
                "underlying closer to the body to keep working. If price is tested, "
                "roll the tested side out and away for a credit; if it is tested hard "
                "this early, the credit rarely justifies defending it -- consider "
                "closing outright rather than rolling into a worse structure.")
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

    elif fam == "protective_put":
        target = "let the put expire if unused; the position is the shares themselves"
        stop = ("there is no stop on the put -- the strike IS the floor. Decide "
                "separately at what price you would actually exit the STOCK")
        adjustment = (
            "as the put approaches expiry, either roll it forward to keep the floor in "
            "place or let the insurance lapse if you have decided you no longer need "
            "it. Do not let it expire by accident one week before an event you were "
            "buying protection for.")
        notes.append("the premium paid is a permanent drag if nothing happens -- this "
                     "is insurance, not a trade with a win condition of its own")

    elif fam == "diagonal":
        target = "close the short leg at 50-60% of its credit; reassess the long leg on its own terms"
        stop = f"the net debit is the maximum loss (${abs(debit):,.0f}) if held to the long expiry"
        adjustment = (
            "the long leg carries vega the short leg does not fully offset -- a drop "
            "in implied volatility hurts this even if price does nothing. If the short "
            "leg is tested, roll it out for a credit as with any short option; if the "
            "long leg's own thesis has changed, that is a separate decision from "
            "managing the short leg.")
        notes.append("check assignment risk on the short leg by hand before entry -- "
                     "this generator does not enforce PMCC's single safety rule, since "
                     "a diagonal's risk shape depends on the specific strikes and side")

    elif fam == "straddle_long":
        target = f"close at 75-100% gain on the debit (~${abs(debit):,.0f} paid); a straddle's profit decays fast once realized, take it"
        stop = f"the debit is the maximum loss (${abs(debit):,.0f}) -- there is no cheaper stop than time itself working against you"
        adjustment = (
            "a long straddle needs a move LARGER than the market is pricing, not just "
            "any move -- check whether the underlying has actually cleared the two "
            "breakevens. If time is passing with no move, theta works against both "
            "legs simultaneously; do not wait for the loss to prove the point.")
        notes.append("this is a pure volatility bet: it profits from a move OR from "
                     "implied volatility rising with spot unchanged. If IV is already "
                     "elevated, you are paying up for a bet the market has already priced")

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
    "covered_call": "קול מכוסה",
    "protective_put": "פוט מגן",
    "csp": "פוט מגובה מזומן",
    "pmcc": "קול מכוסה של עני",
    "diagonal": "ספרד דיאגונלי",
    "vertical": "ספרד אנכי",
    "condor": "איירון קונדור",
    "iron_butterfly": "איירון בטרפליי",
    "butterfly": "פרפר",
    "calendar": "ספרד קלנדרי",
    "straddle_long": "סטרדל (לונג)",
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

    if fam == "covered_call":
        target = "לתת לקול לפקוע, או לקנות בחזרה ב‑80% מהרווח ולגלגל"
        stop = ("אין סטופ על הקול — הסיכון הוא במניה. להחליט מראש באיזה מחיר "
                "אתה יוצא מהמניה עצמה")
        adjust = ("אם המחיר עבר את הסטרייק ואתה רוצה לשמור על המניה — לגלגל "
                  "קדימה ולמעלה **תמורת קרדיט**. אם לא אכפת לך למכור — תן לזה "
                  "להיקרא. זו הייתה העסקה מלכתחילה.")
    elif fam == "csp":
        target = f"סגירה ב‑50% מהקרדיט (~${credit*0.5:,.0f})"
        stop = "אם אתה לא באמת רוצה את המניה במחיר הזה — לא הייתה לך עסקה"
        adjust = ("אם נבחן: לגלגל קדימה ולמטה תמורת קרדיט, או לקבל הקצאה "
                  "ולעבור לקול מכוסה. **הקצאה היא לא כישלון** — היא החצי השני "
                  "של האסטרטגיה.")
    elif fam == "pmcc":
        target = f"סגירה של הרגל הקצרה ב‑50% מהקרדיט (~${credit*0.5:,.0f})"
        stop = f"החיוב נטו הוא ההפסד המקסימלי (${abs(debit):,.0f})"
        adjust = ("שים לב: הרגל הארוכה **לונג וגא** — ירידת תנודתיות פוגעת בך "
                  "גם אם המחיר עשה בדיוק מה שרצית. זה ההבדל מקול מכוסה אמיתי. "
                  "אם ה‑IV קורס, לשקול סגירה.")
    elif fam in ("vertical", "condor", "iron_butterfly") and is_credit:
        target = f"סגירה ב‑50% מהקרדיט (~${credit*0.5:,.0f})"
        stop = f"סגירה בהפסד של פי 2 מהקרדיט (~${credit*2:,.0f})"
        if fam == "vertical":
            adjust = ("אם הסטרייק הקצר נבחן ונשאר יותר משבוע — לגלגל את כל הספרד "
                      "קדימה בזמן והרחק יותר מהכסף, אבל **רק תמורת קרדיט נטו**. "
                      "גלגול בחיוב הוא תשלום על להישאר בטעות.")
        elif fam == "iron_butterfly":
            adjust = ("איירון בטרפליי הוא קונדור צר יותר עם פרמיה גבוהה יותר — "
                      "הוא צריך שהמחיר יישאר קרוב יותר לגוף כדי לעבוד. אם נבחן, "
                      "לגלגל את הצד שנבחן החוצה תמורת קרדיט; אם נבחן חזק ומוקדם, "
                      "לרוב עדיף לסגור מאשר לגלגל למבנה גרוע יותר.")
        else:
            adjust = ("לטפל רק בצד שנבחן: לגלגל אותו החוצה תמורת קרדיט ולהשאיר את "
                      "הצד השני. סגירת שני הצדדים בגלל אחד מוותרת על פרמיה שעובדת.")
    elif fam == "protective_put":
        target = "לתת לפוט לפקוע אם לא נדרש — הפוזיציה היא המניה עצמה"
        stop = "אין סטופ על הפוט — הסטרייק הוא הרצפה. להחליט בנפרד באיזה מחיר יוצאים מהמניה"
        adjust = ("ככל שהפוט מתקרב לפקיעה — לגלגל קדימה כדי לשמור על הרצפה, או "
                  "לתת לביטוח לפקוע אם הוחלט שהוא כבר לא נחוץ. לא לתת לזה לפקוע "
                  "בטעות שבוע לפני האירוע שבשבילו קניתם את ההגנה.")
    elif fam == "diagonal":
        target = "סגירת הרגל הקצרה ב‑50%–60% מהקרדיט שלה; להעריך את הרגל הארוכה בנפרד"
        stop = f"החיוב נטו הוא ההפסד המקסימלי (${abs(debit):,.0f}) אם מוחזק עד לפקיעה הרחוקה"
        adjust = ("הרגל הארוכה נושאת וגא שהרגל הקצרה לא מכסה במלואו — ירידת "
                  "תנודתיות פוגעת גם אם המחיר לא זז. אם הרגל הקצרה נבחנת — לגלגל "
                  "אותה תמורת קרדיט כמו כל אופציה קצרה.")
    elif fam == "straddle_long":
        target = f"סגירה ב‑75%–100% רווח על החיוב (~${abs(debit):,.0f}) — הרווח בסטרדל נשחק מהר ברגע שהתממש"
        stop = f"החיוב הוא ההפסד המקסימלי (${abs(debit):,.0f}) — אין סטופ זול יותר מהזמן עצמו שעובד נגדך"
        adjust = ("סטרדל לונג צריך תנועה **גדולה יותר** ממה שהשוק מתמחר, לא כל "
                  "תנועה — לבדוק אם המחיר באמת חצה את שתי נקודות האיזון. אם הזמן "
                  "חולף בלי תנועה, התטא פועל נגד שתי הרגליים בו־זמנית.")
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
    if fam == "covered_call":
        warn = ("זו לא הכנסה חינם — מכרת את הצד העולה. הסיכון כלפי מטה זהה "
                "להחזקת המניה, פחות הקרדיט. המדד הנכון הוא מול החזקת המניה, "
                "לא מול אפס.")
    elif fam == "csp":
        warn = ("זהה בתשלום לקול מכוסה באותו סטרייק. ההפסד רץ עד לסטרייק — "
                "לגדל בהנחה שתקבל הקצאה.")
    elif fam == "undefined":
        warn = ("סיכון בלתי מוגבל — אין הפסד מקסימלי. לגדל לפי תרחיש קיצון של "
                "3–4 סטיות תקן, לא לפי דרישת המרווח.")
    elif fam == "diagonal":
        warn = ("זהה ברוח ל‑PMCC, אבל בלי הבדיקה האוטומטית שלו נגד הקצאה "
                "להפסד נעול — לבדוק ידנית לפני הכניסה.")
    elif fam == "straddle_long":
        warn = ("הימור טהור על תנודתיות, לא על כיוון — משלמים על תנועה גדולה "
                "מהמתומחר. אם ה‑IV כבר גבוה, משלמים ביוקר על הימור שהשוק כבר תמחר.")
    elif math.isfinite(dte) and dte <= 7:
        warn = ("פחות משבוע לפקיעה — יכול לעבור מרוב הרווח להפסד מלא "
                "בתוך יום מסחר אחד.")
    elif fam in ("vertical", "condor", "iron_butterfly") and is_credit:
        warn = "מכירת פרמיה — פער פתיחה מזיז את זה יותר ממה שהיוונים מרמזים."

    return {"family_he": FAMILY_HE.get(fam, "מבנה"), "target": target,
            "stop": stop, "time_exit": time_exit, "adjust": adjust, "warn": warn}
