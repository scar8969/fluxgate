# Security Policy

## Reporting a vulnerability

If you find a security issue in FluxGate, **do not open a public issue**. Email the maintainer directly or open a private security advisory via GitHub's "Report a vulnerability" button on the repo.

Please include:
- A description of the vulnerability
- Steps to reproduce
- Impact assessment

## What to expect

- Acknowledgment within 48 hours
- A fix within 14 days for critical issues
- Credit in the changelog (if desired)

## Security notes

- **Change the default credentials** (`admin/admin123`) before any production use.
- **Set a strong `SECRET_KEY`** via environment variable — the dev default is not safe for production.
- **Set `API_TOKEN`** to something random; the dev default (`dev-api-token`) is public knowledge.
- The payment flow is **demo-only** — do not use it for real money without integrating a real payment provider.
- Login rate limiting is in-memory (per-process). For multi-worker deployments, use a shared store.
