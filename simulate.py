"""Demo data simulator — generates realistic usage so the panel looks alive.

Creates N users with staggered signup dates, purchase history across the
last 30 days, per-node traffic curves (diurnal pattern), and node heartbeats.

Usage:
    .venv/Scripts/python simulate.py [users] [days]
"""
import random
import sys
from datetime import datetime, timedelta

from fluxgate import create_app, db, GB
from fluxgate.models import Goods, User, UserOrder, UserRefLog, InviteCode
from fluxgate.proxy import ProxyNode, UserTrafficLog

NAMES = ["alice", "bob", "carol", "dave", "erin", "frank", "grace", "heidi",
         "ivan", "judy", "mallory", "nina", "oscar", "peggy", "rupert", "sybil",
         "trent", "victor", "walter", "xenia", "yuki", "zane", "aria", "leo",
         "mila", "kai", "nora", "felix", "luna", "max"]


def diurnal(day_hour: int) -> float:
    """Traffic multiplier peaking at 21:00, trough at 05:00 (UTC)."""
    return 0.25 + 0.75 * (0.5 - 0.5 * __import__("math").cos(2 * 3.14159 * (day_hour - 21) / 24))


def run(users_n: int = 24, days: int = 30):
    app = create_app()
    with app.app_context():
        goods = Goods.query.all()
        nodes = ProxyNode.query.all()
        if not goods or not nodes:
            print("seed first: run.py once, then simulate.py")
            return

        rng = random.Random(42)
        now = datetime.utcnow()

        # --- users with staggered signups ---
        for i in range(users_n):
            name = NAMES[i % len(NAMES)]
            if User.query.filter_by(username=name).first():
                continue
            signup = now - timedelta(days=rng.randint(1, days), hours=rng.randint(0, 23))
            user = User(
                username=name,
                email=f"{name}@example.com",
                ss_port=User.get_not_used_port(),
                vmess_uuid=f"{rng.randint(0, 0xffffffff):08x}-{rng.randint(0, 0xffff):04x}-4{rng.randint(0, 0xfff):03x}-8{rng.randint(0, 0xfff):03x}-{rng.randint(0, 0xffffffffffff):012x}",
                total_traffic=GB * rng.choice([10, 20, 50, 100, 500]),
                created_at=signup,
            )
            user.set_password("demo123")
            db.session.add(user)
            db.session.flush()

            # purchases over their lifetime
            n_orders = rng.randint(1, 5)
            for _ in range(n_orders):
                g = rng.choice(goods)
                when = signup + timedelta(days=rng.randint(0, max(1, (now - signup).days)))
                if when > now:
                    continue
                order = UserOrder(
                    user_id=user.id,
                    goods_id=g.id,
                    status=UserOrder.STATUS_FINISHED,
                    out_trade_no=UserOrder.gen_out_trade_no(),
                    amount=g.money,
                    created_at=when,
                    expired_at=when + timedelta(minutes=10),
                )
                db.session.add(order)
                user.total_traffic += g.transfer

            # referral log for a few
            if rng.random() < 0.4 and i > 0:
                db.session.add(UserRefLog(user_id=user.id, date=signup.date()))

        db.session.commit()

        # --- traffic curves: per user per node, diurnal, last `days` days ---
        users = User.query.filter(User.username != "admin").all()
        for user in users:
            for node in nodes:
                for d in range(days):
                    day = now - timedelta(days=d)
                    # skip days before signup
                    if user.created_at.date() > day.date():
                        continue
                    for h in range(0, 24, 3):
                        ts = day.replace(hour=h)
                        if ts > now:
                            continue
                        mult = diurnal(h)
                        up = int(rng.uniform(1, 8) * 1024 * 1024 * mult)
                        down = int(rng.uniform(2, 20) * 1024 * 1024 * mult)
                        db.session.add(UserTrafficLog(
                            user_id=user.id, node_id=node.id,
                            upload=up, download=down, created_at=ts))
                        user.upload_traffic = (user.upload_traffic or 0) + up
                        user.download_traffic = (user.download_traffic or 0) + down
                        node.used_traffic = (node.used_traffic or 0) + up + down
                        user.last_use_time = ts
            db.session.commit()  # one commit per user, not per record

        # --- node heartbeats: all nodes online (last_seen now) ---
        for node in nodes:
            node.last_seen = now
        db.session.commit()

        total = User.query.count()
        orders = UserOrder.query.count()
        rev = db.session.query(db.func.sum(UserOrder.amount)).filter(
            UserOrder.status == UserOrder.STATUS_FINISHED).scalar() or 0
        print(f"simulated: {total} users, {orders} orders, ¥{rev:.2f} revenue, "
              f"{UserTrafficLog.query.count()} traffic samples")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    d = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    run(n, d)
