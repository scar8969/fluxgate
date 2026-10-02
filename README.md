# sspanel-flask

> Rebuilt [Ehco1996/django-sspanel](https://github.com/Ehco1996/django-sspanel) (3,072★, archived) from scratch in **Flask + SQLAlchemy + SQLite**. Same architecture, same API surface, zero Django — and the subscription engine the original only half-shipped, now generating **ss / v2ray / trojan / clash** links for every node.

![Python](https://img.shields.io/badge/Python-3.11-blue) ![Flask](https://img.shields.io/badge/Flask-3.1-black) ![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-3.1-green) ![tests](https://img.shields.io/badge/tests-19%2F19-passing-brightgreen) ![license](https://img.shields.io/badge/license-GPL--3.0-blue)

A self-hosted **Shadowsocks / V2Ray / Trojan management panel** — users register with invite codes, buy traffic packages, get subscription links for any client, and admins manage nodes, goods, and orders. The original was the legendary Django panel; this is a from-scratch Flask rebuild that runs on any machine with Python, no Redis, no Celery, no VPS required.

---

## Why this exists

The original `django-sspanel` was THE Shadowsocks panel of its era (3k+ stars), but it's **archived** — Django + Redis + Celery + MySQL, a 2017-era stack that's painful to self-host today. This rebuild:

- **Keeps the exact architecture** — `apps/sspanel` (users/goods/orders), `apps/proxy` (nodes), `apps/api` (JSON API), `apps/sub` (subscription engine)
- **Drops the heavy stack** — Flask + SQLAlchemy + SQLite, one process, zero external services
- **Ships what they never finished** — full **clash subscription** with proxy-groups + rules (the original only had partial clash support), per-node traffic charts, and a working demo payment flow

## Architecture

```
sspanel/
├── __init__.py      # app factory, config, db init
├── models.py        # User, Goods, UserOrder, InviteCode, UserCheckInLog, UserRefLog
├── proxy.py         # ProxyNode (ss/vless/trojan), UserTrafficLog
├── sub.py           # subscription engine: ss:// vmess:// vless:// trojan:// clash YAML
├── api.py           # JSON API blueprint
├── web.py           # web UI blueprint (dashboard/shop/admin)
├── seed.py          # demo data (admin/demo users, 3 nodes, 4 goods)
└── templates/       # dark dashboard UI
```

```
                    ┌──────────────┐
                    │   Web UI     │  register/login · dashboard · shop · admin
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │  Flask API   │  /api/subscribe · /api/proxy_configs · /api/orders
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │  Users   │ │  Nodes   │ │  Orders  │
        │ goods    │ │ ss/vless │ │ alipay   │
        │ invite   │ │ trojan   │ │ callback │
        │ traffic  │ │ traffic  │ │          │
        └──────────┘ └──────────┘ └──────────┘
              │            │
              ▼            ▼
        ┌────────────────────────┐
        │  Subscription engine   │  ss:// · vmess:// · vless:// · trojan:// · clash
        └────────────────────────┘
```

## Screenshots

![Dashboard](screenshots/dashboard.png)
![Shop](screenshots/shop.png)

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt     # Linux/macOS
.venv/Scripts/python run.py
```

Open http://127.0.0.1:5000

| Account | Password | Role |
|---|---|---|
| `admin` | `admin123` | admin (manage users/nodes/goods) |
| `demo` | `demo123` | regular user |

## API surface

| Method | Path | Description |
|---|---|---|
| GET | `/api/subscribe?token=<id>&sub_type=ss` | subscription links (ss/v2ray/trojan/clash) |
| GET | `/api/proxy_configs/<node_id>` | node config for backends (X-API-Token auth) |
| POST | `/api/proxy_configs/<node_id>` | traffic report from backends |
| POST | `/api/user/settings` | change ss password |
| GET | `/api/user/stats/traffic_chart` | per-node traffic chart |
| GET | `/api/user/stats/ref_chart` | referral chart |
| POST | `/api/checkin` | daily check-in traffic reward |
| POST | `/api/orders` | create order |
| POST | `/api/callback/alipay` | payment callback (demo) |
| GET | `/api/system_status` | admin dashboard stats |

## What the original shipped vs what this ships

| Feature | django-sspanel (original) | sspanel-flask (this) |
|---|---|---|
| Stack | Django + Redis + Celery + MySQL | Flask + SQLAlchemy + SQLite |
| Subscription | ss/v2ray/clash (partial) | ss/v2ray/trojan/clash (full, proxy-groups) |
| Backend auth | API token | X-API-Token header |
| Traffic sync | Celery task | synchronous POST handler |
| Payment | Alipay face-to-face | demo callback flow |
| Admin | Django admin | built-in dark dashboard |
| Deploy | Docker + VPS | `python run.py` |

## Tests

```bash
.venv/Scripts/python -m pytest tests/ -v
```

19 tests covering: seed data, invite-code registration, login/logout, daily check-in, traffic overflow auto-disable, subscription generation (ss/v2ray/clash), level gating, order lifecycle, payment callback, API auth, admin-only routes, page rendering.

## License

GPL-3.0 — same as the original.
