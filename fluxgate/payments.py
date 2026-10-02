"""Payment provider abstraction — demo (default) + Stripe (test mode).

The demo provider simulates a payment callback instantly. Stripe creates a
real Checkout Session (test mode) and the webhook confirms the order.

Set PAYMENT_PROVIDER=stripe and STRIPE_SECRET_KEY / STRIPE_WEBHOOK_SECRET.
"""
import json
import os
import urllib.request
import urllib.parse


def create_checkout(order, user, app):
    """Return a payment URL for the order, or None for demo (auto-confirm)."""
    provider = app.config.get("PAYMENT_PROVIDER", "demo")
    if provider == "stripe":
        return _stripe_checkout(order, user, app)
    return None  # demo: callback endpoint confirms immediately


def _stripe_checkout(order, user, app):
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        return None
    host = app.config.get("HOST", "http://127.0.0.1:5000")
    data = urllib.parse.urlencode({
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(int(order.amount * 100)),
        "line_items[0][price_data][product_data][name]": f"FluxGate order {order.out_trade_no}",
        "line_items[0][quantity]": "1",
        "mode": "payment",
        "success_url": f"{host}/shop?paid={order.out_trade_no}",
        "cancel_url": f"{host}/shop",
        "client_reference_id": order.out_trade_no,
    }).encode()
    req = urllib.request.Request(
        "https://api.stripe.com/v1/checkout/sessions",
        data=data,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        session = json.loads(resp.read())
    return session.get("url")
