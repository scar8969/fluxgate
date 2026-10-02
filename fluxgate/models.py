"""Core domain models — User, Goods, Order, InviteCode, check-in, referral."""
import random
import string
import uuid
from datetime import datetime, timedelta

from . import db, GB


def _short_rand(n=8):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def _long_rand(n=32):
    return "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def traffic_format(n):
    """Format bytes into human units, matching the original's helper."""
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


class User(db.Model):
    __tablename__ = "users"

    MIN_PORT = 1025
    PORT_BLACK_SET = {6443, 8472}

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    email = db.Column(db.String(128), default="")
    balance = db.Column(db.Float, default=0.0)
    level = db.Column(db.Integer, default=0)
    level_expire_time = db.Column(db.DateTime, default=datetime.utcnow)
    invitecode_num = db.Column(db.Integer, default=5)
    inviter_id = db.Column(db.Integer, default=0)

    # ss
    ss_port = db.Column(db.Integer, unique=True, default=MIN_PORT)
    ss_password = db.Column(db.String(32), default=_short_rand, unique=True)
    # v2ray
    vmess_uuid = db.Column(db.String(64), default="")
    # traffic
    upload_traffic = db.Column(db.BigInteger, default=0)
    download_traffic = db.Column(db.BigInteger, default=0)
    total_traffic = db.Column(db.BigInteger, default=GB * 10)
    last_use_time = db.Column(db.DateTime, nullable=True)
    enable = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ---- class methods (mirror original) ----
    @classmethod
    def get_not_used_port(cls):
        used = {u.ss_port for u in cls.query.all()}
        if not used:
            return cls.MIN_PORT
        max_port = max(used) + 1
        candidates = set(range(cls.MIN_PORT, max_port + 1)) - used - cls.PORT_BLACK_SET
        return random.choice(sorted(candidates))

    @classmethod
    def add_new_user(cls, username, email, password, invitecode=None, ref=None):
        user = cls(
            username=username,
            email=email,
            ss_port=cls.get_not_used_port(),
            vmess_uuid=str(uuid.uuid4()),
            total_traffic=GB * 10,
        )
        user.set_password(password)
        inviter_id = 0
        if invitecode:
            code = InviteCode.query.filter_by(code=invitecode, consumed=False).first()
            if not code:
                raise ValueError("invalid invite code")
            code.consumed = True
            code.consumed_by = username
            inviter_id = code.user_id
        elif ref:
            inviter_id = int(ref)
        if inviter_id:
            user.inviter_id = inviter_id
            UserRefLog.log_ref(inviter_id)
        db.session.add(user)
        db.session.commit()
        return user

    # ---- instance helpers ----
    def set_password(self, raw):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        from werkzeug.security import check_password_hash
        return check_password_hash(self.password_hash, raw)

    @property
    def token(self):
        # obfuscated id, mirrors encoder.int2string in the original
        return f"{self.id:06d}"

    @property
    def used_traffic(self):
        return (self.upload_traffic or 0) + (self.download_traffic or 0)

    @property
    def overflow(self):
        return self.used_traffic > self.total_traffic

    @property
    def human_total_traffic(self):
        return traffic_format(self.total_traffic)

    @property
    def human_used_traffic(self):
        return traffic_format(self.used_traffic)

    @property
    def human_remain_traffic(self):
        return traffic_format(max(0, self.total_traffic - self.used_traffic))

    @property
    def used_percentage(self):
        try:
            return round(self.used_traffic / self.total_traffic * 100, 2)
        except ZeroDivisionError:
            return 100.0

    @property
    def sub_link(self):
        from flask import current_app
        return f"{current_app.config['HOST']}/api/subscribe?token={self.token}"

    @property
    def ref_link(self):
        from flask import current_app
        return f"{current_app.config['HOST']}/register?ref={self.id}"

    def reset_traffic(self, new_traffic):
        self.total_traffic = new_traffic
        self.upload_traffic = 0
        self.download_traffic = 0

    def reset_random_port(self):
        self.ss_port = self.get_not_used_port()
        db.session.commit()
        return self.ss_port

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "balance": self.balance,
            "level": self.level,
            "ss_port": self.ss_port,
            "ss_password": self.ss_password,
            "vmess_uuid": self.vmess_uuid,
            "upload_traffic": self.upload_traffic,
            "download_traffic": self.download_traffic,
            "total_traffic": self.total_traffic,
            "used_traffic": self.used_traffic,
            "human_total": self.human_total_traffic,
            "human_used": self.human_used_traffic,
            "human_remain": self.human_remain_traffic,
            "used_percentage": self.used_percentage,
            "sub_link": self.sub_link,
            "ref_link": self.ref_link,
            "enable": self.enable,
            "is_admin": self.is_admin,
        }


class InviteCode(db.Model):
    __tablename__ = "invite_codes"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(16), unique=True, default=_short_rand)
    user_id = db.Column(db.Integer, default=0)
    consumed = db.Column(db.Boolean, default=False)
    consumed_by = db.Column(db.String(64), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def gen_codes(cls, user_id, num):
        codes = [cls(code=_short_rand(8), user_id=user_id) for _ in range(num)]
        db.session.add_all(codes)
        db.session.commit()
        return codes


class UserRefLog(db.Model):
    __tablename__ = "user_ref_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, default=0)
    date = db.Column(db.Date, default=datetime.utcnow().date)

    @classmethod
    def log_ref(cls, user_id):
        today = datetime.utcnow().date()
        exists = cls.query.filter_by(user_id=user_id, date=today).first()
        if not exists:
            db.session.add(cls(user_id=user_id, date=today))
            db.session.commit()


class UserCheckInLog(db.Model):
    __tablename__ = "user_checkin_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True)
    date = db.Column(db.Date, default=datetime.utcnow().date)
    added_traffic = db.Column(db.BigInteger, default=0)

    @classmethod
    def get_today_is_checkin_by_user_id(cls, user_id):
        today = datetime.utcnow().date()
        return cls.query.filter_by(user_id=user_id, date=today).first() is not None

    @classmethod
    def checkin(cls, user):
        today = datetime.utcnow().date()
        if cls.query.filter_by(user_id=user.id, date=today).first():
            return None
        # random 10MB ~ 100MB, mirrors original checkin reward
        reward = random.randint(10 * 1024 * 1024, 100 * 1024 * 1024)
        user.total_traffic += reward
        db.session.add(cls(user_id=user.id, date=today, added_traffic=reward))
        db.session.commit()
        return reward


class Goods(db.Model):
    __tablename__ = "goods"
    STATUS_ON = 1
    STATUS_OFF = -1

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), default="New plan")
    content = db.Column(db.String(256), default="")
    transfer = db.Column(db.BigInteger, default=GB)  # added traffic (bytes)
    money = db.Column(db.Float, default=0.0)
    level = db.Column(db.Integer, default=0)
    days = db.Column(db.Integer, default=1)
    status = db.Column(db.Integer, default=STATUS_ON)
    order = db.Column(db.Integer, default=1)
    user_purchase_count = db.Column(db.Integer, default=0)

    @classmethod
    def get_on_sale(cls):
        return cls.query.filter_by(status=cls.STATUS_ON).order_by(cls.order).all()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "content": self.content,
            "transfer": self.transfer,
            "human_transfer": traffic_format(self.transfer),
            "money": self.money,
            "level": self.level,
            "days": self.days,
            "status": self.status,
        }


class UserOrder(db.Model):
    __tablename__ = "user_orders"
    STATUS_CREATED = 0
    STATUS_PAID = 1
    STATUS_FINISHED = 2

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, index=True)
    goods_id = db.Column(db.Integer, default=0)
    status = db.Column(db.Integer, default=STATUS_CREATED)
    out_trade_no = db.Column(db.String(64), unique=True)
    amount = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expired_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(minutes=10))

    @classmethod
    def gen_out_trade_no(cls):
        return datetime.utcnow().strftime("%Y%m%d%H%M%S") + str(random.randint(1000, 9999))

    @classmethod
    def create_order(cls, user_id, amount):
        order = cls(
            user_id=user_id,
            status=cls.STATUS_CREATED,
            out_trade_no=cls.gen_out_trade_no(),
            amount=amount,
            expired_at=datetime.utcnow() + timedelta(minutes=10),
        )
        db.session.add(order)
        db.session.commit()
        return order

    @classmethod
    def finish_order(cls, out_trade_no):
        """Mark an order paid and grant the goods. Mirrors original callback flow."""
        order = cls.query.filter_by(out_trade_no=out_trade_no).first()
        if not order or order.status != cls.STATUS_CREATED:
            return None
        order.status = cls.STATUS_PAID
        user = User.query.get(order.user_id)
        if user:
            # grant traffic + level days
            goods = Goods.query.get(order.goods_id) if order.goods_id else None
            if goods:
                user.total_traffic += goods.transfer
                if goods.days:
                    base = user.level_expire_time or datetime.utcnow()
                    if base < datetime.utcnow():
                        base = datetime.utcnow()
                    user.level_expire_time = base + timedelta(days=goods.days)
                    user.level = max(user.level, goods.level)
            user.balance += order.amount  # demo: balance credited
        order.status = cls.STATUS_FINISHED
        db.session.commit()
        return order

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "out_trade_no": self.out_trade_no,
            "amount": self.amount,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expired_at": self.expired_at.isoformat() if self.expired_at else None,
        }
