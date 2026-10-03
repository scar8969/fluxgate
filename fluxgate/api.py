"""JSON API — mirrors apps/api in the original.

Endpoints:
  GET  /api/subscribe?token=..&sub_type=..   subscription links
  GET  /api/proxy_configs/<node_id>          node config for backends
  POST /api/proxy_configs/<node_id>          traffic report from backends
  POST /api/user/settings                    update ss password
  GET  /api/user/stats/traffic_chart         traffic chart data
  GET  /api/user/stats/ref_chart             referral chart data
  POST /api/checkin                          daily check-in reward
  POST /api/orders                           create order
  POST /api/callback/alipay                  payment callback (demo)
  GET  /api/system_status                    admin dashboard stats
"""
from datetime import datetime, timedelta
import json

from flask import Blueprint, current_app, jsonify, render_template, request, session

from . import db, GB

VERSION = "0.6.0"
from .models import Goods, InviteCode, User, UserCheckInLog, UserOrder, UserRefLog
from .proxy import ProxyNode, UserTrafficLog, AuditLog
from .sub import generate_clash_config, generate_subscription

bp = Blueprint("api", __name__)

# per-IP API rate limiter: {ip: [timestamps]} — 120 req / 60s
_api_hits = {}
API_LIMIT = 120
API_WINDOW = 60


def _api_rate_limited(ip: str) -> bool:
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.utcnow()
    hits = [t for t in _api_hits.get(ip, []) if now - t < _td(seconds=API_WINDOW)]
    _api_hits[ip] = hits
    if len(hits) >= API_LIMIT:
        return True
    hits.append(now)
    return False


@bp.before_app_request
def _rate_limit_api():
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE"):
        ip = request.remote_addr or "unknown"
        if _api_rate_limited(ip):
            return jsonify({"error": "rate limit exceeded"}), 429
    return None


@bp.after_app_request
def _rate_limit_headers(resp):
    """Expose rate-limit state on API responses."""
    if request.path.startswith("/api/"):
        ip = request.remote_addr or "unknown"
        hits = len([t for t in _api_hits.get(ip, [])])
        resp.headers["X-RateLimit-Limit"] = str(API_LIMIT)
        resp.headers["X-RateLimit-Remaining"] = str(max(0, API_LIMIT - hits))
        resp.headers["X-RateLimit-Reset"] = str(API_WINDOW)
    return resp


def _current_user():
    uid = session.get("user_id")
    if uid:
        return User.query.get(uid)
    return None


def _api_authorized():
    """Backend nodes authenticate with X-API-Token (mirrors api_authorized)."""
    token = request.headers.get("X-API-Token", "")
    return token == current_app.config.get("API_TOKEN", "dev-api-token")


@bp.route("/subscribe")
def subscribe():
    token = request.args.get("token", "")
    api_key = request.args.get("api_key", "")
    user = None
    if api_key:
        user = User.query.filter_by(api_key=api_key).first()
    elif token and token.isdigit():
        user = User.query.filter_by(id=int(token)).first()
    if not user:
        return "not found", 404
    sub_type = request.args.get("sub_type", "ss")
    try:
        if sub_type == "clash":
            return generate_clash_config(user), 200, {"Content-Type": "text/yaml; charset=utf-8"}
        body = generate_subscription(user, sub_type)
        return body, 200, {"Content-Type": "text/plain; charset=utf-8"}
    except Exception as e:
        return f"error: {e}", 500


@bp.route("/subscribe/qr")
def subscribe_qr():
    """QR code PNG for the subscription URL (any sub_type)."""
    token = request.args.get("token", "")
    user = User.query.filter_by(id=int(token)).first() if token.isdigit() else None
    if not user:
        return "not found", 404
    sub_type = request.args.get("sub_type", "ss")
    url = f"{current_app.config['HOST']}/api/subscribe?token={token}&sub_type={sub_type}"
    import io
    import qrcode
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    from flask import Response
    return Response(buf.getvalue(), mimetype="image/png")


@bp.route("/proxy_configs/<int:node_id>", methods=["GET", "POST"])
def proxy_configs(node_id):
    if not _api_authorized():
        return jsonify({"error": "unauthorized"}), 401
    node = ProxyNode.query.get(node_id)
    if not node:
        return jsonify({"error": "not found"}), 404
    if request.method == "GET":
        return jsonify(node.get_proxy_configs())
    # POST: traffic report from backend — also acts as heartbeat
    node.last_seen = datetime.utcnow()
    if not node.first_seen:
        node.first_seen = node.last_seen
    data = request.get_json(force=True, silent=True) or {}
    for item in data.get("data", []):
        uid = item.get("user_id")
        user = User.query.get(uid) if uid else None
        if not user:
            continue
        up = int(item.get("upload", 0))
        down = int(item.get("download", 0))
        UserTrafficLog.record(user.id, node_id, up, down)
        user.upload_traffic = (user.upload_traffic or 0) + up
        user.download_traffic = (user.download_traffic or 0) + down
        node.used_traffic = (node.used_traffic or 0) + up + down
        user.last_use_time = datetime.utcnow()
        # auto-disable when over quota (mirrors check_and_disable_out_of_traffic_user)
        if user.overflow:
            user.enable = False
    db.session.commit()
    return jsonify({})


@bp.route("/user/2fa", methods=["POST"])
def user_2fa_enable():
    """Enable TOTP 2FA — returns secret + otpauth URI."""
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    from .totp import generate_secret, provisioning_uri
    if not user.totp_secret:
        user.totp_secret = generate_secret()
        db.session.commit()
    return jsonify({
        "status": "success",
        "secret": user.totp_secret,
        "uri": provisioning_uri(user.totp_secret, user.username),
    })


@bp.route("/user/2fa/verify", methods=["POST"])
def user_2fa_verify():
    """Verify a code against the user's TOTP secret."""
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    code = (request.get_json(force=True, silent=True) or {}).get("code", "")
    from .totp import verify
    if verify(user.totp_secret, code):
        return jsonify({"status": "success"})
    return jsonify({"error": "invalid code"}), 400


@bp.route("/user/2fa/disable", methods=["POST"])
def user_2fa_disable():
    """Disable TOTP 2FA (requires a valid code)."""
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    code = (request.get_json(force=True, silent=True) or {}).get("code", "")
    from .totp import verify
    if not verify(user.totp_secret, code):
        return jsonify({"error": "invalid code"}), 400
    user.totp_secret = ""
    db.session.commit()
    return jsonify({"status": "success"})


@bp.route("/user/2fa/status")
def user_2fa_status():
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    return jsonify({"enabled": bool(user.totp_secret)})


@bp.route("/traffic/node/<int:node_id>")
def node_traffic(node_id):
    """Per-node traffic for the current user (last 7 days)."""
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    from datetime import datetime as _dt, timedelta as _td
    days = min(request.args.get("days", 7, type=int), 30)
    since = _dt.utcnow() - _td(days=days)
    logs = UserTrafficLog.query.filter(
        UserTrafficLog.user_id == user.id,
        UserTrafficLog.node_id == node_id,
        UserTrafficLog.created_at >= since,
    ).all()
    # bucket by day
    buckets = {}
    for l in logs:
        day = l.created_at.date().isoformat() if l.created_at else ""
        b = buckets.setdefault(day, {"upload": 0, "download": 0})
        b["upload"] += l.upload or 0
        b["download"] += l.download or 0
    return jsonify({"node_id": node_id, "days": days,
                    "series": [{"date": d, **buckets.get(d, {"upload": 0, "download": 0})}
                               for d in sorted(buckets)]})


@bp.route("/user/settings", methods=["POST"])
def user_settings():
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    pw = request.form.get("ss_password") or (request.get_json(silent=True) or {}).get("ss_password")
    if pw:
        user.ss_password = pw
        db.session.commit()
        return jsonify({"status": "success", "title": "Updated!", "subtitle": "Reconfigure your client with the new password."})
    return jsonify({"status": "error", "title": "Update failed!", "subtitle": "No new password provided."})


@bp.route("/user/password", methods=["POST"])
def change_password():
    """Change the account login password (requires current password)."""
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(force=True, silent=True) or request.form
    current = data.get("current_password", "")
    new = data.get("new_password", "")
    if not user.check_password(current):
        return jsonify({"status": "error", "title": "Wrong current password!"}), 400
    if len(new) < 6:
        return jsonify({"status": "error", "title": "New password too short (min 6 chars)!"}), 400
    user.set_password(new)
    db.session.commit()
    return jsonify({"status": "success", "title": "Password changed!"})


@bp.route("/user/api_key", methods=["POST"])
def regenerate_api_key():
    """Regenerate the user's API key (used for subscription links)."""
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    from .models import _long_rand
    user.api_key = _long_rand(32)
    db.session.commit()
    return jsonify({"status": "success", "api_key": user.api_key})


@bp.route("/user/stats/traffic_chart")
def traffic_chart():
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    node_id = request.args.get("node_id", 0, type=int)
    days = 7
    today = datetime.utcnow().date()
    labels, up_series, down_series = [], [], []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        labels.append(day.isoformat())
        logs = UserTrafficLog.query.filter(
            UserTrafficLog.user_id == user.id,
            UserTrafficLog.created_at >= datetime(day.year, day.month, day.day),
            UserTrafficLog.created_at < datetime(day.year, day.month, day.day) + timedelta(days=1),
        ).all()
        if node_id:
            logs = [l for l in logs if l.node_id == node_id]
        up_series.append(sum(l.upload for l in logs))
        down_series.append(sum(l.download for l in logs))
    return jsonify({"labels": labels, "upload": up_series, "download": down_series})


@bp.route("/user/stats/ref_chart")
def ref_chart():
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    days = 7
    today = datetime.utcnow().date()
    labels, counts = [], []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        labels.append(day.isoformat())
        counts.append(UserRefLog.query.filter_by(user_id=user.id, date=day).count())
    return jsonify({"labels": labels, "counts": counts})


@bp.route("/checkin", methods=["POST"])
def checkin():
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    reward = UserCheckInLog.checkin(user)
    if reward is None:
        return jsonify({"status": "error", "title": "Already checked in today!", "subtitle": "Come back tomorrow."})
    return jsonify({
        "status": "success",
        "title": "Checked in!",
        "subtitle": f"Earned {reward // (1024*1024)} MB of traffic",
    })


@bp.route("/orders", methods=["POST"])
def create_order():
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    data = request.get_json(force=True, silent=True) or request.form
    goods_id = int(data.get("goods_id", 0))
    goods = Goods.query.get(goods_id) if goods_id else None
    if not goods or goods.status != Goods.STATUS_ON:
        return jsonify({"error": "goods not found"}), 404
    order = UserOrder.create_order(user.id, goods.money)
    order.goods_id = goods.id
    db.session.commit()
    # payment provider: stripe returns a checkout URL, demo returns None (auto-confirm)
    from .payments import create_checkout
    pay_url = create_checkout(order, user, current_app)
    resp = {"status": "success", "order": order.to_dict()}
    if pay_url:
        resp["payment_url"] = pay_url
    return jsonify(resp)


@bp.route("/callback/alipay", methods=["POST"])
def alipay_callback():
    """Demo payment callback. In production this verifies the Alipay signature;
    here any POST with a valid out_trade_no marks the order paid (demo mode)."""
    data = request.get_json(force=True, silent=True) or request.form
    out_trade_no = data.get("out_trade_no")
    if not out_trade_no:
        return jsonify({"error": "missing out_trade_no"}), 400
    order = UserOrder.finish_order(out_trade_no)
    if not order:
        return jsonify({"error": "order not found or already finished"}), 404
    _fire_webhook(order)
    _notify_telegram(order)
    # email receipt (no-op if SMTP unset)
    from .mail import notify_order_paid
    user = User.query.get(order.user_id)
    goods = Goods.query.get(order.goods_id)
    if user and goods:
        notify_order_paid(user, order, goods)
    return jsonify({"status": "success", "order": order.to_dict()})


def _notify_telegram(order):
    """Send an order.paid notification to TELEGRAM_CHAT_ID (fire-and-forget)."""
    token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = current_app.config.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    import threading
    import urllib.request

    text = (f"💰 Order paid\n"
            f"Order: {order.out_trade_no}\n"
            f"Amount: ${order.amount}\n"
            f"User: #{order.user_id}")
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()

    def _send():
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def _fire_webhook(order):
    """POST the paid order to WEBHOOK_URL (fire-and-forget, non-blocking)."""
    url = current_app.config.get("WEBHOOK_URL", "")
    if not url:
        return
    import threading
    import urllib.request

    payload = json.dumps({
        "event": "order.paid",
        "out_trade_no": order.out_trade_no,
        "amount": order.amount,
        "user_id": order.user_id,
        "timestamp": datetime.utcnow().isoformat(),
    }).encode()

    def _send():
        try:
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # fire-and-forget; don't fail the callback

    threading.Thread(target=_send, daemon=True).start()


@bp.route("/gen/invitecode", methods=["POST"])
def gen_invitecode():
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    if user.invitecode_num <= 0:
        return jsonify({"status": "error", "title": "No invite codes left!"})
    num = min(int(request.form.get("num", 1)), user.invitecode_num)
    codes = InviteCode.gen_codes(user.id, num)
    user.invitecode_num -= num
    db.session.commit()
    return jsonify({"status": "success", "codes": [c.code for c in codes]})


@bp.route("/health")
def health():
    """Liveness probe: DB up + version."""
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return jsonify({
        "status": "ok" if db_ok else "degraded",
        "version": VERSION,
        "db": "up" if db_ok else "down",
    })


@bp.route("/metrics")
def metrics():
    """Prometheus-format metrics for scraping."""
    from flask import Response
    total_users = User.query.count()
    total_orders = UserOrder.query.count()
    paid_orders = UserOrder.query.filter(UserOrder.status == UserOrder.STATUS_FINISHED).count()
    revenue = db.session.query(db.func.sum(UserOrder.amount)).filter(
        UserOrder.status == UserOrder.STATUS_FINISHED).scalar() or 0.0
    total_traffic = sum(n.used_traffic or 0 for n in ProxyNode.query.all())
    online_nodes = sum(1 for n in ProxyNode.query.all() if n.is_online())
    lines = [
        "# HELP fluxgate_users_total Total registered users",
        "# TYPE fluxgate_users_total gauge",
        f"fluxgate_users_total {total_users}",
        "# HELP fluxgate_orders_total Total orders created",
        "# TYPE fluxgate_orders_total counter",
        f"fluxgate_orders_total {total_orders}",
        "# HELP fluxgate_orders_paid_total Paid (finished) orders",
        "# TYPE fluxgate_orders_paid_total counter",
        f"fluxgate_orders_paid_total {paid_orders}",
        "# HELP fluxgate_revenue_total Revenue from paid orders (currency units)",
        "# TYPE fluxgate_revenue_total counter",
        f"fluxgate_revenue_total {revenue:.2f}",
        "# HELP fluxgate_traffic_bytes_total Total traffic relayed across nodes",
        "# TYPE fluxgate_traffic_bytes_total counter",
        f"fluxgate_traffic_bytes_total {total_traffic}",
        "# HELP fluxgate_nodes_online Number of nodes reporting heartbeat",
        "# TYPE fluxgate_nodes_online gauge",
        f"fluxgate_nodes_online {online_nodes}",
    ]
    return Response("\n".join(lines) + "\n", mimetype="text/plain; version=0.0.4")


@bp.route("/stream")
def stream():
    """Server-Sent Events: live traffic + node status every 2s (login required)."""
    user = _current_user()
    if not user:
        return jsonify({"error": "login required"}), 401
    from flask import Response, stream_with_context
    import time

    def gen():
        while True:
            nodes = ProxyNode.get_active_nodes(level=user.level)
            payload = {
                "used": user.used_traffic,
                "total": user.total_traffic,
                "nodes": [{"id": n.id, "online": n.is_online(),
                           "used": n.used_traffic or 0} for n in nodes],
            }
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(2)

    return Response(stream_with_context(gen()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/docs")
def api_docs():
    """Human-readable API documentation page."""
    return render_template("docs.html", user=_current_user())


@bp.route("/openapi.json")
def openapi_json():
    """OpenAPI 3.0 spec."""
    from .openapi import SPEC
    return jsonify(SPEC)


@bp.route("/swagger")
def swagger_ui():
    """Swagger UI (CDN) for the OpenAPI spec."""
    return render_template("swagger.html", user=_current_user())


@bp.route("/system_status")
def system_status():
    user = _current_user()
    if not user or not user.is_admin:
        return jsonify({"error": "admin required"}), 403
    total_users = User.query.count()
    today = datetime.utcnow().date()
    today_users = User.query.filter(User.created_at >= datetime(today.year, today.month, today.day)).count()
    total_orders = UserOrder.query.count()
    paid_orders = UserOrder.query.filter(UserOrder.status == UserOrder.STATUS_FINISHED).count()
    total_traffic = ProxyNode.calc_total_traffic()
    revenue = db.session.query(db.func.sum(UserOrder.amount)).filter(
        UserOrder.status == UserOrder.STATUS_FINISHED).scalar() or 0.0
    online_nodes = sum(1 for n in ProxyNode.query.all() if n.is_online())
    return jsonify({
        "total_users": total_users,
        "today_users": today_users,
        "total_orders": total_orders,
        "paid_orders": paid_orders,
        "total_traffic": total_traffic,
        "revenue": round(revenue, 2),
        "online_nodes": online_nodes,
        "nodes": [n.to_dict() for n in ProxyNode.query.all()],
    })


# ---------- admin CRUD ----------

def _admin_required():
    user = _current_user()
    if not user or not user.is_admin:
        return None
    return user


def _audit(action, detail=""):
    """Record an admin action in the audit log."""
    user = _current_user()
    if user:
        AuditLog.log(user.id, action, detail)


@bp.route("/admin/nodes", methods=["POST"])
def admin_add_node():
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    data = request.get_json(force=True, silent=True) or request.form
    node = ProxyNode(
        name=data.get("name", ""),
        server=data.get("server", ""),
        node_type=data.get("node_type", "ss"),
        ss_method=data.get("ss_method", "aes-256-gcm"),
        ss_port=int(data.get("ss_port", 8388)),
        country=data.get("country", "CN"),
        level=int(data.get("level", 0)),
        uuid=data.get("uuid", ""),
        trojan_password=data.get("trojan_password", ""),
        total_traffic=int(float(data.get("total_traffic_gb", 1000)) * GB),
        sequence=int(data.get("sequence", 0)),
    )
    db.session.add(node)
    db.session.commit()
    _audit("node.add", node.name)
    return jsonify({"status": "success", "node": node.to_dict()})


@bp.route("/admin/nodes/<int:node_id>", methods=["DELETE"])
def admin_delete_node(node_id):
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    node = ProxyNode.query.get(node_id)
    if not node:
        return jsonify({"error": "not found"}), 404
    db.session.delete(node)
    db.session.commit()
    _audit("node.delete", f"#{node_id}")
    return jsonify({"status": "success"})


@bp.route("/admin/nodes/<int:node_id>/toggle", methods=["POST"])
def admin_toggle_node(node_id):
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    node = ProxyNode.query.get(node_id)
    if not node:
        return jsonify({"error": "not found"}), 404
    node.enable = not node.enable
    db.session.commit()
    _audit("node.toggle", f"#{node_id} enable={node.enable}")
    return jsonify({"status": "success", "enable": node.enable})


@bp.route("/admin/goods", methods=["POST"])
def admin_add_goods():
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    data = request.get_json(force=True, silent=True) or request.form
    goods = Goods(
        name=data.get("name", "New plan"),
        content=data.get("content", ""),
        transfer=int(float(data.get("transfer_gb", 10)) * GB),
        money=float(data.get("money", 0)),
        level=int(data.get("level", 0)),
        days=int(data.get("days", 30)),
        order=int(data.get("order", 99)),
    )
    db.session.add(goods)
    db.session.commit()
    _audit("goods.add", goods.name)
    return jsonify({"status": "success", "goods": goods.to_dict()})


@bp.route("/admin/goods/<int:goods_id>", methods=["DELETE"])
def admin_delete_goods(goods_id):
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    goods = Goods.query.get(goods_id)
    if not goods:
        return jsonify({"error": "not found"}), 404
    db.session.delete(goods)
    db.session.commit()
    _audit("goods.delete", f"#{goods_id}")
    return jsonify({"status": "success"})


@bp.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
def admin_toggle_user(user_id):
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "not found"}), 404
    user.enable = not user.enable
    db.session.commit()
    _audit("user.toggle", f"#{user_id} enable={user.enable}")
    return jsonify({"status": "success", "enable": user.enable})


@bp.route("/admin/users/<int:user_id>/reset_traffic", methods=["POST"])
def admin_reset_traffic(user_id):
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    user = User.query.get(user_id)
    if not user:
        return jsonify({"error": "not found"}), 404
    user.reset_traffic(user.total_traffic)
    user.enable = True
    db.session.commit()
    _audit("user.reset_traffic", f"#{user_id}")
    return jsonify({"status": "success"})


@bp.route("/admin/analytics")
def admin_analytics():
    """Revenue + user-growth trends over the last N days (admin)."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    days = min(request.args.get("days", 14, type=int), 90)
    today = datetime.utcnow().date()
    labels, revenue, users = [], [], []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        start = datetime(day.year, day.month, day.day)
        end = start + timedelta(days=1)
        labels.append(day.isoformat())
        rev = db.session.query(db.func.sum(UserOrder.amount)).filter(
            UserOrder.status == UserOrder.STATUS_FINISHED,
            UserOrder.created_at >= start,
            UserOrder.created_at < end,
        ).scalar() or 0.0
        revenue.append(round(rev, 2))
        users.append(User.query.filter(
            User.created_at >= start, User.created_at < end).count())
    return jsonify({"labels": labels, "revenue": revenue, "users": users})


@bp.route("/admin/export/users")
def admin_export_users():
    """CSV export of all users (admin)."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "username", "email", "level", "balance", "ss_port",
                "upload_bytes", "download_bytes", "total_bytes", "enable", "created_at"])
    for u in User.query.order_by(User.id).all():
        w.writerow([u.id, u.username, u.email, u.level, u.balance, u.ss_port,
                    u.upload_traffic, u.download_traffic, u.total_traffic,
                    u.enable, u.created_at.isoformat() if u.created_at else ""])
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=users.csv"},
    )


@bp.route("/admin/export/orders")
def admin_export_orders():
    """CSV export of all orders (admin)."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "user_id", "goods_id", "status", "amount", "out_trade_no", "created_at"])
    for o in UserOrder.query.order_by(UserOrder.id).all():
        w.writerow([o.id, o.user_id, o.goods_id, o.status, o.amount, o.out_trade_no,
                    o.created_at.isoformat() if o.created_at else ""])
    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=orders.csv"},
    )


@bp.route("/admin/invites", methods=["GET"])
def admin_invites():
    """List invite codes (admin)."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    codes = InviteCode.query.order_by(InviteCode.id.desc()).limit(100).all()
    return jsonify({"codes": [c.to_dict() for c in codes]})


@bp.route("/admin/invites", methods=["POST"])
def admin_invite_create():
    """Create N invite codes (admin)."""
    admin = _admin_required()
    if not admin:
        return jsonify({"error": "admin required"}), 403
    n = request.get_json(force=True, silent=True) or {}
    count = max(1, min(int(n.get("count", 1)), 100))
    codes = []
    for _ in range(count):
        code = InviteCode(code=InviteCode.random_code(), user_id=admin.id)
        db.session.add(code)
        codes.append(code)
    db.session.commit()
    _audit("invite.create", f"{count} codes")
    return jsonify({"status": "success", "codes": [c.to_dict() for c in codes]})


@bp.route("/admin/invites/<int:code_id>", methods=["DELETE"])
def admin_invite_delete(code_id):
    """Delete an invite code (admin)."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    code = InviteCode.query.get(code_id)
    if not code:
        return jsonify({"error": "not found"}), 404
    db.session.delete(code)
    db.session.commit()
    _audit("invite.delete", f"#{code_id}")
    return jsonify({"status": "success"})


@bp.route("/admin/audit")
def admin_audit():
    """Recent admin audit log entries (admin)."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    limit = min(request.args.get("limit", 50, type=int), 200)
    entries = AuditLog.query.order_by(AuditLog.id.desc()).limit(limit).all()
    return jsonify({"entries": [e.to_dict() for e in entries]})


@bp.route("/admin/backup")
def admin_backup():
    """Full JSON backup of users, nodes, goods, orders (admin)."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    from datetime import datetime as _dt
    backup = {
        "version": VERSION,
        "exported_at": _dt.utcnow().isoformat(),
        "users": [u.to_dict() for u in User.query.all()],
        "nodes": [n.to_dict() for n in ProxyNode.query.all()],
        "goods": [g.to_dict() for g in Goods.query.all()],
        "orders": [o.to_dict() for o in UserOrder.query.all()],
    }
    from flask import Response
    return Response(
        json.dumps(backup, indent=2, default=str),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=fluxgate-backup.json"},
    )


@bp.route("/admin/restore", methods=["POST"])
def admin_restore():
    """Restore from a JSON backup (admin). Wipes current data."""
    if not _admin_required():
        return jsonify({"error": "admin required"}), 403
    data = request.get_json(force=True, silent=True)
    if not data or "users" not in data:
        return jsonify({"error": "invalid backup"}), 400
    # wipe
    for m in (UserOrder, User, ProxyNode, Goods):
        db.session.query(m).delete()
    db.session.commit()
    # restore users
    for u in data.get("users", []):
        user = User(username=u["username"], email=u.get("email", ""),
                    ss_port=u.get("ss_port", 1025), ss_password=u.get("ss_password", ""),
                    vmess_uuid=u.get("vmess_uuid", ""), balance=u.get("balance", 0),
                    level=u.get("level", 0), upload_traffic=u.get("upload_traffic", 0),
                    download_traffic=u.get("download_traffic", 0),
                    total_traffic=u.get("total_traffic", GB * 10),
                    enable=u.get("enable", True), is_admin=u.get("is_admin", False),
                    api_key=u.get("api_key", ""))
        user.password_hash = u.get("password_hash", "")
        db.session.add(user)
    for n in data.get("nodes", []):
        server = n.get("server", "")
        if isinstance(server, list):
            server = ",".join(server)
        db.session.add(ProxyNode(name=n.get("name", ""), server=server,
                                 node_type=n.get("node_type", "ss"), ss_port=n.get("port", 8388),
                                 ss_method=n.get("method", "aes-256-gcm"),
                                 country=n.get("country", "CN"), level=n.get("level", 0),
                                 used_traffic=n.get("used_traffic", 0),
                                 total_traffic=n.get("total_traffic", GB),
                                 enable=n.get("enable", True)))
    for g in data.get("goods", []):
        db.session.add(Goods(name=g.get("name", ""), content=g.get("content", ""),
                             transfer=g.get("transfer", GB), money=g.get("money", 0),
                             level=g.get("level", 0), days=g.get("days", 30),
                             status=g.get("status", 1)))
    for o in data.get("orders", []):
        db.session.add(UserOrder(user_id=o.get("user_id", 0), goods_id=o.get("goods_id", 0),
                                 status=o.get("status", 0), amount=o.get("amount", 0),
                                 out_trade_no=o.get("out_trade_no", "")))
    db.session.commit()
    _audit("backup.restore", f"{len(data.get('users', []))} users, {len(data.get('nodes', []))} nodes")
    return jsonify({"status": "success",
                    "restored": {"users": len(data.get("users", [])),
                                 "nodes": len(data.get("nodes", [])),
                                 "goods": len(data.get("goods", [])),
                                 "orders": len(data.get("orders", []))}})
