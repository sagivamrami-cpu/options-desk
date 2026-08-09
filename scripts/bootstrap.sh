#!/usr/bin/env bash
# Create the virtualenv and install dependencies, on any machine.
#
# Written because a fresh clone failed in exactly the way that is hardest to
# notice: `pip install -r requirements.txt` printed ResolutionImpossible, the
# shell reported success because the error was piped, and the next command
# died on ModuleNotFoundError. The real cause was the interpreter -- yfinance
# needs curl_cffi, which needs Python 3.10 or newer, and a bare `python3` can
# easily be 3.9.
#
# So this script picks the interpreter deliberately, upgrades pip before
# resolving anything (old resolvers fail differently and less clearly), and
# verifies the imports actually work rather than trusting an exit code.
#
#   ./scripts/bootstrap.sh          # create/refresh .venv
#   ./scripts/bootstrap.sh --check  # verify only, do not install

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VENV="$ROOT/.venv"
MIN_MINOR=10

say() { printf '[bootstrap] %s\n' "$*"; }
die() { printf '[bootstrap] ERROR: %s\n' "$*" >&2; exit 1; }

verify() {
    "$VENV/bin/python" - <<'PY'
import sys
bad = []
for m in ("numpy", "pandas", "scipy", "yfinance"):
    try:
        __import__(m)
    except Exception as exc:
        bad.append(f"{m}: {exc}")
try:
    import optionsdesk  # noqa: F401
except Exception as exc:
    bad.append(f"optionsdesk: {exc}")
if bad:
    print("MISSING:", *bad, sep="\n  ")
    sys.exit(1)
import numpy, pandas, scipy, yfinance
print(f"python {sys.version.split()[0]}  numpy {numpy.__version__}  "
      f"pandas {pandas.__version__}  scipy {scipy.__version__}  "
      f"yfinance {yfinance.__version__}")
PY
}

if [[ "${1:-}" == "--check" ]]; then
    [[ -x "$VENV/bin/python" ]] || die "no venv at $VENV -- run ./scripts/bootstrap.sh"
    verify && say "environment OK"
    exit $?
fi

# --- pick an interpreter new enough for the dependency tree -----------------
PY_BIN=""
for cand in python3.13 python3.12 python3.11 python3.10 python3 "$HOME/.local/bin/python3.12"; do
    command -v "$cand" >/dev/null 2>&1 || [[ -x "$cand" ]] || continue
    minor="$("$cand" -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"
    major="$("$cand" -c 'import sys; print(sys.version_info[0])' 2>/dev/null || echo 0)"
    if [[ "$major" -eq 3 && "$minor" -ge "$MIN_MINOR" ]]; then
        PY_BIN="$cand"
        break
    fi
done

if [[ -z "$PY_BIN" ]]; then
    die "need Python 3.$MIN_MINOR or newer (yfinance depends on curl_cffi, which
       has no wheel for 3.9). Found only: $(python3 --version 2>&1).
       macOS:  brew install python@3.12
       Debian: sudo apt-get install -y python3.12-venv"
fi

say "using $("$PY_BIN" --version) at $(command -v "$PY_BIN" || echo "$PY_BIN")"

if [[ -x "$VENV/bin/python" ]]; then
    cur="$("$VENV/bin/python" -c 'import sys; print(sys.version_info[1])' 2>/dev/null || echo 0)"
    if [[ "$cur" -lt "$MIN_MINOR" ]]; then
        say "existing venv is on 3.$cur, rebuilding"
        rm -rf "$VENV"
    fi
fi

[[ -d "$VENV" ]] || "$PY_BIN" -m venv "$VENV"

# Upgrade pip FIRST. pip 21 predates the current resolver and reports conflicts
# in a way that is easy to misread as success.
say "upgrading pip"
"$VENV/bin/python" -m pip install -q --upgrade pip >/dev/null

say "installing requirements"
if ! "$VENV/bin/pip" install -q -r requirements.txt; then
    die "dependency install failed -- see the resolver output above"
fi

say "verifying imports"
verify || die "packages installed but imports still fail"
say "ready:  ./.venv/bin/python scripts/daily_report.py --source yahoo"
