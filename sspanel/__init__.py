"""sspanel-flask: a from-scratch Flask rebuild of Ehco1996/django-sspanel.

Architecture mirrors the original Django app:
  apps/sspanel  -> core domain (User, Goods, Order, InviteCode, checkin)
  apps/proxy    -> proxy nodes (ss / vless / trojan) + traffic sync
  apps/api      -> JSON API (subscribe, proxy_configs, orders, stats)
  apps/sub      -> subscription link generation (ss / v2ray / clash / trojan)

Rebuilt in Flask + SQLAlchemy with a SQLite backend. The original shipped
Django admin; this ships a self-contained web UI + admin + API.
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
        "DATABASE_URL", "sqlite:///" + os.path.join(app.root_path, "sspanel.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["HOST"] = os.environ.get("HOST", "http://127.0.0.1:5000")
    app.config["DEFAULT_TRAFFIC"] = int(os.environ.get("DEFAULT_TRAFFIC", 10 * GB))
    app.config["INVITE_NUM"] = int(os.environ.get("INVITE_NUM", 5))
    app.config["TITLE"] = os.environ.get("TITLE", "sspanel-flask")
    if config:
        app.config.update(config)

    db.init_app(app)

    from .api import bp as api_bp
    from .web import bp as web_bp
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(web_bp)

    with app.app_context():
        db.create_all()
        from .seed import seed
        seed(app)

    return app
