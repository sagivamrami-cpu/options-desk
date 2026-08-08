"""options-desk: an options positioning and volatility analysis toolkit.

Typical use:

    from optionsdesk.report import analyze
    a = analyze("QQQ")               # auto: IBKR if reachable, else Yahoo
    print(a["read"]["regime"], a["gex"]["flip_level"])
"""

from .report import analyze, synthesize, to_json
from .sources import fetch

__version__ = "0.1.0"
__all__ = ["analyze", "synthesize", "to_json", "fetch"]
