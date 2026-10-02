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
    return client.post("/login", data={"username": username, "password": password})


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
    r = client.post("/register", data={"username": "demo", "email": "x@x.com", "password": "x"})
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
    for _ in range(5):
        client.post("/login", data={"username": "demo", "password": "wrong"})
    r = client.post("/login", data={"username": "demo", "password": "demo123"})
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
            c.post("/login", data={"username": "demo", "password": "demo123"})
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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
