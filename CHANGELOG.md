# Changelog

All notable changes to FluxGate.

## [Unreleased]

### Added
- QR code generation for subscription links (`/api/subscribe/qr`)
- Prometheus metrics endpoint (`/api/metrics`)
- Webhook notifications on paid orders (`WEBHOOK_URL` env)
- API documentation page (`/api/docs`)
- CONTRIBUTING.md, SECURITY.md, issue/PR templates

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
