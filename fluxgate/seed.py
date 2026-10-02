"""Seed demo data so the panel is instantly demoable (mirrors the original's
create_admin management command + default goods)."""
from . import db, GB
from .models import Goods, User
from .proxy import ProxyNode


def seed(app):
    # admin user
    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            email="admin@example.com",
            ss_port=User.get_not_used_port(),
            vmess_uuid="00000000-0000-0000-0000-000000000000",
            total_traffic=GB * 100,
            is_admin=True,
            level=9,
        )
        admin.set_password("admin123")
        db.session.add(admin)

    # demo user
    if not User.query.filter_by(username="demo").first():
        demo = User(
            username="demo",
            email="demo@example.com",
            ss_port=User.get_not_used_port(),
            vmess_uuid="11111111-2222-3333-4444-555555555555",
            total_traffic=GB * 20,
        )
        demo.set_password("demo123")
        db.session.add(demo)

    # demo nodes
    if ProxyNode.query.count() == 0:
        db.session.add_all([
            ProxyNode(
                name="HK-01 Hong Kong",
                server="hk01.example.com",
                node_type="ss",
                ss_method="aes-256-gcm",
                ss_port=8388,
                country="HK",
                level=0,
                total_traffic=GB * 1000,
                sequence=1,
            ),
            ProxyNode(
                name="JP-02 Tokyo",
                server="jp02.example.com",
                node_type="vless",
                uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                ss_port=443,
                country="JP",
                level=0,
                total_traffic=GB * 1000,
                sequence=2,
            ),
            ProxyNode(
                name="US-03 Los Angeles",
                server="us03.example.com",
                node_type="trojan",
                trojan_password="trojan-demo-pass",
                ss_port=443,
                country="US",
                level=1,
                total_traffic=GB * 1000,
                sequence=3,
            ),
        ])

    # demo goods
    if Goods.query.count() == 0:
        db.session.add_all([
            Goods(name="Trial", content="10GB traffic / 7 days", transfer=GB * 10, money=1.0, days=7, level=0, order=1),
            Goods(name="Basic", content="100GB traffic / 30 days", transfer=GB * 100, money=5.0, days=30, level=0, order=2),
            Goods(name="Pro", content="500GB traffic / 90 days", transfer=GB * 500, money=20.0, days=90, level=1, order=3),
            Goods(name="Ultimate", content="1TB traffic / 365 days", transfer=GB * 1024, money=60.0, days=365, level=2, order=4),
        ])

    db.session.commit()
