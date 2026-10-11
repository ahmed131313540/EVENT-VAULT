"""Stripe: one Product per event, one Price per ticket tier, and Checkout Sessions."""
import time

from . import config, db


def stripe_enabled() -> bool:
    return config.PAYMENTS_MODE == "stripe"


def _stripe():
    import stripe
    stripe.api_key = config.STRIPE_SECRET_KEY
    return stripe


def ensure_stripe_prices(event_id: int) -> bool:
    """Creates the Stripe Product for the event and a separate Price for every paid tier that lacks one.
    Safe to call repeatedly. Returns True when every paid tier has a Price ID."""
    if not stripe_enabled():
        return False
    stripe = _stripe()
    ev = db.one("SELECT id, title, stripe_product_id FROM events WHERE id = %s", (event_id,))
    tiers = db.all_("SELECT id, name, price_cents, stripe_price_id FROM ticket_tiers WHERE event_id = %s ORDER BY sort_order, id", (event_id,))
    product_id = ev["stripe_product_id"]
    if not product_id and any(t["price_cents"] > 0 and not t["stripe_price_id"] for t in tiers):
        product = stripe.Product.create(name=ev["title"][:250], metadata={"event_id": str(event_id)})
        product_id = product.id
        db.run("UPDATE events SET stripe_product_id = %s WHERE id = %s", (product_id, event_id))
    for t in tiers:
        if t["price_cents"] > 0 and not t["stripe_price_id"]:
            price = stripe.Price.create(product=product_id, unit_amount=t["price_cents"], currency=config.CURRENCY,
                                        nickname=t["name"][:250], metadata={"tier_id": str(t["id"]), "event_id": str(event_id)})
            db.run("UPDATE ticket_tiers SET stripe_price_id = %s WHERE id = %s AND stripe_price_id IS NULL", (price.id, t["id"]))
    return True


def create_checkout_session(order_id, order_ref, buyer_email, line_items, site_url):
    stripe = _stripe()
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,                         # [{"price": "price_...", "quantity": n}]
        customer_email=buyer_email,
        client_reference_id=order_ref,
        metadata={"order_id": str(order_id), "order_ref": order_ref},
        success_url=f"{site_url}/#/order/{order_ref}",
        cancel_url=f"{site_url}/#/order/{order_ref}?cancelled=1",
        expires_at=int(time.time()) + config.CHECKOUT_MINUTES * 60,
    )
    return session.id, session.url


def retrieve_session_paid(session_id: str) -> bool:
    """Asks Stripe directly whether a session has been paid (used when the webhook hasn't arrived yet)."""
    session = _stripe().checkout.Session.retrieve(session_id)
    return getattr(session, "payment_status", None) == "paid"


def retrieve_session(session_id: str):
    """Full Checkout Session object — used when the caller also needs the payment_intent id (for refunds)."""
    return _stripe().checkout.Session.retrieve(session_id)


def refund_payment_intent(payment_intent_id: str, amount_cents: int):
    """Issues a partial or full refund against a PaymentIntent. Raises on failure — the caller (routes_admin.py)
    turns that into a clear HTTP error rather than a stack trace."""
    return _stripe().Refund.create(payment_intent=payment_intent_id, amount=amount_cents)


def verify_webhook(payload: bytes, signature: str):
    """Raises if the signature is wrong. Returns the parsed event as plain dicts."""
    import json
    stripe = _stripe()
    stripe.Webhook.construct_event(payload, signature, config.STRIPE_WEBHOOK_SECRET)
    return json.loads(payload)
