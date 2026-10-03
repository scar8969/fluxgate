"""fluxgate: a self-hosted proxy management panel.

Architecture:
  core    -> domain (User, Goods, Order, InviteCode, checkin)
  proxy   -> proxy nodes (ss / vless / trojan) + traffic sync
  api     -> JSON API (subscribe, proxy_configs, orders, stats)
  sub     -> subscription link generation (ss / v2ray / clash / trojan)

Built with Flask + SQLAlchemy on SQLite. Ships a self-contained web UI +
admin + API in a single process.
"""
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

GB = 1024 ** 3


def create_app(config=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(app.root_path, "fluxgate.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["HOST"] = os.environ.get("HOST", "http://127.0.0.1:5000")
    app.config["DEFAULT_TRAFFIC"] = int(os.environ.get("DEFAULT_TRAFFIC", 10 * GB))
    app.config["INVITE_NUM"] = int(os.environ.get("INVITE_NUM", 5))
    app.config["TITLE"] = os.environ.get("TITLE", "FluxGate")
    app.config["WEBHOOK_URL"] = os.environ.get("WEBHOOK_URL", "")  # optional paid-order webhook
    app.config["TELEGRAM_BOT_TOKEN"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    app.config["TELEGRAM_CHAT_ID"] = os.environ.get("TELEGRAM_CHAT_ID", "")
    # SMTP (optional — no-op when unset)
    app.config["SMTP_HOST"] = os.environ.get("SMTP_HOST", "")
    app.config["SMTP_PORT"] = os.environ.get("SMTP_PORT", "587")
    app.config["SMTP_USER"] = os.environ.get("SMTP_USER", "")
    app.config["SMTP_PASSWORD"] = os.environ.get("SMTP_PASSWORD", "")
    app.config["MAIL_FROM"] = os.environ.get("MAIL_FROM", "fluxgate@localhost")
    app.config["PAYMENT_PROVIDER"] = os.environ.get("PAYMENT_PROVIDER", "demo")  # demo | stripe
    # session security
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "0") == "1"
    if config:
        app.config.update(config)

    db.init_app(app)

    from .api import bp as api_bp
    from .web import bp as web_bp
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(web_bp)

    # expose CSRF token to templates
    from .web import _csrf_token, _lang, I18N
    app.jinja_env.globals["csrf_token"] = _csrf_token

    def _t(key):
        return I18N.get(_lang(), {}).get(key, key)

    app.jinja_env.globals["t"] = _t

    @app.context_processor
    def _inject():
        from flask import request as _req
        return {"theme": "light" if _req.cookies.get("theme") == "light" else "dark"}

    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("X-XSS-Protection", "1; mode=block")
        # permissive CSP (self + inline styles/scripts + CDN for swagger)
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data:;",
        )
        return resp

    with app.app_context():
        db.create_all()
        from .seed import seed
        seed(app)

    return app
