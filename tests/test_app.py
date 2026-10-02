"""End-to-end tests for fluxgate. Run: python tests/test_app.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fluxgate import create_app, db, GB
from fluxgate.models import User, Goods, UserOrder, InviteCode, UserCheckInLog
from fluxgate.proxy import ProxyNode, UserTrafficLog
from fluxgate.sub import generate_subscription, generate_clash_config


@pytest.fixture()
def app():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp.name}",
        "SECRET_KEY": "test",
        "API_TOKEN": "test-token",
    })
    from fluxgate.web import _login_attempts
    _login_attempts.clear()  # fresh rate-limiter state per test
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    try:
        os.unlink(tmp.name)
    except PermissionError:
        pass


@pytest.fixture()
def client(app):
    return app.test_client()


def _login(client, username="demo", password="demo123"):
    client.get("/login")  # seed session CSRF token
    with client.session_transaction() as s:
        token = s.get("_csrf", "")
    return client.post("/login", data={"username": username, "password": password, "_csrf": token})


# ---------- core model tests ----------

def test_seed_data(app):
    with app.app_context():
        assert User.query.filter_by(username="admin").first().is_admin
        assert User.query.filter_by(username="demo").first() is not None
        assert ProxyNode.query.count() == 3
        assert Goods.query.count() == 4


def test_user_register_with_invite(app):
    with app.app_context():
        inviter = User.query.filter_by(username="demo").first()
        code = InviteCode.gen_codes(inviter.id, 1)[0]
        user = User.add_new_user("newbie", "n@x.com", "pass123", invitecode=code.code)
        assert user.inviter_id == inviter.id
        assert code.consumed
        assert user.ss_port >= User.MIN_PORT
        assert user.vmess_uuid


def test_register_duplicate_username(app, client):
    client.get("/register")
    with client.session_transaction() as s:
        token = s.get("_csrf", "")
    r = client.post("/register", data={"username": "demo", "email": "x@x.com", "password": "x", "_csrf": token})
    assert "Username already exists" in r.get_data(as_text=True)


def test_login_logout(app, client):
    r = _login(client)
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]
    client.get("/logout")
    r2 = client.get("/dashboard")
    assert r2.status_code == 302


def test_checkin_once_per_day(app, client):
    _login(client)
    r1 = client.post("/api/checkin")
    assert r1.get_json()["status"] == "success"
    r2 = client.post("/api/checkin")
    assert r2.get_json()["status"] == "error"


def test_traffic_overflow_disables_user(app):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        user.total_traffic = 100
        user.upload_traffic = 60
        user.download_traffic = 60
        db.session.commit()
        assert user.overflow
        assert user.enable is True  # not yet disabled
    # simulate backend traffic report
    with app.test_client() as c:
        c.post("/api/proxy_configs/1", json={"data": [{"user_id": 2, "upload": 10, "download": 10}]},
               headers={"X-API-Token": "test-token"})
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        assert user.enable is False


# ---------- subscription tests ----------

def test_subscribe_ss(app, client):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        r = client.get(f"/api/subscribe?token={user.token}&sub_type=ss")
        assert r.status_code == 200
        import base64
        decoded = base64.b64decode(r.get_data()).decode()
        assert "ss://" in decoded
        assert "hk01.example.com" in decoded


def test_subscribe_v2ray(app, client):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        r = client.get(f"/api/subscribe?token={user.token}&sub_type=v2ray")
        import base64, json
        decoded = base64.b64decode(r.get_data()).decode()
        assert "vmess://" in decoded


def test_subscribe_clash(app, client):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        r = client.get(f"/api/subscribe?token={user.token}&sub_type=clash")
        assert r.status_code == 200
        assert "proxies:" in r.get_data(as_text=True)
        assert "proxy-groups:" in r.get_data(as_text=True)


def test_subscribe_level_gating(app):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        user.level = 0
        db.session.commit()
        nodes = ProxyNode.get_active_nodes(level=0)
        assert all(n.level <= 0 for n in nodes)
        assert len(nodes) == 2  # US-03 is level 1


def test_subscribe_invalid_token(app, client):
    assert client.get("/api/subscribe?token=999999").status_code == 404
    assert client.get("/api/subscribe").status_code == 404


# ---------- order / payment tests ----------

def test_create_order_and_callback(app, client):
    _login(client)
    with app.app_context():
        goods = Goods.query.first()
        goods_id = goods.id
    r = client.post("/api/orders", json={"goods_id": goods_id})
    order = r.get_json()["order"]
    assert order["status"] == 0
    r2 = client.post("/api/callback/alipay", json={"out_trade_no": order["out_trade_no"]})
    assert r2.get_json()["status"] == "success"
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        assert user.total_traffic > GB * 20  # granted goods transfer


def test_order_requires_login(app, client):
    r = client.post("/api/orders", json={"goods_id": 1})
    assert r.status_code == 401


def test_proxy_configs_requires_auth(app, client):
    r = client.get("/api/proxy_configs/1")
    assert r.status_code == 401
    r2 = client.get("/api/proxy_configs/1", headers={"X-API-Token": "test-token"})
    assert r2.status_code == 200
    assert r2.get_json()["node_type"] == "ss"


def test_traffic_report_updates_user(app, client):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        before = user.used_traffic
    r = client.post("/api/proxy_configs/1", json={"data": [{"user_id": 2, "upload": 5, "download": 7}]},
                    headers={"X-API-Token": "test-token"})
    assert r.status_code == 200
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        assert user.used_traffic == before + 12
        assert UserTrafficLog.query.count() >= 1


def test_admin_required(app, client):
    _login(client, "demo", "demo123")
    assert client.get("/api/system_status").status_code == 403
    _login(client, "admin", "admin123")
    r = client.get("/api/system_status")
    assert r.status_code == 200
    assert "total_users" in r.get_json()


# ---------- web pages ----------

def test_pages_render(app, client):
    _login(client)
    for path in ["/dashboard", "/shop"]:
        assert client.get(path).status_code == 200
    _login(client, "admin", "admin123")
    assert client.get("/admin").status_code == 200


def test_user_settings_change_password(app, client):
    _login(client)
    r = client.post("/api/user/settings", data={"ss_password": "newpass123"})
    assert r.get_json()["status"] == "success"
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        assert user.ss_password == "newpass123"


def test_gen_invitecode(app, client):
    _login(client)
    r = client.post("/api/gen/invitecode", data={"num": 1})
    assert r.get_json()["status"] == "success"
    assert len(r.get_json()["codes"]) == 1


# ---------- admin CRUD ----------

def test_admin_add_node(app, client):
    _login(client, "admin", "admin123")
    r = client.post("/api/admin/nodes", json={
        "name": "SG-04", "server": "sg04.example.com", "node_type": "ss",
        "ss_port": 9000, "total_traffic_gb": 500,
    })
    assert r.get_json()["status"] == "success"
    assert r.get_json()["node"]["name"] == "SG-04"
    with app.app_context():
        assert ProxyNode.query.filter_by(name="SG-04").first() is not None


def test_admin_node_toggle_delete(app, client):
    _login(client, "admin", "admin123")
    with app.app_context():
        nid = ProxyNode.query.first().id
    r = client.post(f"/api/admin/nodes/{nid}/toggle")
    assert r.get_json()["enable"] is False
    r = client.delete(f"/api/admin/nodes/{nid}")
    assert r.get_json()["status"] == "success"
    with app.app_context():
        assert ProxyNode.query.get(nid) is None


def test_admin_add_delete_goods(app, client):
    _login(client, "admin", "admin123")
    r = client.post("/api/admin/goods", json={"name": "测试包", "transfer_gb": 5, "money": 2, "days": 7})
    assert r.get_json()["status"] == "success"
    gid = r.get_json()["goods"]["id"]
    r = client.delete(f"/api/admin/goods/{gid}")
    assert r.get_json()["status"] == "success"


def test_admin_user_toggle_reset(app, client):
    _login(client, "admin", "admin123")
    with app.app_context():
        demo = User.query.filter_by(username="demo").first()
        demo.upload_traffic = 5 * GB
        db.session.commit()
        uid = demo.id
    r = client.post(f"/api/admin/users/{uid}/toggle")
    assert r.get_json()["enable"] is False
    r = client.post(f"/api/admin/users/{uid}/reset_traffic")
    assert r.get_json()["status"] == "success"
    with app.app_context():
        demo = User.query.get(uid)
        assert demo.upload_traffic == 0
        assert demo.enable is True


def test_admin_crud_requires_admin(app, client):
    _login(client, "demo", "demo123")
    assert client.post("/api/admin/nodes", json={}).status_code == 403
    assert client.delete("/api/admin/nodes/1").status_code == 403
    assert client.post("/api/admin/users/1/toggle").status_code == 403


def test_system_status_has_revenue_and_online(app, client):
    _login(client, "admin", "admin123")
    r = client.get("/api/system_status")
    d = r.get_json()
    assert "revenue" in d
    assert "online_nodes" in d
    assert "online" in d["nodes"][0]


def test_node_heartbeat_marks_online(app, client):
    with app.app_context():
        node = ProxyNode.query.first()
        assert node.is_online() is False  # no heartbeat yet
    client.post("/api/proxy_configs/1", json={"data": []}, headers={"X-API-Token": "test-token"})
    with app.app_context():
        node = ProxyNode.query.first()
        assert node.is_online() is True


# ---------- analytics + exports ----------

def test_admin_analytics(app, client):
    _login(client, "admin", "admin123")
    r = client.get("/api/admin/analytics?days=7")
    assert r.status_code == 200
    d = r.get_json()
    assert len(d["labels"]) == 7
    assert len(d["revenue"]) == 7
    assert len(d["users"]) == 7


def test_admin_analytics_requires_admin(app, client):
    _login(client, "demo", "demo123")
    assert client.get("/api/admin/analytics").status_code == 403


def test_admin_export_users_csv(app, client):
    _login(client, "admin", "admin123")
    r = client.get("/api/admin/export/users")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert "username" in r.get_data(as_text=True)
    assert "demo" in r.get_data(as_text=True)


def test_admin_export_orders_csv(app, client):
    _login(client, "admin", "admin123")
    r = client.get("/api/admin/export/orders")
    assert r.status_code == 200
    assert r.mimetype == "text/csv"
    assert "out_trade_no" in r.get_data(as_text=True)


def test_admin_export_requires_admin(app, client):
    _login(client, "demo", "demo123")
    assert client.get("/api/admin/export/users").status_code == 403
    assert client.get("/api/admin/export/orders").status_code == 403


# ---------- login rate limiting ----------

def test_login_rate_limit(app, client):
    client.get("/login")
    with client.session_transaction() as s:
        token = s.get("_csrf", "")
    for _ in range(5):
        client.post("/login", data={"username": "demo", "password": "wrong", "_csrf": token})
    r = client.post("/login", data={"username": "demo", "password": "demo123", "_csrf": token})
    assert r.status_code == 429
    assert "Too many attempts" in r.get_data(as_text=True)


def test_login_rate_limit_resets_after_window(app, client):
    from fluxgate.web import _login_attempts, _rate_limited
    with app.app_context():
        _login_attempts.clear()
    # simulate old attempts outside the window
    from datetime import datetime, timedelta
    with app.app_context():
        _login_attempts["127.0.0.1"] = [datetime.utcnow() - timedelta(seconds=400)] * 5
        assert _rate_limited("127.0.0.1") is False  # expired, allowed again


# ---------- QR / metrics / webhook / docs ----------

def test_subscribe_qr(app, client):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        r = client.get(f"/api/subscribe/qr?token={user.id}&sub_type=ss")
        assert r.status_code == 200
        assert r.mimetype == "image/png"
        assert r.data[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic


def test_subscribe_qr_invalid_token(app, client):
    assert client.get("/api/subscribe/qr?token=999999").status_code == 404


def test_metrics_endpoint(app, client):
    r = client.get("/api/metrics")
    assert r.status_code == 200
    txt = r.get_data(as_text=True)
    assert "fluxgate_users_total" in txt
    assert "fluxgate_revenue_total" in txt
    assert "fluxgate_nodes_online" in txt
    assert "fluxgate_traffic_bytes_total" in txt


def test_webhook_fires_on_paid(app):
    """WEBHOOK_URL set -> order.paid POSTed (fire-and-forget)."""
    import threading
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received["body"] = _json.loads(self.rfile.read(length))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        app.config["WEBHOOK_URL"] = f"http://127.0.0.1:{port}/hook"
        with app.test_client() as c:
            _login(c)
            r = c.post("/api/orders", json={"goods_id": 1})
            out_trade_no = r.get_json()["order"]["out_trade_no"]
            c.post("/api/callback/alipay", json={"out_trade_no": out_trade_no})
        import time
        for _ in range(20):
            if received.get("body"):
                break
            time.sleep(0.1)
        check_webhook = received.get("body")
        assert check_webhook and check_webhook["event"] == "order.paid"
        assert check_webhook["out_trade_no"] == out_trade_no
    finally:
        srv.shutdown()


def test_docs_page(app, client):
    _login(client)
    r = client.get("/api/docs")
    assert r.status_code == 200
    assert "API Documentation" in r.get_data(as_text=True)


def test_sse_stream_requires_login(app, client):
    assert client.get("/api/stream").status_code == 401


def test_sse_stream_emits_events(app, client):
    _login(client)
    r = client.get("/api/stream")
    assert r.status_code == 200
    assert r.mimetype == "text/event-stream"
    # pull one chunk from the generator directly (stream is infinite)
    gen = r.response
    chunk = next(gen)
    assert b"data: " in chunk
    assert b"nodes" in chunk


# ---------- Telegram bot ----------

def _fake_db():
    return {
        "2": {"username": "demo", "level": 0,
              "human_remain": "19.91 GB", "human_used": "91.43 MB",
              "human_total": "20.00 GB", "sub_link": "http://x/sub?token=2",
              "is_admin": False, "checkin": "Checked in! +50 MB",
              "stats": {"total_users": 2, "revenue": 10.0, "total_nodes": 3, "online_nodes": 2}},
        "1": {"username": "admin", "level": 9,
              "human_remain": "100.00 GB", "human_used": "0 B",
              "human_total": "100.00 GB", "sub_link": "http://x/sub?token=1",
              "is_admin": True, "checkin": "Already checked in today!",
              "stats": {"total_users": 2, "revenue": 10.0, "total_nodes": 3, "online_nodes": 2}},
    }


def test_bot_commands():
    from bot import handle_update
    db = _fake_db()
    # fresh links file (no stale state from prior runs)
    import bot as botmod
    botmod._LINKS_FILE = os.path.join(tempfile.gettempdir(), "hermes-tg-links-test.json")
    if os.path.exists(botmod._LINKS_FILE):
        os.unlink(botmod._LINKS_FILE)
    # /start
    r = handle_update({"message": {"chat": {"id": 1}, "text": "/start"}}, lambda: db)
    assert "FluxGate bot" in r
    # /traffic without link
    r = handle_update({"message": {"chat": {"id": 1}, "text": "/traffic"}}, lambda: db)
    assert "Link your account" in r
    # /link + /traffic (link persists to tg_links.json)
    r = handle_update({"message": {"chat": {"id": 1}, "text": "/link 2"}}, lambda: db)
    assert "Linked" in r
    r = handle_update({"message": {"chat": {"id": 1}, "text": "/traffic"}}, lambda: db)
    assert "Remaining: 19.91 GB" in r
    # /subscribe
    r = handle_update({"message": {"chat": {"id": 1}, "text": "/subscribe"}}, lambda: db)
    assert "Subscription" in r
    # /stats non-admin -> admin only
    r = handle_update({"message": {"chat": {"id": 1}, "text": "/stats"}}, lambda: db)
    assert "Admin only" in r
    # /stats as admin (chat 2 linked to admin)
    botmod._LINKS_FILE = os.path.join(tempfile.gettempdir(), "hermes-tg-links-test2.json")
    if os.path.exists(botmod._LINKS_FILE):
        os.unlink(botmod._LINKS_FILE)
    r = handle_update({"message": {"chat": {"id": 2}, "text": "/link 1"}}, lambda: db)
    assert "Linked" in r
    r = handle_update({"message": {"chat": {"id": 2}, "text": "/stats"}}, lambda: db)
    assert "2 users" in r
    # unknown
    r = handle_update({"message": {"chat": {"id": 1}, "text": "/nope"}}, lambda: db)
    assert "Unknown command" in r


def test_bot_demo_mode_runs(app):
    """bot.py main() in DEMO_MODE (no token) prints, doesn't crash."""
    import subprocess
    import tempfile as _tf
    tmpdb = _tf.NamedTemporaryFile(suffix=".db", delete=False)
    tmpdb.close()
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmpdb.name}")
    r = subprocess.run([sys.executable, "bot.py"], capture_output=True, text=True,
                       cwd=r"C:\Users\priya\Desktop\sspanel-flask", timeout=60, env=env)
    try:
        os.unlink(tmpdb.name)
    except PermissionError:
        pass
    assert r.returncode == 0, r.stderr[-500:]
    assert "DEMO_MODE" in r.stdout


# ---------- payments ----------

def test_payment_demo_provider(app, client):
    """Default provider (demo) returns no payment_url — callback confirms."""
    _login(client)
    r = client.post("/api/orders", json={"goods_id": 1})
    d = r.get_json()
    assert d["status"] == "success"
    assert "payment_url" not in d  # demo auto-confirms


def test_payment_stripe_provider_no_key(app, client):
    """Stripe provider without key falls back to demo behavior."""
    app.config["PAYMENT_PROVIDER"] = "stripe"
    _login(client)
    r = client.post("/api/orders", json={"goods_id": 1})
    assert r.get_json()["status"] == "success"


def test_telegram_notify_fires(app):
    """TELEGRAM_BOT_TOKEN+CHAT_ID set -> sendMessage attempted (fire-and-forget)."""
    import threading
    import json as _json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received["body"] = _json.loads(self.rfile.read(length))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # point the bot API at our local server via monkeypatched urllib
    import urllib.request as _ur
    orig = _ur.urlopen
    try:
        def fake_urlopen(req, timeout=5):
            return orig(_ur.Request(
                f"http://127.0.0.1:{port}/sendMessage",
                data=req.data, headers=req.headers), timeout=timeout)
        _ur.urlopen = fake_urlopen
        app.config["TELEGRAM_BOT_TOKEN"] = "test-token"
        app.config["TELEGRAM_CHAT_ID"] = "123"
        with app.test_client() as c:
            _login(c)
            r = c.post("/api/orders", json={"goods_id": 1})
            out_trade_no = r.get_json()["order"]["out_trade_no"]
            c.post("/api/callback/alipay", json={"out_trade_no": out_trade_no})
        import time
        for _ in range(20):
            if received.get("body"):
                break
            time.sleep(0.1)
        assert received.get("body"), "telegram sendMessage not fired"
        assert "Order paid" in received["body"]["text"]
    finally:
        _ur.urlopen = orig
        srv.shutdown()


# ---------- API keys / password / uptime ----------

def test_subscribe_via_api_key(app, client):
    with app.app_context():
        user = User.query.filter_by(username="demo").first()
        key = user.api_key
        assert key
        r = client.get(f"/api/subscribe?api_key={key}&sub_type=ss")
        assert r.status_code == 200
        assert "ss://" in __import__("base64").b64decode(r.get_data()).decode()


def test_regenerate_api_key(app, client):
    _login(client)
    with app.app_context():
        old = User.query.filter_by(username="demo").first().api_key
    r = client.post("/api/user/api_key")
    assert r.get_json()["status"] == "success"
    with app.app_context():
        new = User.query.filter_by(username="demo").first().api_key
        assert new != old


def test_change_password(app, client):
    _login(client)
    r = client.post("/api/user/password", json={"current_password": "wrong", "new_password": "newpass1"})
    assert r.status_code == 400
    r = client.post("/api/user/password", json={"current_password": "demo123", "new_password": "newpass1"})
    assert r.get_json()["status"] == "success"
    # old password no longer works
    client.get("/logout")
    client.get("/login")  # reseed CSRF after logout
    with client.session_transaction() as s:
        token = s.get("_csrf", "")
    r = client.post("/login", data={"username": "demo", "password": "demo123", "_csrf": token})
    assert "Invalid username or password" in r.get_data(as_text=True)
    r = client.post("/login", data={"username": "demo", "password": "newpass1", "_csrf": token})
    assert r.status_code == 302


def test_node_uptime(app, client):
    with app.app_context():
        node = ProxyNode.query.first()
        assert node.uptime() == "0m"  # no heartbeat yet
        assert node.first_seen is None
    client.post("/api/proxy_configs/1", json={"data": []}, headers={"X-API-Token": "test-token"})
    with app.app_context():
        node = ProxyNode.query.first()
        assert node.first_seen is not None
        assert node.last_seen is not None


# ---------- landing + health ----------

def test_landing_page(app, client):
    r = client.get("/")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Self-hosted proxy panel" in html
    assert "Get started" in html
    assert "Simple pricing" in html


def test_landing_redirects_logged_in(app, client):
    _login(client)
    r = client.get("/")
    assert r.status_code == 302
    assert "/dashboard" in r.headers["Location"]


def test_health_endpoint(app, client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.get_json()
    assert d["status"] == "ok"
    assert d["db"] == "up"
    assert d["version"] == "0.6.0"


def test_uptime_formats(app):
    from datetime import datetime, timedelta
    with app.app_context():
        node = ProxyNode.query.first()
        node.first_seen = datetime.utcnow() - timedelta(days=3, hours=4)
        assert node.uptime() == "3d 4h"
        node.first_seen = datetime.utcnow() - timedelta(hours=5, minutes=30)
        assert node.uptime() == "5h 30m"
        node.first_seen = datetime.utcnow() - timedelta(minutes=45)
        assert node.uptime() == "45m"


def test_traffic_format_units():
    from fluxgate.models import traffic_format
    assert traffic_format(500) == "500.00 B"
    assert traffic_format(2048) == "2.00 KB"
    assert traffic_format(5 * 1024 * 1024) == "5.00 MB"
    assert traffic_format(3 * 1024 ** 3) == "3.00 GB"
    assert traffic_format(2 * 1024 ** 4) == "2.00 TB"


def test_subscribe_invalid_api_key(app, client):
    r = client.get("/api/subscribe?api_key=nonexistent")
    assert r.status_code == 404


def test_change_password_short(app, client):
    _login(client)
    r = client.post("/api/user/password", json={"current_password": "demo123", "new_password": "abc"})
    assert r.status_code == 400
    assert "too short" in r.get_json()["title"].lower()


# ---------- security / openapi / swagger ----------

def test_login_requires_csrf(app, client):
    """POST without CSRF token is rejected."""
    r = client.post("/login", data={"username": "demo", "password": "demo123"})
    assert r.status_code == 400
    assert "Invalid form token" in r.get_data(as_text=True)


def test_login_with_csrf(app, client):
    # GET login page to seed the session CSRF token
    client.get("/login")
    with client.session_transaction() as s:
        token = s["_csrf"]
    r = client.post("/login", data={"username": "demo", "password": "demo123", "_csrf": token})
    assert r.status_code == 302


def test_register_requires_csrf(app, client):
    r = client.post("/register", data={"username": "x", "password": "y"})
    assert r.status_code == 400


def test_session_cookie_flags(app, client):
    # first GET renders login (csrf_token() modifies session) -> Set-Cookie emitted
    r = client.get("/login")
    set_cookie = r.headers.get("Set-Cookie", "")
    assert "HttpOnly" in set_cookie
    assert "SameSite=Lax" in set_cookie


def test_openapi_spec(app, client):
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    d = r.get_json()
    assert d["openapi"] == "3.0.3"
    assert "/api/subscribe" in d["paths"]
    assert "ApiToken" in d["components"]["securitySchemes"]


def test_swagger_ui(app, client):
    r = client.get("/api/swagger")
    assert r.status_code == 200
    assert "SwaggerUIBundle" in r.get_data(as_text=True)


def test_favicon(app, client):
    r = client.get("/static/favicon.svg")
    assert r.status_code == 200
    assert b"<svg" in r.data


def test_admin_page_has_search(app, client):
    _login(client, "admin", "admin123")
    r = client.get("/admin")
    html = r.get_data(as_text=True)
    assert 'id="userSearch"' in html
    assert 'id="usersTable"' in html


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
