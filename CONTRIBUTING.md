# Contributing to FluxGate

Thanks for wanting to help! Here's how to get started.

## Development setup

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # Windows
.venv/Scripts/python -m pytest tests/ -v                  # run tests
```

## Project structure

```
fluxgate/
├── __init__.py      # app factory
├── models.py        # domain models
├── proxy.py         # proxy nodes + traffic
├── sub.py           # subscription engine
├── api.py           # JSON API
├── web.py           # web UI routes
└── templates/       # Jinja templates
```

## Guidelines

- **Keep it single-process** — no Redis, no Celery, no external services.
- **Tests must pass** — every change ships with a test in `tests/test_app.py`.
- **English only** — UI copy, comments, and commit messages in English.
- **KISS** — prefer simple, readable code over clever abstractions.
- **No scope creep** — fix what the issue asks, nothing more.

## Commit style

- One logical change per commit.
- Imperative subject line: `Add QR code for subscriptions`, `Fix webhook thread context`.
- Reference the issue number when applicable.

## Pull requests

1. Fork the repo and create a branch.
2. Make your change + add tests.
3. Run `pytest tests/ -v` — all green.
4. Open a PR with a clear description and screenshot if UI changed.

## Reporting bugs

Open an issue with:
- What you did
- What you expected
- What happened (include the traceback)
- Your environment (OS, Python version)
