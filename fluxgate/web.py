"""Web UI — register/login/dashboard/shop/admin. Served as a single-page
dark dashboard."""
from datetime import datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for

from . import db
from .models import Goods, InviteCode, User, UserOrder
from .proxy import ProxyNode

bp = Blueprint("web", __name__)


def _current_user():
    uid = session.get("user_id")
    if uid:
        return User.query.get(uid)
    return None


@bp.route("/")
def index():
    user = _current_user()
    if user:
        return redirect(url_for("web.dashboard"))
    return redirect(url_for("web.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        invitecode = request.form.get("invitecode", "").strip()
        ref = request.form.get("ref", "")
        if not username or not password:
            flash("Username and password are required", "error")
            return render_template("register.html", ref=ref)
        if User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
            return render_template("register.html", ref=ref)
        try:
            user = User.add_new_user(username, email, password, invitecode=invitecode or None, ref=ref or None)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("register.html", ref=ref)
        session["user_id"] = user.id
        return redirect(url_for("web.dashboard"))
    return render_template("register.html", ref=request.args.get("ref", ""))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            return redirect(url_for("web.dashboard"))
        flash("Invalid username or password", "error")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.login"))


@bp.route("/dashboard")
def dashboard():
    user = _current_user()
    if not user:
        return redirect(url_for("web.login"))
    nodes = ProxyNode.get_active_nodes(level=user.level)
    return render_template("dashboard.html", user=user, nodes=nodes)


@bp.route("/shop")
def shop():
    user = _current_user()
    if not user:
        return redirect(url_for("web.login"))
    goods = Goods.get_on_sale()
    orders = UserOrder.query.filter_by(user_id=user.id).order_by(UserOrder.id.desc()).limit(10).all()
    return render_template("shop.html", user=user, goods=goods, orders=orders)


@bp.route("/admin")
def admin():
    user = _current_user()
    if not user or not user.is_admin:
        return redirect(url_for("web.login"))
    users = User.query.order_by(User.id.desc()).limit(50).all()
    nodes = ProxyNode.query.order_by(ProxyNode.sequence).all()
    goods = Goods.query.order_by(Goods.order).all()
    orders = UserOrder.query.order_by(UserOrder.id.desc()).limit(20).all()
    revenue = db.session.query(db.func.sum(UserOrder.amount)).filter(
        UserOrder.status == UserOrder.STATUS_FINISHED).scalar() or 0.0
    online_nodes = sum(1 for n in nodes if n.is_online())
    return render_template("admin.html", user=user, users=users, nodes=nodes,
                           goods=goods, orders=orders,
                           revenue=round(revenue, 2), online_nodes=online_nodes)
