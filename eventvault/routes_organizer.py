import base64
import binascii
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import config, db, payments, security
from .deps import owned_event, require_organizer
from .orders import tiers_for_events

router = APIRouter(prefix="/api")

MAX_IMAGE_BYTES = 2_500_000


class TierIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    price: float = Field(ge=0, le=100000)
    quantity: int = Field(ge=1, le=100000)


class EventIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    category: str
    description: str = Field(min_length=10, max_length=5000)
    venue: str = Field(min_length=2, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    date: str
    time: str
    contact_email: str = Field(max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    image: str | None = None                 # data URL, already shrunk by the browser
    tiers: list[TierIn] = Field(min_length=1, max_length=6)


class TierEdit(BaseModel):
    id: int
    name: str = Field(min_length=1, max_length=40)
    quantity: int = Field(ge=1, le=100000)


class EventEdit(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    category: str
    description: str = Field(min_length=10, max_length=5000)
    venue: str = Field(min_length=2, max_length=160)
    city: str = Field(min_length=2, max_length=80)
    date: str
    time: str
    contact_email: str = Field(max_length=200)
    contact_phone: str | None = Field(default=None, max_length=40)
    image: str | None = None
    remove_image: bool = False
    tiers: list[TierEdit] = []               # existing tiers: name and capacity can change, price can't
    new_tiers: list[TierIn] = Field(default=[], max_length=6)


def _validate_common(b):
    if b.category not in config.CATEGORIES:
        raise HTTPException(400, "Choose one of the listed categories.")
    if not security.EMAIL_RE.match(b.contact_email.strip()):
        raise HTTPException(400, "Enter a valid contact email address.")
    try:
        return datetime.strptime(f"{b.date} {b.time}", "%Y-%m-%d %H:%M")
    except ValueError:
        raise HTTPException(400, "Enter the date and time of the event.")


def _decode_image(data_url):
    if not data_url:
        return None, None
    try:
        head, b64 = data_url.split(",", 1)
        raw = base64.b64decode(b64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(400, "That image couldn't be read. Try a JPG or PNG.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "That image is too large. Please use one under 2.5 MB.")
    if raw[:3] == b"\xff\xd8\xff":
        return raw, "image/jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw, "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return raw, "image/webp"
    raise HTTPException(400, "Only JPG, PNG or WebP images are supported.")


def _dup_names(names):
    low = [n.strip().lower() for n in names]
    if len(set(low)) != len(low):
        raise HTTPException(400, "Each ticket type needs a different name.")


@router.post("/events")
def create_event(body: EventIn, request: Request):
    user = require_organizer(request)
    starts = _validate_common(body)
    if starts < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=12):
        raise HTTPException(400, "Choose a date and time in the future.")
    img, img_type = _decode_image(body.image)
    _dup_names([t.name for t in body.tiers])
    with db.conn() as c:
        ev = c.execute(
            """INSERT INTO events (organizer_id, title, category, description, venue, city, starts_at, contact_email, contact_phone, image, image_type)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (user["id"], body.title.strip(), body.category, body.description.strip(), body.venue.strip(), body.city.strip(), starts,
             body.contact_email.strip(), (body.contact_phone or "").strip() or None, img, img_type)).fetchone()
        for i, t in enumerate(body.tiers):
            c.execute("INSERT INTO ticket_tiers (event_id, name, price_cents, quantity, sort_order) VALUES (%s,%s,%s,%s,%s)",
                      (ev["id"], t.name.strip(), round(t.price * 100), t.quantity, i))
    synced = False
    if payments.stripe_enabled():
        try:
            synced = payments.ensure_stripe_prices(ev["id"])       # a separate Stripe Price per paid tier
        except Exception:
            synced = False                                          # retried automatically at first checkout
    return {"id": ev["id"], "stripe_synced": synced, "payments_mode": config.PAYMENTS_MODE}


@router.put("/events/{event_id}")
def update_event(event_id: int, body: EventEdit, request: Request):
    user = require_organizer(request)
    owned_event(event_id, user)
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


@router.delete("/events/{event_id}")
def delete_event(event_id: int, request: Request):
    user = require_organizer(request)
    owned_event(event_id, user)
    paid = db.one("SELECT count(*)::int AS n FROM orders WHERE event_id = %s AND status = 'paid'", (event_id,))["n"]
    if paid:
        raise HTTPException(409, "This event already has ticket buyers, so it can't be deleted. Contact your attendees and stop selling by setting capacity to the number sold.")
    db.run("DELETE FROM events WHERE id = %s", (event_id,))
    return {"ok": True}


@router.get("/me/events")
def my_events(request: Request):
    user = require_organizer(request)
    rows = db.all_(
        """SELECT e.id, e.title, e.category, e.venue, e.city, e.starts_at, e.featured, e.updated_at, (e.image IS NOT NULL) AS has_image,
                  COALESCE((SELECT count(*) FROM tickets t WHERE t.event_id = e.id AND t.status <> 'void'), 0)::int AS tickets_sold,
                  COALESCE((SELECT count(*) FROM tickets t WHERE t.event_id = e.id AND t.status = 'used'), 0)::int AS checked_in,
                  COALESCE((SELECT sum(oi.quantity * oi.unit_price_cents) FROM order_items oi JOIN orders o ON o.id = oi.order_id
                            WHERE o.event_id = e.id AND o.status = 'paid'), 0)::int AS revenue_cents,
                  (SELECT sum(quantity) FROM ticket_tiers t WHERE t.event_id = e.id)::int AS capacity
           FROM events e WHERE e.organizer_id = %s ORDER BY e.starts_at DESC""", (user["id"],))
    for r in rows:
        r["starts_at"] = r["starts_at"].isoformat()
        r["image_url"] = f"/api/events/{r['id']}/image?v={int(r['updated_at'].timestamp())}" if r["has_image"] else None
        del r["updated_at"]
    return {"events": rows}


SERIES_SQL = """
SELECT d::date AS day, COALESCE(s.n, 0)::int AS tickets
FROM generate_series(current_date - 13, current_date, interval '1 day') d
LEFT JOIN (SELECT o.paid_at::date AS day, sum(oi.quantity) AS n
           FROM orders o JOIN order_items oi ON oi.order_id = o.id
           WHERE o.status = 'paid' AND {scope} GROUP BY 1) s ON s.day = d::date
ORDER BY d
"""


@router.get("/me/overview")
def overview(request: Request):
    user = require_organizer(request)
    uid = user["id"]
    stats = db.one(
        """SELECT
             (SELECT count(*) FROM tickets t JOIN orders o ON o.id = t.order_id WHERE o.user_id = %(u)s AND t.status <> 'void')::int AS tickets_bought,
             (SELECT count(DISTINCT o.event_id) FROM orders o JOIN events e ON e.id = o.event_id
                WHERE o.user_id = %(u)s AND o.status = 'paid' AND e.starts_at >= (now() AT TIME ZONE 'UTC') - interval '12 hours')::int AS upcoming_registered,
             (SELECT count(*) FROM events WHERE organizer_id = %(u)s)::int AS events_created,
             (SELECT count(*) FROM tickets t JOIN events e ON e.id = t.event_id WHERE e.organizer_id = %(u)s AND t.status <> 'void')::int AS tickets_sold,
             (SELECT COALESCE(sum(oi.quantity * oi.unit_price_cents), 0) FROM order_items oi JOIN orders o ON o.id = oi.order_id
                JOIN events e ON e.id = o.event_id WHERE e.organizer_id = %(u)s AND o.status = 'paid')::int AS revenue_cents,
             (SELECT count(*) FROM tickets t JOIN events e ON e.id = t.event_id WHERE e.organizer_id = %(u)s AND t.status = 'used')::int AS checked_in""",
        {"u": uid})
    series = db.all_(SERIES_SQL.format(scope="o.event_id IN (SELECT id FROM events WHERE organizer_id = %s)"), (uid,))
    for s in series:
        s["day"] = s["day"].isoformat()
    return {"stats": stats, "sales_by_day": series}


@router.get("/events/{event_id}/stats")
def event_stats(event_id: int, request: Request):
    user = require_organizer(request)
    ev = owned_event(event_id, user)
    tiers = db.all_(
        """SELECT t.id, t.name, t.price_cents, t.quantity,
                  COALESCE((SELECT count(*) FROM tickets x WHERE x.tier_id = t.id AND x.status <> 'void'), 0)::int AS sold,
                  COALESCE((SELECT count(*) FROM tickets x WHERE x.tier_id = t.id AND x.status = 'used'), 0)::int AS checked_in
           FROM ticket_tiers t WHERE t.event_id = %s ORDER BY t.sort_order, t.id""", (event_id,))
    for t in tiers:
        t["revenue_cents"] = t["sold"] * t["price_cents"]
    series = db.all_(SERIES_SQL.format(scope="o.event_id = %s"), (event_id,))
    for s in series:
        s["day"] = s["day"].isoformat()
    blocked = db.one("SELECT count(*)::int AS n FROM scans WHERE event_id = %s AND result = 'already_used'", (event_id,))["n"]
    return {"title": ev["title"], "tiers": tiers, "sales_by_day": series, "blocked_duplicates": blocked,
            "totals": {"sold": sum(t["sold"] for t in tiers), "capacity": sum(t["quantity"] for t in tiers),
                       "revenue_cents": sum(t["revenue_cents"] for t in tiers), "checked_in": sum(t["checked_in"] for t in tiers)}}


@router.get("/events/{event_id}/edit")
def event_for_edit(event_id: int, request: Request):
    """Everything the edit form needs, including tier prices and how many of each are sold."""
    user = require_organizer(request)
    ev = owned_event(event_id, user)
    tiers = db.all_("SELECT id, name, price_cents, quantity, sold FROM ticket_tiers WHERE event_id = %s ORDER BY sort_order, id", (event_id,))
    return {"id": ev["id"], "title": ev["title"], "category": ev["category"], "description": ev["description"], "venue": ev["venue"],
            "city": ev["city"], "date": ev["starts_at"].strftime("%Y-%m-%d"), "time": ev["starts_at"].strftime("%H:%M"),
            "contact_email": ev["contact_email"], "contact_phone": ev["contact_phone"] or "", "has_image": ev["image"] is not None,
            "image_url": f"/api/events/{ev['id']}/image?v={int(ev['updated_at'].timestamp())}" if ev["image"] else None, "tiers": tiers}


@router.get("/events/{event_id}/scans")
def event_scans(event_id: int, request: Request):
    user = require_organizer(request)
    ev = owned_event(event_id, user)
    counts = db.one("""SELECT count(*) FILTER (WHERE status <> 'void')::int AS total, count(*) FILTER (WHERE status = 'used')::int AS used
                       FROM tickets WHERE event_id = %s""", (event_id,))
    recent = db.all_(
        """SELECT s.result, s.created_at, s.code_hint, t.holder_name, ti.name AS tier_name
           FROM scans s LEFT JOIN tickets t ON t.id = s.ticket_id LEFT JOIN ticket_tiers ti ON ti.id = t.tier_id
           WHERE s.event_id = %s ORDER BY s.created_at DESC, s.id DESC LIMIT 12""", (event_id,))
    for r in recent:
        r["created_at"] = r["created_at"].isoformat()
    return {"title": ev["title"], "total": counts["total"], "checked_in": counts["used"], "recent": recent}
