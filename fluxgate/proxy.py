"""Proxy node models — mirrors apps/proxy/models.py in the original.

Supports ss / vless / trojan node types, per-node traffic accounting,
level gating, and multi-server addresses.
"""
import base64
import json
from urllib.parse import quote

from . import db, GB
from .models import traffic_format


class ProxyNode(db.Model):
    __tablename__ = "proxy_nodes"

    NODE_TYPE_SS = "ss"
    NODE_TYPE_VLESS = "vless"
    NODE_TYPE_TROJAN = "trojan"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), default="")
    server = db.Column(db.String(256), default="")  # comma-separated addresses
    enable = db.Column(db.Boolean, default=True)
    node_type = db.Column(db.String(32), default=NODE_TYPE_SS)
    info = db.Column(db.String(1024), default="")
    level = db.Column(db.Integer, default=0)
    country = db.Column(db.String(5), default="CN")
    used_traffic = db.Column(db.BigInteger, default=0)
    total_traffic = db.Column(db.BigInteger, default=GB)
    enlarge_scale = db.Column(db.Float, default=1.0)
    sequence = db.Column(db.Integer, default=0)
    last_seen = db.Column(db.DateTime, nullable=True)  # heartbeat from backend
    first_seen = db.Column(db.DateTime, nullable=True)  # first heartbeat (uptime)

    # ss-specific
    ss_method = db.Column(db.String(32), default="aes-256-gcm")
    ss_port = db.Column(db.Integer, default=8388)
    # vless/trojan
    uuid = db.Column(db.String(64), default="")
    # trojan
    trojan_password = db.Column(db.String(64), default="")

    @property
    def multi_server_address(self):
        return [s for s in self.server.split(",") if s]

    @classmethod
    def get_active_nodes(cls, level=None):
        q = cls.query.filter_by(enable=True)
        if level is not None:
            q = q.filter(cls.level <= level)
        return q.order_by(cls.sequence).all()

    @classmethod
    def calc_total_traffic(cls):
        used = sum(n.used_traffic or 0 for n in cls.query.all())
        return traffic_format(used)

    def get_ss_config(self):
        return {
            "server": self.multi_server_address,
            "port": self.ss_port,
            "method": self.ss_method,
            "password": "",  # filled per-user at subscribe time
            "plugin": "",
        }

    def get_proxy_configs(self):
        """Node-level config the backend polls (mirrors ProxyConfigsView)."""
        return {
            "id": self.id,
            "name": self.name,
            "node_type": self.node_type,
            "server": self.multi_server_address,
            "port": self.ss_port,
            "method": self.ss_method,
            "uuid": self.uuid,
            "password": self.trojan_password,
            "level": self.level,
            "country": self.country,
            "info": self.info,
            "used_traffic": self.used_traffic,
            "total_traffic": self.total_traffic,
            "enlarge_scale": self.enlarge_scale,
        }

    def to_dict(self):
        d = self.get_proxy_configs()
        d["enable"] = self.enable
        d["human_used"] = traffic_format(self.used_traffic or 0)
        d["human_total"] = traffic_format(self.total_traffic or 0)
        d["online"] = self.is_online()
        d["uptime"] = self.uptime()
        return d

    def uptime(self):
        """Human uptime string since first heartbeat (e.g. '3d 4h')."""
        from datetime import datetime
        if not self.first_seen:
            return "0m"
        delta = datetime.utcnow() - self.first_seen
        days, rem = divmod(int(delta.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        mins = rem // 60
        if days:
            return f"{days}d {hours}h"
        if hours:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    def is_online(self):
        """Node is online if a backend reported traffic within the last 5 min."""
        from datetime import datetime, timedelta
        if not self.last_seen:
            return False
        return datetime.utcnow() - self.last_seen < timedelta(minutes=5)


class UserTrafficLog(db.Model):
    """Per-user per-node traffic accounting (mirrors original traffic logs)."""
    __tablename__ = "user_traffic_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True)
    node_id = db.Column(db.Integer, index=True)
    upload = db.Column(db.BigInteger, default=0)
    download = db.Column(db.BigInteger, default=0)
    created_at = db.Column(db.DateTime, default=__import__("datetime").datetime.utcnow)

    @classmethod
    def record(cls, user_id, node_id, upload, download):
        db.session.add(cls(user_id=user_id, node_id=node_id, upload=upload, download=download))
        db.session.commit()

    @classmethod
    def get_user_traffic_by_node(cls, user_id, node_id):
        logs = cls.query.filter_by(user_id=user_id, node_id=node_id).all()
        up = sum(l.upload for l in logs)
        down = sum(l.download for l in logs)
        return up, down
