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

from flask import Blueprint, current_app, jsonify, request, session

from . import db, GB
from .models import Goods, InviteCode, User, UserCheckInLog, UserOrder, UserRefLog
from .proxy import ProxyNode, UserTrafficLog
from .sub import generate_clash_config, generate_subscription

bp = Blueprint("api", __name__)


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
    if not token:
        return "not found", 404
    user = User.query.filter_by(id=int(token)).first() if token.isdigit() else None
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
    return jsonify({"status": "success", "order": order.to_dict()})


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
    return jsonify({"status": "success", "order": order.to_dict()})


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
    return jsonify({"status": "success"})
