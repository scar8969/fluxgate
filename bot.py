"""Telegram bot for FluxGate — check traffic, check in, get subscription links.

Commands (link your account once with your subscription token):
  /start              show help
  /link <token>       link your FluxGate account (token = user id)
  /traffic            show remaining/used traffic
  /checkin            daily check-in reward
  /subscribe          subscription link (ss)
  /stats              admin: users/orders/revenue (admin users only)

Run with:
  TELEGRAM_BOT_TOKEN=<token> .venv/Scripts/python bot.py
Without a token it runs in DEMO_MODE and prints what it would send.
"""
import os
import sys
import time
import urllib.request
import json

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API = f"https://api.telegram.org/bot{TOKEN}"


def tg_call(method, params):
    """POST to the Telegram Bot API. Returns parsed JSON or None."""
    req = urllib.request.Request(
        f"{API}/{method}",
        data=json.dumps(params).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def send_message(chat_id, text):
    if not TOKEN:
        print(f"[demo] would send to {chat_id}: {text}")
        return
    tg_call("sendMessage", {"chat_id": chat_id, "text": text})


def handle_update(update, get_db):
    """Process one Telegram update against the app. Pure logic, testable."""
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id")
    if not chat_id or not text:
        return None
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    user = None
    if cmd in ("/traffic", "/checkin", "/subscribe", "/stats"):
        user = _resolve_user(chat_id, get_db)
    if cmd == "/start":
        return "FluxGate bot 🤖\n\n" \
               "/link <token> — link your account (token = your user id)\n" \
               "/traffic — remaining traffic\n" \
               "/checkin — daily reward\n" \
               "/subscribe — ss subscription link\n" \
               "/stats — admin stats"
    if cmd == "/link":
        token = arg
        if not token.isdigit():
            return "Usage: /link <token> (your user id)"
        db = get_db()
        user = db.get(token)
        if not user:
            return "Account not found."
        # persist link chat_id -> user id
        _save_link(chat_id, token)
        return f"Linked to {user['username']}! Try /traffic"
    if cmd == "/traffic":
        if not user:
            return _need_link()
        return (f"📊 {user['username']}\n"
                f"Remaining: {user['human_remain']}\n"
                f"Used: {user['human_used']}\n"
                f"Total: {user['human_total']}\n"
                f"Level: Lv.{user['level']}")
    if cmd == "/checkin":
        if not user:
            return _need_link()
        return user["checkin"]
    if cmd == "/subscribe":
        if not user:
            return _need_link()
        return f"🔗 Subscription:\n{user['sub_link']}"
    if cmd == "/stats":
        if not user or not user.get("is_admin"):
            return "Admin only."
        return (f"👑 {user['stats']['total_users']} users\n"
                f"💰 ¥{user['stats']['revenue']} revenue\n"
                f"🟢 {user['stats']['online_nodes']}/{user['stats']['total_nodes']} nodes online")
    return "Unknown command. Try /start"


def _resolve_user(chat_id, get_db):
    """Look up a linked user for this chat, else None."""
    link = _load_link(chat_id)
    if not link:
        return None
    db = get_db()
    return db.get(link)


def _need_link():
    return "Link your account first: /link <your-user-id>"


_LINKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tg_links.json")


def _save_link(chat_id, user_id):
    links = {}
    try:
        with open(_LINKS_FILE, encoding="utf-8") as f:
            links = json.load(f)
    except (OSError, ValueError):
        pass
    links[str(chat_id)] = str(user_id)
    with open(_LINKS_FILE, "w", encoding="utf-8") as f:
        json.dump(links, f)


def _load_link(chat_id):
    try:
        with open(_LINKS_FILE, encoding="utf-8") as f:
            return json.load(f).get(str(chat_id))
    except (OSError, ValueError):
        return None


def main():
    from fluxgate import create_app
    from fluxgate.models import User, UserOrder, UserCheckInLog
    from fluxgate.proxy import ProxyNode

    app = create_app()

    def get_db():
        """Snapshot view of the DB as plain dicts (bot-friendly)."""
        with app.app_context():
            users = {str(u.id): {
                "username": u.username,
                "level": u.level,
                "human_remain": u.human_remain_traffic,
                "human_used": u.human_used_traffic,
                "human_total": u.human_total_traffic,
                "sub_link": u.sub_link,
                "is_admin": u.is_admin,
                "checkin": _checkin_text(u),
                "stats": _stats_dict(),
            } for u in User.query.all()}
            return users

    def _checkin_text(u):
        with app.app_context():
            reward = UserCheckInLog.checkin(u)
            if reward is None:
                return "Already checked in today! Come back tomorrow."
            return f"Checked in! +{reward // (1024 * 1024)} MB"

    def _stats_dict():
        with app.app_context():
            revenue = (UserOrder.query.filter(
                UserOrder.status == UserOrder.STATUS_FINISHED
            ).count(), )
            total = User.query.count()
            rev = sum(o.amount for o in UserOrder.query.filter(
                UserOrder.status == UserOrder.STATUS_FINISHED).all())
            nodes = ProxyNode.query.all()
            return {"total_users": total, "revenue": round(rev, 2),
                    "total_nodes": len(nodes),
                    "online_nodes": sum(1 for n in nodes if n.is_online())}

    if not TOKEN:
        print("[bot] DEMO_MODE (no TELEGRAM_BOT_TOKEN) — sending would print here")
        print("[bot] try: /link 2  /traffic  /checkin  /subscribe  /stats")
        # demo: simulate an update from user 2
        for cmd in ["/link 2", "/traffic", "/subscribe", "/stats"]:
            print(f">>> {cmd}")
            print(handle_update({"message": {"chat": {"id": 1}, "text": cmd}}, get_db))
        return

    print("[bot] polling Telegram...")
    offset = 0
    while True:
        try:
            updates = tg_call("getUpdates", {"offset": offset, "timeout": 30}) or {"result": []}
            for u in updates.get("result", []):
                reply = handle_update(u, get_db)
                if reply:
                    send_message(u.get("message", {}).get("chat", {}).get("id"), reply)
                offset = u["update_id"] + 1
        except Exception as e:
            print(f"[bot] error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
