# Launch Pack — FluxGate

Copy-paste posts for launching FluxGate. Post Tue–Thu mornings for max reach.

## LinkedIn

**Rebuilt the legendary Shadowsocks panel — in one Python process.**

The old Django-era proxy panels are archived, bloated, and need Redis + Celery + MySQL just to boot. So I rebuilt one from scratch: **FluxGate**.

What it ships:
- 🔗 Multi-protocol subscriptions — ss / v2ray / trojan / clash, one URL
- 📦 Invite-code registration + referral rewards
- 💳 Goods, orders, and a payment callback flow
- 📊 Live traffic charts + node health (online/offline heartbeat)
- 👑 Full admin CRUD — users, nodes, goods, revenue
- 🐳 Docker one-liner, 26 passing tests, GPL-3.0

The kicker: `python run.py` and it's live. No Redis. No Celery. No VPS required.

Built with Flask + SQLAlchemy + SQLite. Would love feedback on the subscription engine — especially the Clash YAML generation.

#FluxGate #Python #Flask #SelfHosted #OpenSource

## X / Twitter thread

1/ Proxy panels are stuck in 2017. Archived repos, Redis+Celery+MySQL stacks, painful deploys. So I rebuilt one from scratch. Meet FluxGate ⚡
2/ One process. Flask + SQLAlchemy + SQLite. `python run.py` → live panel.
3/ Multi-protocol subscriptions: ss, v2ray, trojan, clash — one URL, any client.
4/ Invite codes, referral rewards, daily check-in, traffic packages, payment callbacks.
5/ Admin CRUD: users, nodes, goods, revenue. Node heartbeats show online/offline.
6/ Live traffic charts per node. Auto-disable over-quota users.
7/ 26 tests green. Docker one-liner. GPL-3.0.
8/ The whole thing is ~1500 lines. No Redis. No Celery. No VPS. Try it: github.com/scar8969/fluxgate

## Show HN

**FluxGate — a self-hosted proxy management panel in a single Python process**

I rebuilt the classic Django-era Shadowsocks panel from scratch in Flask + SQLAlchemy + SQLite. The original needed Redis, Celery, and MySQL; this runs with `python run.py`.

What's in it:
- Subscription engine generating ss://, vmess://, vless://, trojan://, and full Clash YAML with proxy-groups
- Invite-code registration, referral rewards, daily check-in
- Goods/billing with an order lifecycle and payment callback (demo)
- Per-user per-node traffic logs, auto-disable on quota overflow
- Admin dashboard with CRUD for users/nodes/goods + revenue stats
- Node heartbeat → online/offline status
- Demo data simulator so you can see it alive in 30 seconds
- 26 tests, Dockerfile, CI

The weakest part is probably the Clash config generation — I'd love criticism there. Also the payment flow is demo-only (no real Alipay integration).

## Reddit (r/selfhosted)

[P] I rebuilt the classic Shadowsocks panel in Flask — single process, no Redis/Celery/MySQL. Multi-protocol subscriptions (ss/v2ray/trojan/clash), invite codes, billing, admin CRUD, node heartbeats. `python run.py` and it's live. 26 tests, Docker included. Would love feedback: github.com/scar8969/fluxgate

## Posting checklist

- [ ] CI badge green (check Actions tab)
- [ ] `gh repo edit --add-topic flask,shadowsocks,v2ray,trojan,clash,proxy,panel,self-hosted`
- [ ] Pin repo on profile
- [ ] Post LinkedIn + X same morning, Show HN + Reddit next day
- [ ] Reply to every comment within 24h (keeps the thread alive)
