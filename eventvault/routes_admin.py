"""Platform-wide admin API. Every route requires role 'admin' (require_admin). Nothing here is scoped to
"the calling user's own" anything — that's the organizer routes' job (routes_organizer.py, routes_orders.py's
/api/checkin). An admin who wants to act on one specific event they happen to own can still use those; this
file is for acting on *any* user's account, event, order or ticket."""
import logging

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import config, db, emailer, orders, payments, tickets as tk
from .deps import require_admin
from .orders import tiers_for_events
from .routes_organizer import EventEdit, SERIES_SQL, _decode_image, _dup_names, _validate_common
from .routes_public import event_card

router = APIRouter(prefix="/api/admin")
log = logging.getLogger("eventvault")


# ---------------------------------------------------------------------- users

@router.get("/users")
def list_users(request: Request, q: str = "", role: str = "",
               limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    require_admin(request)
    where, args = ["true"], []
    if q.strip():
        where.append("(u.name ILIKE %s OR u.email ILIKE %s)")
        args += [f"%{q.strip()}%"] * 2
    if role:
        if role not in ("user", "organizer", "admin"):
            raise HTTPException(400, "role must be user, organizer or admin.")
        where.append("u.role = %s"); args.append(role)
    clause = " AND ".join(where)
    total = db.one(f"SELECT count(*)::int AS n FROM users u WHERE {clause}", args)["n"]
    rows = db.all_(
        f"""SELECT u.id, u.name, u.email, u.role, u.suspended_at, u.created_at,
                   COALESCE((SELECT count(*) FROM events e WHERE e.organizer_id = u.id), 0)::int AS events_count
            FROM users u WHERE {clause} ORDER BY u.created_at DESC LIMIT %s OFFSET %s""",
        args + [limit, offset])
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["suspended_at"] = r["suspended_at"].isoformat() if r["suspended_at"] else None
    return {"total": total, "users": rows}


class RoleIn(BaseModel):
    role: str


@router.post("/users/{user_id}/role")
def set_role(user_id: int, body: RoleIn, request: Request):
    admin = require_admin(request)
    if body.role not in ("user", "organizer", "admin"):
        raise HTTPException(400, "role must be user, organizer or admin.")
    if user_id == admin["id"] and body.role != "admin":
        raise HTTPException(400, "You can't remove your own admin access.")
    n = db.run("UPDATE users SET role = %s WHERE id = %s", (body.role, user_id))
    if not n:
        raise HTTPException(404, "User not found.")
    return {"ok": True, "role": body.role}


class SuspendIn(BaseModel):
    suspended: bool


@router.post("/users/{user_id}/suspend")
def set_suspended(user_id: int, body: SuspendIn, request: Request):
    admin = require_admin(request)
    if user_id == admin["id"] and body.suspended:
        raise HTTPException(400, "You can't suspend your own account.")
    n = db.run("UPDATE users SET suspended_at = CASE WHEN %s THEN now() ELSE NULL END WHERE id = %s",
              (body.suspended, user_id))
    if not n:
        raise HTTPException(404, "User not found.")
    return {"ok": True, "suspended": body.suspended}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request):
    admin = require_admin(request)
    if user_id == admin["id"]:
        raise HTTPException(400, "You can't delete your own account.")
    if not db.one("SELECT id FROM users WHERE id = %s", (user_id,)):
        raise HTTPException(404, "User not found.")
    owns_paid_event = db.one(
        """SELECT count(*)::int AS n FROM events e JOIN orders o ON o.event_id = e.id
           WHERE e.organizer_id = %s AND o.status = 'paid'""", (user_id,))["n"]
    if owns_paid_event:
        raise HTTPException(409, "This user organises an event with paid ticket buyers, so their account can't be deleted. Suspend it instead.")
    bought_paid = db.one("SELECT count(*)::int AS n FROM orders WHERE user_id = %s AND status = 'paid'", (user_id,))["n"]
    if bought_paid:
        raise HTTPException(409, "This user has paid ticket purchases, so their account can't be deleted. Suspend it instead.")
    db.run("DELETE FROM users WHERE id = %s", (user_id,))
    return {"ok": True}


@router.get("/users/{user_id}/orders")
def user_orders(user_id: int, request: Request):
    require_admin(request)
    if not db.one("SELECT id FROM users WHERE id = %s", (user_id,)):
        raise HTTPException(404, "User not found.")
    rows = db.all_(
        """SELECT o.id, o.public_ref, o.status, o.total_cents, o.currency, o.refunded_cents, o.created_at, o.paid_at,
                  e.id AS event_id, e.title AS event_title
           FROM orders o JOIN events e ON e.id = o.event_id WHERE o.user_id = %s ORDER BY o.created_at DESC""", (user_id,))
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["paid_at"] = r["paid_at"].isoformat() if r["paid_at"] else None
    return {"orders": rows}


@router.get("/users/{user_id}/events")
def user_events(user_id: int, request: Request):
    require_admin(request)
    if not db.one("SELECT id FROM users WHERE id = %s", (user_id,)):
        raise HTTPException(404, "User not found.")
    rows = db.all_(
        """SELECT id, title, category, city, starts_at, status, featured
           FROM events WHERE organizer_id = %s ORDER BY starts_at DESC""", (user_id,))
    for r in rows:
        r["starts_at"] = r["starts_at"].isoformat()
    return {"events": rows}


# ---------------------------------------------------------------- organizer requests

@router.get("/organizer-requests")
def list_organizer_requests(request: Request, status: str = "pending"):
    require_admin(request)
    if status not in ("pending", "approved", "denied", "all"):
        raise HTTPException(400, "status must be pending, approved, denied or all.")
    where, args = ("", ()) if status == "all" else ("WHERE r.status = %s", (status,))
    rows = db.all_(
        f"""SELECT r.id, r.message, r.status, r.created_at, r.reviewed_at,
                   u.id AS user_id, u.name AS user_name, u.email AS user_email,
                   rv.name AS reviewed_by_name
            FROM organizer_requests r JOIN users u ON u.id = r.user_id LEFT JOIN users rv ON rv.id = r.reviewed_by
            {where} ORDER BY r.created_at DESC""", args)
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["reviewed_at"] = r["reviewed_at"].isoformat() if r["reviewed_at"] else None
    return {"requests": rows}


@router.post("/organizer-requests/{request_id}/approve")
def approve_organizer_request(request_id: int, request: Request):
    admin = require_admin(request)
    with db.conn() as c:
        req = c.execute(
            """UPDATE organizer_requests SET status = 'approved', reviewed_by = %s, reviewed_at = now()
               WHERE id = %s AND status = 'pending' RETURNING user_id""", (admin["id"], request_id)).fetchone()
        if not req:
            raise HTTPException(409, "This request has already been reviewed.")
        c.execute("UPDATE users SET role = 'organizer' WHERE id = %s AND role = 'user'", (req["user_id"],))
    return {"ok": True}


class DenyIn(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/organizer-requests/{request_id}/deny")
def deny_organizer_request(request_id: int, body: DenyIn, request: Request):
    admin = require_admin(request)
    n = db.run(
        """UPDATE organizer_requests SET status = 'denied', reviewed_by = %s, reviewed_at = now()
           WHERE id = %s AND status = 'pending'""", (admin["id"], request_id))
    if not n:
        raise HTTPException(409, "This request has already been reviewed.")
    return {"ok": True}


# ---------------------------------------------------------------------- events

ADMIN_LIST_SQL = """
SELECT e.id, e.title, e.category, e.description, e.venue, e.city, e.starts_at, e.featured, e.updated_at, e.status,
       e.organizer_id, (e.image IS NOT NULL) AS has_image, u.name AS organizer_name, u.email AS organizer_email
FROM events e JOIN users u ON u.id = e.organizer_id
"""


@router.get("/events")
def list_events(request: Request, q: str = "", category: str = "", city: str = "", organizer_id: int = 0,
                status: str = "", limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    require_admin(request)
    where, args = ["true"], []
    if q.strip():
        where.append("(e.title ILIKE %s OR e.description ILIKE %s OR e.city ILIKE %s OR e.venue ILIKE %s)")
        args += [f"%{q.strip()}%"] * 4
    if category:
        where.append("e.category = %s"); args.append(category)
    if city:
        where.append("e.city = %s"); args.append(city)
    if organizer_id:
        where.append("e.organizer_id = %s"); args.append(organizer_id)
    if status:
        if status not in ("active", "cancelled"):
            raise HTTPException(400, "status must be active or cancelled.")
        where.append("e.status = %s"); args.append(status)
    clause = " AND ".join(where)
    total = db.one(f"SELECT count(*)::int AS n FROM events e WHERE {clause}", args)["n"]
    rows = db.all_(ADMIN_LIST_SQL + f" WHERE {clause} ORDER BY e.starts_at DESC LIMIT %s OFFSET %s", args + [limit, offset])
    tiers = tiers_for_events([r["id"] for r in rows])
    events = []
    for r in rows:
        card = event_card(r, tiers.get(r["id"], []))
        card.update(status=r["status"], organizer_id=r["organizer_id"], organizer_email=r["organizer_email"])
        events.append(card)
    return {"total": total, "events": events}


@router.put("/events/{event_id}")
def update_event(event_id: int, body: EventEdit, request: Request):
    require_admin(request)
    if not db.one("SELECT id FROM events WHERE id = %s", (event_id,)):
        raise HTTPException(404, "Event not found.")
    starts = _validate_common(body)
    img, img_type = _decode_image(body.image)
    existing = {t["id"]: t for t in db.all_("SELECT id, name, sold FROM ticket_tiers WHERE event_id = %s", (event_id,))}
    _dup_names([t.name for t in body.tiers] + [t.name for t in body.new_tiers])
    for t in body.tiers:
        if t.id not in existing:
            raise HTTPException(400, "One of the ticket types doesn't belong to this event.")
        if t.quantity < existing[t.id]["sold"]:
            raise HTTPException(409, f"{t.name}: {existing[t.id]['sold']} tickets are already sold, so capacity can't go below that.")
    with db.conn() as c:
        c.execute("""UPDATE events SET title=%s, category=%s, description=%s, venue=%s, city=%s, starts_at=%s,
                     contact_email=%s, contact_phone=%s, updated_at=now() WHERE id=%s""",
                  (body.title.strip(), body.category, body.description.strip(), body.venue.strip(), body.city.strip(), starts,
                   body.contact_email.strip(), (body.contact_phone or "").strip() or None, event_id))
        if img:
            c.execute("UPDATE events SET image=%s, image_type=%s WHERE id=%s", (img, img_type, event_id))
        elif body.remove_image:
            c.execute("UPDATE events SET image=NULL, image_type=NULL WHERE id=%s", (event_id,))
        for t in body.tiers:
            c.execute("UPDATE ticket_tiers SET name=%s, quantity=%s WHERE id=%s AND event_id=%s", (t.name.strip(), t.quantity, t.id, event_id))
        base = len(existing)
        for i, t in enumerate(body.new_tiers):
            c.execute("INSERT INTO ticket_tiers (event_id, name, price_cents, quantity, sort_order) VALUES (%s,%s,%s,%s,%s)",
                      (event_id, t.name.strip(), round(t.price * 100), t.quantity, base + i))
    if body.new_tiers and payments.stripe_enabled():
        try:
            payments.ensure_stripe_prices(event_id)
        except Exception:
            pass
    return {"ok": True}


class FeatureIn(BaseModel):
    featured: bool


@router.post("/events/{event_id}/feature")
def feature_event(event_id: int, body: FeatureIn, request: Request):
    require_admin(request)
    n = db.run("UPDATE events SET featured = %s, updated_at = now() WHERE id = %s", (body.featured, event_id))
    if not n:
        raise HTTPException(404, "Event not found.")
    return {"ok": True}


def _cancellation_email(buyer_name, event_title, reason):
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (
        "<div style='font-family:Arial,Helvetica,sans-serif;background:#0B1020;padding:24px'>"
        "<div style='max-width:520px;margin:0 auto;background:#182238;border:1px solid #263452;border-radius:16px;padding:28px'>"
        f"<h1 style='font-size:20px;margin:0 0 12px;color:#F8FAFC'>{esc(event_title)} has been cancelled</h1>"
        f"<p style='color:#94A3B8;line-height:1.5'>Hi {esc(buyer_name.split(' ')[0])}, we're sorry to say this event won't be going ahead. {esc(reason)}</p>"
        "<p style='color:#94A3B8;line-height:1.5'>Your ticket has been voided. If you paid for it, contact the organiser about a refund.</p>"
        "</div></div>")
    text = f"{event_title} has been cancelled.\n\n{reason}\n\nYour ticket has been voided. Contact the organiser about a refund if you paid."
    return html, text


def _cancel_event(event_id, reason):
    """Marks the event cancelled and voids every outstanding ticket for it. Returns False if it was already
    cancelled (nothing to do). Emailing buyers is best-effort and never allowed to break the cancellation
    itself — same philosophy as orders.py's send_order_email."""
    reason = (reason or "").strip() or "The organiser cancelled this event."
    with db.conn() as c:
        ev = c.execute(
            "UPDATE events SET status = 'cancelled', cancelled_at = now(), updated_at = now() WHERE id = %s AND status = 'active' RETURNING id, title",
            (event_id,)).fetchone()
        if not ev:
            return False
        c.execute("UPDATE tickets SET status = 'void', void_reason = %s WHERE event_id = %s AND status <> 'void'", (reason, event_id))
    buyers = db.all_("SELECT DISTINCT buyer_email, buyer_name FROM orders WHERE event_id = %s AND status = 'paid'", (event_id,))
    for b in buyers:
        try:
            html, text = _cancellation_email(b["buyer_name"], ev["title"], reason)
            emailer.send_email(b["buyer_email"], f"{ev['title']} has been cancelled", html, text)
        except Exception:
            log.exception("Couldn't email a buyer about an event cancellation")
    return True


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.post("/events/{event_id}/cancel")
def cancel_event(event_id: int, body: CancelIn, request: Request):
    require_admin(request)
    if not db.one("SELECT id FROM events WHERE id = %s", (event_id,)):
        raise HTTPException(404, "Event not found.")
    if not _cancel_event(event_id, body.reason):
        raise HTTPException(409, "This event is already cancelled.")
    return {"ok": True}


@router.delete("/events/{event_id}")
def delete_event(event_id: int, request: Request, force: bool = False):
    require_admin(request)
    ev = db.one("SELECT id, status FROM events WHERE id = %s", (event_id,))
    if not ev:
        raise HTTPException(404, "Event not found.")
    paid = db.one("SELECT count(*)::int AS n FROM orders WHERE event_id = %s AND status = 'paid'", (event_id,))["n"]
    if paid:
        if not force:
            raise HTTPException(409, "This event has paid ticket buyers. Pass force=true to cancel it and delete it anyway.")
        if ev["status"] == "active":
            _cancel_event(event_id, "Event deleted by an administrator.")
    db.run("DELETE FROM events WHERE id = %s", (event_id,))
    return {"ok": True}


# ---------------------------------------------------------------------- orders & refunds

@router.get("/orders")
def list_orders(request: Request, q: str = "", status: str = "", event_id: int = 0,
                limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    require_admin(request)
    where, args = ["true"], []
    if q.strip():
        where.append("(o.buyer_name ILIKE %s OR o.buyer_email ILIKE %s OR o.public_ref ILIKE %s OR e.title ILIKE %s)")
        args += [f"%{q.strip()}%"] * 4
    if status:
        if status not in ("pending", "paid", "expired", "failed"):
            raise HTTPException(400, "Invalid status filter.")
        where.append("o.status = %s"); args.append(status)
    if event_id:
        where.append("o.event_id = %s"); args.append(event_id)
    clause = " AND ".join(where)
    total = db.one(f"SELECT count(*)::int AS n FROM orders o JOIN events e ON e.id = o.event_id WHERE {clause}", args)["n"]
    rows = db.all_(
        f"""SELECT o.id, o.public_ref, o.status, o.payment_mode, o.total_cents, o.currency, o.refunded_cents,
                   o.buyer_name, o.buyer_email, o.created_at, o.paid_at, e.id AS event_id, e.title AS event_title
            FROM orders o JOIN events e ON e.id = o.event_id WHERE {clause}
            ORDER BY o.created_at DESC LIMIT %s OFFSET %s""", args + [limit, offset])
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
        r["paid_at"] = r["paid_at"].isoformat() if r["paid_at"] else None
    return {"total": total, "orders": rows}


@router.post("/orders/{order_id}/resend")
def resend_order(order_id: int, request: Request):
    require_admin(request)
    o = db.one("SELECT id, status FROM orders WHERE id = %s", (order_id,))
    if not o:
        raise HTTPException(404, "Order not found.")
    if o["status"] != "paid":
        raise HTTPException(409, "This order hasn't been paid yet.")
    ok = orders.send_order_email(order_id)
    if not ok:
        fresh = db.one("SELECT email_error FROM orders WHERE id = %s", (order_id,))
        raise HTTPException(502, fresh["email_error"] or "The email couldn't be sent.")
    return {"ok": True}


@router.get("/orders/{order_id}/tickets")
def order_tickets(order_id: int, request: Request):
    """Every ticket row of an order (including voided ones and reissues), for the admin's void / reissue /
    reset panel."""
    require_admin(request)
    if not db.one("SELECT id FROM orders WHERE id = %s", (order_id,)):
        raise HTTPException(404, "Order not found.")
    rows = db.all_(
        """SELECT t.token, t.seq, t.status, t.holder_name, t.used_at, t.void_reason, ti.name AS tier_name,
                  (t.reissued_from IS NOT NULL) AS is_reissue
           FROM tickets t JOIN ticket_tiers ti ON ti.id = t.tier_id
           WHERE t.order_id = %s ORDER BY t.seq, t.id""", (order_id,))
    for r in rows:
        r["used_at"] = r["used_at"].isoformat() if r["used_at"] else None
    return {"tickets": rows}


class RefundIn(BaseModel):
    amount_cents: int | None = Field(default=None, ge=1)


@router.post("/orders/{order_id}/refund")
def refund_order(order_id: int, body: RefundIn, request: Request):
    require_admin(request)
    o = db.one(
        "SELECT id, payment_mode, total_cents, refunded_cents, stripe_payment_intent_id, status FROM orders WHERE id = %s",
        (order_id,))
    if not o:
        raise HTTPException(404, "Order not found.")
    if o["status"] != "paid":
        raise HTTPException(400, "Only a paid order can be refunded.")
    if o["payment_mode"] != "stripe":
        raise HTTPException(400, "Only Stripe orders can be refunded here.")
    if not o["stripe_payment_intent_id"]:
        raise HTTPException(400, "This order predates refund support and can't be refunded automatically — refund it directly in the Stripe dashboard.")
    remaining = o["total_cents"] - o["refunded_cents"]
    if remaining <= 0:
        raise HTTPException(400, "This order has already been fully refunded.")
    amount = body.amount_cents if body.amount_cents is not None else remaining
    if amount > remaining:
        raise HTTPException(400, f"You can refund at most {remaining} cents on this order.")
    # Reserve the amount first, in one atomic UPDATE, so two admins refunding at the same moment can't
    # together exceed what was paid. If Stripe then fails, hand the reservation back.
    reserved = db.one(
        """UPDATE orders SET refunded_cents = refunded_cents + %s, refunded_at = now()
           WHERE id = %s AND status = 'paid' AND refunded_cents + %s <= total_cents RETURNING id""",
        (amount, order_id, amount))
    if not reserved:
        raise HTTPException(409, "This order was just refunded by someone else. Reload and check the remaining amount.")
    try:
        payments.refund_payment_intent(o["stripe_payment_intent_id"], amount)
    except Exception:
        log.exception("Stripe refund failed")
        db.run("UPDATE orders SET refunded_cents = refunded_cents - %s WHERE id = %s", (amount, order_id))
        raise HTTPException(502, "Stripe couldn't process the refund. Please try again.")
    return {"ok": True, "refunded_cents": amount}


# ---------------------------------------------------------------------- tickets

class ReasonIn(BaseModel):
    reason: str = Field(default="", max_length=300)


@router.post("/tickets/{token}/void")
def void_ticket(token: str, body: ReasonIn, request: Request):
    require_admin(request)
    reason = body.reason.strip() or "Voided by an administrator."
    row = db.one(
        "UPDATE tickets SET status = 'void', void_reason = %s WHERE token = %s AND status IN ('valid', 'used') RETURNING id",
        (reason, token))
    if row:
        return {"ok": True}
    if not db.one("SELECT id FROM tickets WHERE token = %s", (token,)):
        raise HTTPException(404, "Ticket not found.")
    raise HTTPException(409, "This ticket is already void.")


@router.post("/tickets/{token}/reset")
def reset_ticket(token: str, request: Request):
    require_admin(request)
    row = db.one(
        "UPDATE tickets SET status = 'valid', used_at = NULL, used_by = NULL WHERE token = %s AND status = 'used' RETURNING id",
        (token,))
    if row:
        return {"ok": True}
    if not db.one("SELECT id FROM tickets WHERE token = %s", (token,)):
        raise HTTPException(404, "Ticket not found.")
    raise HTTPException(409, "This ticket isn't marked used.")


@router.post("/tickets/{token}/reissue")
def reissue_ticket(token: str, body: ReasonIn, request: Request):
    require_admin(request)
    reason = body.reason.strip() or "Reissued by an administrator."
    with db.conn() as c:
        old = c.execute(
            """UPDATE tickets SET status = 'void', void_reason = %s WHERE token = %s AND status IN ('valid', 'used')
               RETURNING id, order_id, event_id, tier_id, holder_name, seq""", (reason, token)).fetchone()
        if not old:
            if not c.execute("SELECT id FROM tickets WHERE token = %s", (token,)).fetchone():
                raise HTTPException(404, "Ticket not found.")
            raise HTTPException(409, "This ticket is already void and can't be reissued.")
        new_token = tk.new_token()
        c.execute(
            """INSERT INTO tickets (token, order_id, event_id, tier_id, holder_name, seq, reissued_from)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (new_token, old["order_id"], old["event_id"], old["tier_id"], old["holder_name"], old["seq"], old["id"]))
    return {"ok": True, "token": new_token}


# ---------------------------------------------------------------------- scans

@router.get("/scans")
def list_scans(request: Request, event_id: int = 0, result: str = "",
              limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    require_admin(request)
    where, args = ["true"], []
    if event_id:
        where.append("s.event_id = %s"); args.append(event_id)
    if result:
        if result not in ("ok", "already_used", "wrong_event", "invalid", "void"):
            raise HTTPException(400, "Invalid result filter.")
        where.append("s.result = %s"); args.append(result)
    clause = " AND ".join(where)
    total = db.one(f"SELECT count(*)::int AS n FROM scans s WHERE {clause}", args)["n"]
    rows = db.all_(
        f"""SELECT s.id, s.result, s.created_at, s.code_hint, s.event_id, e.title AS event_title,
                   t.holder_name, ti.name AS tier_name, u.name AS scanned_by_name
            FROM scans s JOIN events e ON e.id = s.event_id
            LEFT JOIN tickets t ON t.id = s.ticket_id LEFT JOIN ticket_tiers ti ON ti.id = t.tier_id
            LEFT JOIN users u ON u.id = s.scanned_by
            WHERE {clause} ORDER BY s.created_at DESC, s.id DESC LIMIT %s OFFSET %s""", args + [limit, offset])
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return {"total": total, "scans": rows}


# ---------------------------------------------------------------------- messages

@router.get("/messages")
def list_messages(request: Request, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    require_admin(request)
    total = db.one("SELECT count(*)::int AS n FROM messages")["n"]
    rows = db.all_("SELECT id, name, email, message, created_at FROM messages ORDER BY created_at DESC LIMIT %s OFFSET %s", (limit, offset))
    for r in rows:
        r["created_at"] = r["created_at"].isoformat()
    return {"total": total, "messages": rows}


@router.delete("/messages/{message_id}")
def delete_message(message_id: int, request: Request):
    require_admin(request)
    n = db.run("DELETE FROM messages WHERE id = %s", (message_id,))
    if not n:
        raise HTTPException(404, "Message not found.")
    return {"ok": True}


# ---------------------------------------------------------------------- platform analytics

@router.get("/overview")
def platform_overview(request: Request):
    require_admin(request)
    stats = db.one(
        """SELECT
             (SELECT count(*) FROM users)::int AS total_users,
             (SELECT count(*) FROM events)::int AS total_events,
             (SELECT count(*) FROM tickets WHERE status <> 'void')::int AS tickets_sold,
             (SELECT count(*) FROM tickets WHERE status = 'used')::int AS checked_in,
             (SELECT COALESCE(sum(total_cents), 0) FROM orders WHERE status = 'paid')::int AS revenue_cents,
             (SELECT COALESCE(sum(refunded_cents), 0) FROM orders WHERE status = 'paid')::int AS refunded_cents,
             (SELECT count(*) FROM organizer_requests WHERE status = 'pending')::int AS pending_requests""")
    series = db.all_(SERIES_SQL.format(scope="true"))
    for s in series:
        s["day"] = s["day"].isoformat()
    return {"stats": stats, "sales_by_day": series}


@router.get("/breakdown")
def platform_breakdown(request: Request):
    require_admin(request)
    by_category = db.all_(
        """SELECT e.category, count(DISTINCT e.id)::int AS events,
                  COALESCE(SUM(oi.quantity * oi.unit_price_cents) FILTER (WHERE o.status = 'paid'), 0)::int AS revenue_cents
           FROM events e LEFT JOIN orders o ON o.event_id = e.id LEFT JOIN order_items oi ON oi.order_id = o.id
           GROUP BY e.category ORDER BY revenue_cents DESC""")
    by_city = db.all_(
        """SELECT e.city, count(DISTINCT e.id)::int AS events,
                  COALESCE(SUM(oi.quantity * oi.unit_price_cents) FILTER (WHERE o.status = 'paid'), 0)::int AS revenue_cents
           FROM events e LEFT JOIN orders o ON o.event_id = e.id LEFT JOIN order_items oi ON oi.order_id = o.id
           GROUP BY e.city ORDER BY revenue_cents DESC""")
    return {"by_category": by_category, "by_city": by_city}


# ---------------------------------------------------------------------- system

@router.get("/system")
def system_status(request: Request):
    require_admin(request)
    return {
        "payments_mode": config.PAYMENTS_MODE,
        "email_enabled": emailer.email_enabled(),
        "stripe_webhook_configured": bool(config.STRIPE_WEBHOOK_SECRET),
    }
