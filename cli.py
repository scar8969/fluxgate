"""fluxgate — command-line admin for FluxGate.

Usage:
  python cli.py stats
  python cli.py users
  python cli.py user add <username> <password> [--admin] [--traffic 10G]
  python cli.py user reset <username>
  python cli.py nodes
  python cli.py node add <name> <server> [--port 8388] [--type ss]
  python cli.py goods
  python cli.py orders
  python cli.py backup <file.json>
  python cli.py restore <file.json>
"""
import argparse
import json
import sys
from datetime import datetime

from fluxgate import create_app, db, GB
from fluxgate.models import Goods, User, UserOrder
from fluxgate.proxy import AuditLog, ProxyNode

app = create_app()


def _fmt_gb(n):
    return f"{n / GB:.2f} GB"


def cmd_stats(_):
    with app.app_context():
        users = User.query.count()
        nodes = ProxyNode.query.count()
        goods = Goods.query.count()
        orders = UserOrder.query.count()
        paid = UserOrder.query.filter_by(status=1).count()
        revenue = sum(o.amount for o in UserOrder.query.filter_by(status=1).all())
        print(f"users:    {users}")
        print(f"nodes:    {nodes}")
        print(f"goods:    {goods}")
        print(f"orders:   {orders} ({paid} paid)")
        print(f"revenue:  ${revenue:.2f}")


def cmd_users(_):
    with app.app_context():
        for u in User.query.order_by(User.id).all():
            print(f"#{u.id} {u.username:<16} {_fmt_gb(u.upload_traffic + u.download_traffic):>10} / "
                  f"{_fmt_gb(u.total_traffic):>10}  level={u.level}  {'admin' if u.is_admin else ''}  "
                  f"{'ON' if u.enable else 'OFF'}")


def cmd_user_add(args):
    with app.app_context():
        if User.query.filter_by(username=args.username).first():
            print(f"error: user '{args.username}' already exists", file=sys.stderr)
            return 1
        u = User.add_new_user(args.username, "", args.password)
        u.total_traffic = args.traffic
        u.is_admin = args.admin
        db.session.commit()
        print(f"created user #{u.id} {args.username} (port {u.ss_port})")
    return 0


def cmd_user_reset(args):
    with app.app_context():
        u = User.query.filter_by(username=args.username).first()
        if not u:
            print(f"error: user '{args.username}' not found", file=sys.stderr)
            return 1
        u.reset_traffic(u.total_traffic)
        u.enable = True
        db.session.commit()
        print(f"reset traffic for {args.username}")
    return 0


def cmd_nodes(_):
    with app.app_context():
        for n in ProxyNode.query.order_by(ProxyNode.id).all():
            print(f"#{n.id} {n.name:<16} {n.node_type:<6} {n.server}:{n.ss_port}  "
                  f"{_fmt_gb(n.used_traffic):>10} / {_fmt_gb(n.total_traffic):>10}  "
                  f"{'ON' if n.enable else 'OFF'}")


def cmd_node_add(args):
    with app.app_context():
        n = ProxyNode(name=args.name, server=args.server, node_type=args.type,
                      ss_port=args.port, ss_method="aes-256-gcm", country=args.country,
                      total_traffic=GB)
        db.session.add(n)
        db.session.commit()
        AuditLog.log(0, "node.add", args.name)
        print(f"created node #{n.id} {args.name}")
    return 0


def cmd_goods(_):
    with app.app_context():
        for g in Goods.query.order_by(Goods.id).all():
            print(f"#{g.id} {g.name:<20} ${g.money:<8} {_fmt_gb(g.transfer):>10}  "
                  f"{g.days}d  level={g.level}  {'ON' if g.status else 'OFF'}")


def cmd_orders(_):
    with app.app_context():
        for o in UserOrder.query.order_by(UserOrder.id.desc()).limit(50).all():
            print(f"#{o.id} user={o.user_id} goods={o.goods_id} ${o.amount} "
                  f"{'PAID' if o.status == 1 else 'PENDING'} {o.out_trade_no} "
                  f"{o.created_at.isoformat() if o.created_at else ''}")


def cmd_backup(args):
    with app.app_context():
        data = {
            "version": "cli",
            "exported_at": datetime.utcnow().isoformat(),
            "users": [u.to_dict() for u in User.query.all()],
            "nodes": [n.to_dict() for n in ProxyNode.query.all()],
            "goods": [g.to_dict() for g in Goods.query.all()],
            "orders": [o.to_dict() for o in UserOrder.query.all()],
        }
        with open(args.file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        print(f"backup written to {args.file}")


def cmd_restore(args):
    with app.app_context():
        with open(args.file, encoding="utf-8") as f:
            data = json.load(f)
        for m in (UserOrder, User, ProxyNode, Goods):
            db.session.query(m).delete()
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
        print(f"restored {len(data.get('users', []))} users, {len(data.get('nodes', []))} nodes")


def main():
    p = argparse.ArgumentParser(prog="fluxgate", description="FluxGate CLI admin")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("stats", help="system stats")
    sub.add_parser("users", help="list users")
    sub.add_parser("nodes", help="list nodes")
    sub.add_parser("goods", help="list goods")
    sub.add_parser("orders", help="recent orders")
    ua = sub.add_parser("user", help="user commands")
    uas = ua.add_subparsers(dest="sub")
    uadd = uas.add_parser("add", help="add user")
    uadd.add_argument("username")
    uadd.add_argument("password")
    uadd.add_argument("--admin", action="store_true")
    uadd.add_argument("--traffic", type=float, default=10 * GB, help="total traffic in bytes")
    ureset = uas.add_parser("reset", help="reset user traffic")
    ureset.add_argument("username")
    na = sub.add_parser("node", help="node commands")
    nas = na.add_subparsers(dest="sub")
    nadd = nas.add_parser("add", help="add node")
    nadd.add_argument("name")
    nadd.add_argument("server")
    nadd.add_argument("--port", type=int, default=8388)
    nadd.add_argument("--type", default="ss", choices=["ss", "vless", "trojan"])
    nadd.add_argument("--country", default="CN")
    bk = sub.add_parser("backup", help="backup to JSON")
    bk.add_argument("file")
    rs = sub.add_parser("restore", help="restore from JSON")
    rs.add_argument("file")
    args = p.parse_args()

    handlers = {
        "stats": cmd_stats, "users": cmd_users, "nodes": cmd_nodes,
        "goods": cmd_goods, "orders": cmd_orders, "backup": cmd_backup,
        "restore": cmd_restore,
    }
    if args.cmd in handlers:
        return handlers[args.cmd](args)
    if args.cmd == "user":
        if args.sub == "add":
            return cmd_user_add(args)
        if args.sub == "reset":
            return cmd_user_reset(args)
    if args.cmd == "node":
        if args.sub == "add":
            return cmd_node_add(args)
    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
