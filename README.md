# FluxGate

> Self-hosted proxy management panel — users, nodes, subscriptions, and billing in one process.

![Python](https://img.shields.io/badge/Python-3.11-blue) ![Flask](https://img.shields.io/badge/Flask-3.1-black) ![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-3.1-green) ![tests](https://img.shields.io/badge/tests-19%2F19-passing-brightgreen) ![license](https://img.shields.io/badge/license-GPL--3.0-blue)

**FluxGate** is a self-hosted management panel for proxy services. Users register with invite codes, buy traffic packages, and get subscription links for any client. Admins manage nodes, goods, and orders from a built-in dashboard. Everything runs in a single Python process — no Redis, no Celery, no external services.

## Why FluxGate

Proxy panels are either abandoned, bloated, or locked behind paid SaaS. FluxGate is:

- **Single-process** — Flask + SQLAlchemy + SQLite, `python run.py` and you're live
- **Multi-protocol** — ss / v2ray / trojan / clash subscriptions out of the box
- **Self-contained** — web UI, admin, API, and billing all built in
- **Demo-ready** — seeded admin + demo accounts, demo payment flow, instant to explore

## Features

- 🔑 **Invite-code registration** — no spam users, referral rewards for inviters
- 📦 **Goods & billing** — traffic packages with level gating, order lifecycle, payment callback
- 🔗 **Subscription engine** — `ss://`, `vmess://`, `vless://`, `trojan://`, and full Clash YAML with proxy-groups
- 📊 **Traffic accounting** — per-user per-node logs, auto-disable on quota overflow
- 🎁 **Daily check-in** — random traffic reward, once per day
- 🛡️ **Backend API** — token-authenticated node config + traffic reporting
- 👑 **Admin dashboard** — users, nodes, goods, orders at a glance

## Architecture

```
fluxgate/
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
        │ goods    │ │ ss/vless │ │ payment  │
        │ invite   │ │ trojan   │ │ callback │
        │ traffic  │ │ traffic  │ │          │
        └──────────┘ └──────────┘ └──────────┘
              │            │
              ▼            ▼
        ┌────────────────────────┐
        │  Subscription engine   │  ss:// · vmess:// · vless:// · trojan:// · clash
        └────────────────────────┘
```

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

## Screenshots

![Dashboard](screenshots/dashboard.png)
![Shop](screenshots/shop.png)

## Tests

```bash
.venv/Scripts/python -m pytest tests/ -v
```

19 tests covering: seed data, invite-code registration, login/logout, daily check-in, traffic overflow auto-disable, subscription generation (ss/v2ray/clash), level gating, order lifecycle, payment callback, API auth, admin-only routes, page rendering.

## License

GPL-3.0
