from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from . import config, db, emailer, security
from .deps import current_user
from .orders import tiers_for_events

router = APIRouter(prefix="/api")

UPCOMING = "e.starts_at >= (now() AT TIME ZONE 'UTC') - interval '12 hours'"
ACTIVE = "e.status = 'active'"


def event_card(e, tiers):
    """Public summary of an event (used by every card on the site)."""
    paid = [t["price_cents"] for t in tiers]
    seats = sum(t["available"] for t in tiers)
    return {
        "id": e["id"], "title": e["title"], "category": e["category"], "venue": e["venue"], "city": e["city"],
        "short_description": (e["description"][:150].rsplit(" ", 1)[0] + "…") if len(e["description"]) > 150 else e["description"],
        "starts_at": e["starts_at"].isoformat(), "featured": e["featured"],
        "image_url": f"/api/events/{e['id']}/image?v={int(e['updated_at'].timestamp())}" if e.get("has_image") else None,
        "min_price_cents": min(paid) if paid else 0, "max_price_cents": max(paid) if paid else 0,
        "seats_left": seats, "sold_out": bool(tiers) and seats == 0, "organizer_name": e["organizer_name"],
    }


LIST_SQL = f"""
SELECT e.id, e.title, e.category, e.description, e.venue, e.city, e.starts_at, e.featured, e.updated_at, e.status,
       (e.image IS NOT NULL) AS has_image, u.name AS organizer_name
FROM events e JOIN users u ON u.id = e.organizer_id
"""


@router.get("/meta")
def meta():
    counts = {r["category"]: r["n"] for r in db.all_(f"SELECT category, count(*)::int AS n FROM events e WHERE {UPCOMING} AND {ACTIVE} GROUP BY 1")}
    cities = [r["city"] for r in db.all_(f"SELECT city FROM events e WHERE {UPCOMING} AND {ACTIVE} GROUP BY city ORDER BY count(*) DESC, city")]
    return {
        "categories": [{"name": c, "count": counts.get(c, 0)} for c in config.CATEGORIES],
        "cities": cities, "currency": config.CURRENCY,
        "payments_mode": config.PAYMENTS_MODE, "email_enabled": emailer.email_enabled(),
        "max_tickets": config.MAX_TICKETS_PER_ORDER,
    }


@router.get("/events")
def list_events(q: str = Query("", max_length=100), category: str = "", city: str = "", date: str = "",
                sort: str = Query("soonest", pattern="^(soonest|price_low|price_high|newest)$"),
                featured: bool = False, limit: int = Query(12, ge=1, le=50), offset: int = Query(0, ge=0),
                exclude: int = 0):
    where, args = [UPCOMING, ACTIVE], []
    if q.strip():
        where.append("(e.title ILIKE %s OR e.description ILIKE %s OR e.city ILIKE %s OR e.venue ILIKE %s OR e.category ILIKE %s)")
        args += [f"%{q.strip()}%"] * 5
    if category:
        where.append("e.category = %s"); args.append(category)
    if city:
        where.append("e.city = %s"); args.append(city)
    if date:
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, "Use the date format YYYY-MM-DD.")
        where.append("e.starts_at >= %s::date"); args.append(date)
    if featured:
        where.append("e.featured")
    if exclude:
        where.append("e.id <> %s"); args.append(exclude)
    base = LIST_SQL + " WHERE " + " AND ".join(where)
    total = db.one("SELECT count(*)::int AS n FROM events e WHERE " + " AND ".join(where), args)["n"]
    order = {"soonest": "e.starts_at, e.id", "newest": "e.created_at DESC, e.id DESC",
             "price_low": "(SELECT min(price_cents) FROM ticket_tiers t WHERE t.event_id = e.id), e.starts_at",
             "price_high": "(SELECT max(price_cents) FROM ticket_tiers t WHERE t.event_id = e.id) DESC, e.starts_at"}[sort]
    rows = db.all_(base + f" ORDER BY {'e.featured DESC, ' if featured else ''}{order} LIMIT %s OFFSET %s", args + [limit, offset])
    tiers = tiers_for_events([r["id"] for r in rows])
    return {"total": total, "events": [event_card(r, tiers.get(r["id"], [])) for r in rows]}


@router.get("/events/{event_id}")
def get_event(event_id: int, request: Request):
    e = db.one(LIST_SQL.replace("u.name AS organizer_name", "u.name AS organizer_name, e.organizer_id, e.contact_email, e.contact_phone, e.created_at")
               + " WHERE e.id = %s", (event_id,))
    if not e:
        raise HTTPException(404, "We couldn't find that event. It may have been removed.")
    if e["status"] != "active":
        viewer = current_user(request)
        is_owner_or_admin = viewer and (viewer["id"] == e["organizer_id"] or viewer["role"] == "admin")
        if not is_owner_or_admin:
            raise HTTPException(404, "We couldn't find that event. It may have been removed.")
    tiers = tiers_for_events([event_id]).get(event_id, [])
    card = event_card(e, tiers)
    card.update({
        "description": e["description"], "organizer_id": e["organizer_id"], "status": e["status"],
        "contact_email": e["contact_email"], "contact_phone": e["contact_phone"],
        "tiers": [{"id": t["id"], "name": t["name"], "price_cents": t["price_cents"], "quantity": t["quantity"], "available": t["available"]} for t in tiers],
    })
    return card


@router.get("/events/{event_id}/image")
def event_image(event_id: int):
    row = db.one("SELECT image, image_type FROM events WHERE id = %s", (event_id,))
    if not row or not row["image"]:
        raise HTTPException(404, "No image.")
    return Response(bytes(row["image"]), media_type=row["image_type"] or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=200)
    message: str = Field(min_length=10, max_length=3000)


@router.post("/contact")
def contact(body: ContactIn):
    if not security.EMAIL_RE.match(body.email.strip()):
        raise HTTPException(400, "Enter a valid email address.")
    db.run("INSERT INTO messages (name, email, message) VALUES (%s,%s,%s)", (body.name.strip(), body.email.strip(), body.message.strip()))
    return {"ok": True}
