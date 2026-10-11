import logging
import time

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import config, db, orders, payments, tickets as tk
from .deps import current_user, owned_event_or_admin, require_organizer, require_user, site_url

router = APIRouter(prefix="/api")
log = logging.getLogger("eventvault")


class CartItem(BaseModel):
    tier_id: int
    quantity: int = Field(ge=0, le=config.MAX_TICKETS_PER_ORDER)


class CheckoutIn(BaseModel):
    event_id: int
    items: list[CartItem] = Field(min_length=1, max_length=6)


@router.post("/checkout")
def checkout(body: CheckoutIn, request: Request):
    user = require_user(request)
    try:
        return orders.create_order(user, body.event_id, [i.model_dump() for i in body.items], site_url(request))
    except orders.OrderError as e:
        raise HTTPException(e.status, e.message)


def _order_for(ref, user):
    o = db.one("""SELECT o.*, e.title, e.starts_at, e.venue, e.city, e.organizer_id FROM orders o JOIN events e ON e.id = o.event_id
                  WHERE o.public_ref = %s""", (ref,))
    if not o or o["user_id"] != user["id"]:
        raise HTTPException(404, "We couldn't find that order.")
    return o


def _order_json(o):
    tix = orders.load_order_tickets(o["id"]) if o["status"] == "paid" else []
    return {
        "ref": o["public_ref"], "status": o["status"], "payment_mode": o["payment_mode"], "total_cents": o["total_cents"],
        "currency": o["currency"], "buyer_email": o["buyer_email"], "emailed": o["emailed_at"] is not None, "email_error": o["email_error"],
        "expired": o["status"] == "pending" and o["expires_at"].timestamp() < time.time(),
        "event": {"id": o["event_id"], "title": o["title"], "starts_at": o["starts_at"].isoformat(), "venue": o["venue"], "city": o["city"]},
        "tickets": [{"token": t["token"], "seq": t["seq"], "tier_name": t["tier_name"], "holder_name": t["holder_name"], "status": t["status"]} for t in tix],
    }


@router.get("/orders/{ref}")
def get_order(ref: str, request: Request):
    """Polled by the order page. If Stripe says the session is paid but our webhook hasn't landed yet, fulfil it here."""
    user = require_user(request)
    o = _order_for(ref, user)
    if o["status"] == "pending" and o["stripe_session_id"] and payments.stripe_enabled():
        try:
            session = payments.retrieve_session(o["stripe_session_id"])
            if getattr(session, "payment_status", None) == "paid":
                orders.fulfil_order(o["id"], getattr(session, "payment_intent", None))
                o = _order_for(ref, user)
        except Exception:
            log.exception("Couldn't verify the Stripe session")
    return _order_json(o)


@router.post("/orders/{ref}/resend")
def resend(ref: str, request: Request):
    user = require_user(request)
    o = _order_for(ref, user)
    if o["status"] != "paid":
        raise HTTPException(409, "This order hasn't been paid yet.")
    ok = orders.send_order_email(o["id"])
    o = _order_for(ref, user)
    if not ok:
        raise HTTPException(502, o["email_error"] or "The email couldn't be sent.")
    return {"ok": True}


@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    if not (payments.stripe_enabled() and config.STRIPE_WEBHOOK_SECRET):
        raise HTTPException(503, "Stripe webhooks aren't configured.")
    payload = await request.body()
    try:
        event = await run_in_threadpool(payments.verify_webhook, payload, request.headers.get("stripe-signature", ""))
    except ValueError:
        raise HTTPException(400, "Invalid payload.")
    except Exception:
        raise HTTPException(400, "Invalid signature.")
    etype = event.get("type")
    session = (event.get("data") or {}).get("object") or {}
    order_id = (session.get("metadata") or {}).get("order_id")
    if order_id and order_id.isdigit():
        if etype in ("checkout.session.completed", "checkout.session.async_payment_succeeded") and session.get("payment_status") == "paid":
            await run_in_threadpool(orders.fulfil_order, int(order_id), session.get("payment_intent"))
        elif etype in ("checkout.session.expired", "checkout.session.async_payment_failed"):
            await run_in_threadpool(db.run, "UPDATE orders SET status = 'expired' WHERE id = %s AND status = 'pending'", (int(order_id),))
    return {"received": True}


@router.get("/me/tickets")
def my_tickets(request: Request):
    user = require_user(request)
    rows = db.all_(
        """SELECT t.token, t.status, t.used_at, t.seq, t.holder_name, ti.name AS tier_name, o.public_ref,
                  e.id AS event_id, e.title, e.category, e.starts_at, e.venue, e.city, e.updated_at, (e.image IS NOT NULL) AS has_image
           FROM tickets t JOIN orders o ON o.id = t.order_id JOIN events e ON e.id = t.event_id JOIN ticket_tiers ti ON ti.id = t.tier_id
           WHERE o.user_id = %s AND t.status <> 'void' ORDER BY e.starts_at, t.id""", (user["id"],))
    out = []
    for r in rows:
        out.append({"token": r["token"], "status": r["status"], "used_at": r["used_at"].isoformat() if r["used_at"] else None,
                    "seq": r["seq"], "tier_name": r["tier_name"], "order_ref": r["public_ref"],
                    "event": {"id": r["event_id"], "title": r["title"], "category": r["category"], "starts_at": r["starts_at"].isoformat(),
                              "venue": r["venue"], "city": r["city"],
                              "image_url": f"/api/events/{r['event_id']}/image?v={int(r['updated_at'].timestamp())}" if r["has_image"] else None}})
    return {"tickets": out}


def _ticket_access(token, user):
    t = db.one("""SELECT t.token, o.user_id, e.organizer_id FROM tickets t JOIN orders o ON o.id = t.order_id
                  JOIN events e ON e.id = t.event_id WHERE t.token = %s""", (token,))
    if not t or user["id"] not in (t["user_id"], t["organizer_id"]):
        raise HTTPException(404, "Ticket not found.")


@router.get("/tickets/{token}/pdf")
def ticket_pdf(token: str, request: Request):
    _ticket_access(token, require_user(request))
    built = orders.ticket_pdf_for(token)
    if not built:
        raise HTTPException(404, "Ticket not found.")
    name, pdf = built
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "private, no-store"})


@router.get("/tickets/{token}/qr.svg")
def ticket_qr(token: str, request: Request):
    _ticket_access(token, require_user(request))
    return Response(tk.qr_svg(token), media_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})


class CheckInIn(BaseModel):
    event_id: int
    code: str = Field(max_length=100)


@router.post("/checkin")
def checkin(body: CheckInIn, request: Request):
    user = require_organizer(request)
    owned_event_or_admin(body.event_id, user)
    return orders.check_in(body.code, body.event_id, user["id"])
