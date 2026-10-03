"""Email notifications — SMTP with graceful no-op fallback.

Configure via env:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM
If SMTP_HOST is unset, send_mail() logs and returns False (no crash).
"""
import logging
import smtplib
from email.message import EmailMessage
from flask import current_app

log = logging.getLogger("fluxgate.mail")


def _config():
    return {
        "host": current_app.config.get("SMTP_HOST", ""),
        "port": int(current_app.config.get("SMTP_PORT", 587)),
        "user": current_app.config.get("SMTP_USER", ""),
        "password": current_app.config.get("SMTP_PASSWORD", ""),
        "from": current_app.config.get("MAIL_FROM", "fluxgate@localhost"),
    }


def send_mail(to: str, subject: str, body: str) -> bool:
    """Send an email. Returns False (no-op) when SMTP is not configured."""
    cfg = _config()
    if not cfg["host"]:
        log.info("SMTP not configured — skipping mail to %s: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as s:
            s.starttls()
            if cfg["user"]:
                s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        return True
    except Exception as e:  # never crash the request on mail failure
        log.warning("mail failed: %s", e)
        return False


def notify_order_paid(user, order, goods):
    """Send an order-paid receipt."""
    body = (
        f"Hi {user.username},\n\n"
        f"Your order {order.out_trade_no} for {goods.name} (${order.amount:.2f}) "
        f"has been paid.\n"
        f"Your subscription link: {user.sub_link}\n\n"
        f"— FluxGate"
    )
    return send_mail(user.email, f"[FluxGate] Order paid — {goods.name}", body)


def notify_registered(user):
    """Welcome email on registration."""
    body = (
        f"Welcome to FluxGate, {user.username}!\n\n"
        f"Your account is ready. Subscription link: {user.sub_link}\n\n"
        f"— FluxGate"
    )
    return send_mail(user.email, "[FluxGate] Welcome!", body)
