# Changelog

All notable changes to FluxGate.

## [Unreleased]

### Added
- Telegram bot (`bot.py`) — /link /traffic /checkin /subscribe /stats, DEMO_MODE
- Telegram order-paid notifications (TELEGRAM_BOT_TOKEN + CHAT_ID)
- Stripe payment adapter (test mode Checkout Sessions, provider pattern)
- README banner + comparison table vs v2board/xboard/django-sspanel
- Auto-release workflow (tag → GitHub release)

## [0.3.0] - 2026-10-02

### Added
- SSE live traffic stream (`/api/stream`)
- Load-test benchmark (`bench.py`) — 92 req/s, 0% errors measured
- GHCR multi-arch Docker image workflow
- Demo GIF + real coverage badge (86%)

## [0.2.0] - 2026-10-02

### Added
- Sample backend agent (`backend.py`) — panel ↔ backend ↔ traffic loop
- Admin analytics: revenue + signup trends chart
- CSV exports for users and orders
- Login rate limiting (5 attempts / 5 min → 429)
- Render + Railway deploy configs
- CI with coverage (pytest-cov)
- English UI (full translation from Chinese)

### Changed
- Node heartbeat → online/offline status
- Admin CRUD for users/nodes/goods

## [0.1.0] - 2026-10-02

### Added
- Initial release: users, invite codes, referral rewards
- Multi-protocol subscription engine (ss/v2ray/trojan/clash)
- Goods/billing + payment callback
- Traffic accounting + auto-disable on overflow
- Live traffic charts
- Daily check-in
- Admin dashboard
- Demo data simulator
- Docker + docker-compose
