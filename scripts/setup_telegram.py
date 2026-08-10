#!/usr/bin/env python
"""Interactive Telegram setup. Run it in YOUR terminal.

    ./.venv/bin/python scripts/setup_telegram.py

The bot token is typed here, never pasted into a chat transcript, and is written
to ~/.config/options-desk/.env with mode 0600. That file is outside the git
repository on purpose -- this repo is public.

If you already have a bot posting your daily content ideas, reuse it: paste the
same token and this will just add a second kind of message to the same chat.

To create a new one: message @BotFather on Telegram, send /newbot, follow the
prompts, and it hands you a token that looks like 1234567890:AA...

The chat id is discovered automatically. Send your bot any message first (or
add it to the group you want and post something there), then run this.
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from optionsdesk import notify  # noqa: E402


def api(token: str, method: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> int:
    print(__doc__)
    print("=" * 68)

    existing = notify.load_config()
    if existing:
        print(f"Existing config found: chat_id={existing.chat_id}, "
              f"token ending ...{existing.token[-4:]}")
        if input("Replace it? [y/N] ").strip().lower() != "y":
            print("Keeping the existing configuration.")
            return 0

    # getpass so the token is not echoed to the screen or into scrollback.
    token = getpass.getpass("Bot token (hidden as you type): ").strip()
    if not token or ":" not in token:
        print("That does not look like a bot token (expected digits:letters).",
              file=sys.stderr)
        return 1

    try:
        me = api(token, "getMe")
    except Exception as exc:
        print(f"Could not reach Telegram: {exc}", file=sys.stderr)
        return 1
    if not me.get("ok"):
        print(f"Telegram rejected the token: {me.get('description')}", file=sys.stderr)
        return 1
    bot = me["result"]
    print(f"  bot verified: @{bot.get('username')} ({bot.get('first_name')})")

    print("\nLooking for chats. If nothing is found, send your bot a message"
          "\n(or post in the group it belongs to) and press Enter to retry.")

    chat_id = None
    while chat_id is None:
        try:
            upd = api(token, "getUpdates")
        except Exception as exc:
            print(f"  getUpdates failed: {exc}", file=sys.stderr)
            return 1

        chats = {}
        for u in upd.get("result", []):
            msg = u.get("message") or u.get("channel_post") or {}
            c = msg.get("chat") or {}
            if c.get("id") is not None:
                name = c.get("title") or c.get("username") or c.get("first_name") or "?"
                chats[c["id"]] = f"{name} ({c.get('type')})"

        if not chats:
            print("  no chats seen yet.")
            if input("  press Enter to retry, or type an id manually: ").strip():
                chat_id = input("  chat id: ").strip()
            continue

        items = list(chats.items())
        if len(items) == 1:
            cid, label = items[0]
            print(f"  found: {label} -> {cid}")
            chat_id = str(cid)
        else:
            print("  multiple chats found:")
            for i, (cid, label) in enumerate(items, 1):
                print(f"    {i}. {label} -> {cid}")
            pick = input("  choose a number: ").strip()
            try:
                chat_id = str(items[int(pick) - 1][0])
            except (ValueError, IndexError):
                print("  invalid choice", file=sys.stderr)

    cfg = notify.TelegramConfig(token, chat_id)
    print("\nSending a test message…")
    try:
        notify.send(
            "‏<b>📈 שולחן האופציות מחובר</b>\n\n"
            "‏תקבל את הדוח היומי בכל יום מסחר, "
            "והתראות תוך-יומיות רק כשהמצב באמת משתנה.\n\n"
            "‏<i>קריאת מיצוב, לא תחזית. אין באמור ייעוץ השקעות.</i>",
            cfg)
    except Exception as exc:
        print(f"Test send failed: {exc}", file=sys.stderr)
        return 1
    print("  sent — check Telegram.")

    path = notify.CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# options-desk Telegram credentials.\n"
        "# Outside the git repository on purpose: the repo is public.\n"
        f"TELEGRAM_BOT_TOKEN={token}\n"
        f"TELEGRAM_CHAT_ID={chat_id}\n",
        encoding="utf-8")
    path.chmod(0o600)
    print(f"\nSaved to {path} (mode 0600)")
    print("\nNow enable delivery:")
    print("  ./.venv/bin/python scripts/install_launchd.py --job daily --at 15:30 --telegram")
    print("  ./.venv/bin/python scripts/install_launchd.py --job watch --interval 600 --telegram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
