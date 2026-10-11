"""Seat reservation, order fulfilment (tickets + PDF + email) and check-in."""
import logging
import secrets
from datetime import datetime, timedelta, timezone


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

import psycopg

from . import config, db, emailer, payments, tickets as tk

log = logging.getLogger("eventvault")

# Seats a tier can still sell = quantity - sold - seats held by unpaid checkouts that haven't expired yet.
AVAILABILITY_SQL = """
SELECT t.id, t.event_id, t.name, t.price_cents, t.quantity, t.sold, t.stripe_price_id,
       GREATEST(0, t.quantity - t.sold - COALESCE(r.reserved, 0))::int AS available
FROM ticket_tiers t
LEFT JOIN LATERAL (
    SELECT sum(oi.quantity) AS reserved
    FROM order_items oi JOIN orders o ON o.id = oi.order_id
    WHERE oi.tier_id = t.id AND o.status = 'pending' AND o.expires_at > now()
) r ON true
"""


class OrderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def tiers_for_events(event_ids):
    if not event_ids:
        return {}
    rows = db.all_(AVAILABILITY_SQL + " WHERE t.event_id = ANY(%s) ORDER BY t.event_id, t.sort_order, t.id", (list(event_ids),))
    out = {}
    for r in rows:
        out.setdefault(r["event_id"], []).append(r)
    return out


def create_order(user, event_id, items, site_url):
    """items: [{tier_id, quantity}]. Reserves the seats atomically, then hands off to Stripe (or completes instantly)."""
    wanted = {}
    for it in items:
        wanted[it["tier_id"]] = wanted.get(it["tier_id"], 0) + it["quantity"]
    wanted = {k: v for k, v in wanted.items() if v > 0}
    if not wanted:
        raise OrderError("Choose at least one ticket.")
    if sum(wanted.values()) > config.MAX_TICKETS_PER_ORDER:
        raise OrderError(f"You can buy up to {config.MAX_TICKETS_PER_ORDER} tickets per order.")

    ev = db.one("SELECT id, title, starts_at, status FROM events WHERE id = %s", (event_id,))
    if not ev:
        raise OrderError("That event no longer exists.", 404)
    if ev["status"] != "active":
        raise OrderError("This event has been cancelled, so tickets can't be bought.", 409)
    if ev["starts_at"] < _utcnow() - timedelta(hours=12):
        raise OrderError("This event has already taken place.")

    if payments.stripe_enabled():
        try:
            payments.ensure_stripe_prices(event_id)      # also covers events created before Stripe was configured
        except Exception as e:
            log.exception("Stripe price sync failed")
            raise OrderError("Payments are temporarily unavailable. Please try again in a moment.", 502)

    ref = secrets.token_urlsafe(12)
    with db.conn() as c:
        # Lock the tiers being bought (in id order to avoid deadlocks) so two buyers can't take the same last seat.
        ids = sorted(wanted)
        c.execute("SELECT id FROM ticket_tiers WHERE id = ANY(%s) ORDER BY id FOR UPDATE", (ids,))
        tiers = c.execute(AVAILABILITY_SQL + " WHERE t.id = ANY(%s)", (ids,)).fetchall()
        if len(tiers) != len(ids) or any(t["event_id"] != event_id for t in tiers):
            raise OrderError("One of those ticket types isn't available for this event.")
        for t in tiers:
            if wanted[t["id"]] > t["available"]:
                left = t["available"]
                raise OrderError(f"Only {left} {t['name']} ticket{'s' if left != 1 else ''} left." if left else f"{t['name']} is sold out.", 409)
        total = sum(t["price_cents"] * wanted[t["id"]] for t in tiers)
        mode = "free" if total == 0 else ("stripe" if payments.stripe_enabled() else "demo")
        expires = datetime.now(timezone.utc) + timedelta(minutes=config.CHECKOUT_MINUTES)
        order = c.execute(
            """INSERT INTO orders (public_ref, user_id, event_id, payment_mode, total_cents, currency, buyer_name, buyer_email, expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (ref, user["id"], event_id, mode, total, config.CURRENCY, user["name"], user["email"], expires)).fetchone()
        for t in tiers:
            c.execute("INSERT INTO order_items (order_id, tier_id, quantity, unit_price_cents) VALUES (%s,%s,%s,%s)",
                      (order["id"], t["id"], wanted[t["id"]], t["price_cents"]))

    order_id = order["id"]
    if mode in ("free", "demo"):
        fulfil_order(order_id)
        return {"mode": mode, "order_ref": ref}

    try:
        line_items = [{"price": t["stripe_price_id"], "quantity": wanted[t["id"]]} for t in tiers]
        if any(not li["price"] for li in line_items):
            fresh = {r["id"]: r["stripe_price_id"] for r in db.all_("SELECT id, stripe_price_id FROM ticket_tiers WHERE id = ANY(%s)", (ids,))}
            line_items = [{"price": fresh[t["id"]], "quantity": wanted[t["id"]]} for t in tiers]
        session_id, url = payments.create_checkout_session(order_id, ref, user["email"], line_items, site_url)
        db.run("UPDATE orders SET stripe_session_id = %s WHERE id = %s", (session_id, order_id))
    except Exception:
        log.exception("Stripe checkout creation failed")
        db.run("UPDATE orders SET status = 'failed' WHERE id = %s", (order_id,))     # releases the reserved seats
        raise OrderError("We couldn't start the payment. Please try again.", 502)
    return {"mode": "stripe", "order_ref": ref, "url": url}


def fulfil_order(order_id, payment_intent_id=None):
    """Marks the order paid and issues the tickets. Idempotent: only the first caller does the work
    (returns True); a webhook and the success-page check can race safely. The email is sent afterwards.

    payment_intent_id is optional and stored for later refunds (COALESCE keeps whichever caller
    supplies it first — webhook or the order-page poll, whichever wins the race above)."""
    with db.conn() as c:
        order = c.execute(
            """UPDATE orders SET status = 'paid', paid_at = now(),
                      stripe_payment_intent_id = COALESCE(stripe_payment_intent_id, %s)
               WHERE id = %s AND status IN ('pending', 'expired')
               RETURNING id, event_id, buyer_name""",
            (payment_intent_id, order_id)).fetchone()
        if not order:
            return False
        items = c.execute("SELECT tier_id, quantity FROM order_items WHERE order_id = %s ORDER BY id", (order_id,)).fetchall()
        seq = 0
        for it in items:
            c.execute("UPDATE ticket_tiers SET sold = sold + %s WHERE id = %s", (it["quantity"], it["tier_id"]))
            for _ in range(it["quantity"]):
                seq += 1
                c.execute("INSERT INTO tickets (token, order_id, event_id, tier_id, holder_name, seq) VALUES (%s,%s,%s,%s,%s,%s)",
                          (tk.new_token(), order_id, order["event_id"], it["tier_id"], order["buyer_name"], seq))
    try:
        send_order_email(order_id)
    except Exception:
        log.exception("Sending ticket email failed")
    return True


def load_order_tickets(order_id):
    return db.all_(
        """SELECT t.id, t.token, t.seq, t.status, t.holder_name, ti.name AS tier_name, ti.price_cents
           FROM tickets t JOIN ticket_tiers ti ON ti.id = t.tier_id WHERE t.order_id = %s ORDER BY t.seq""", (order_id,))


def ticket_pdf_for(token):
    """Builds the PDF for one ticket by token. Returns (filename, bytes) or None."""
    row = db.one(
        """SELECT t.token, t.seq, t.holder_name, ti.name AS tier_name, e.title, e.starts_at, e.venue, e.city, o.public_ref,
                  (SELECT count(*) FROM tickets x WHERE x.order_id = t.order_id) AS total
           FROM tickets t JOIN ticket_tiers ti ON ti.id = t.tier_id JOIN events e ON e.id = t.event_id JOIN orders o ON o.id = t.order_id
           WHERE t.token = %s""", (token,))
    if not row:
        return None
    pdf = tk.build_ticket_pdf({"token": row["token"], "event_title": row["title"], "starts_at": row["starts_at"], "venue": row["venue"],
                               "city": row["city"], "tier_name": row["tier_name"], "holder_name": row["holder_name"],
                               "seq": row["seq"], "total": row["total"], "order_ref": row["public_ref"]})
    return f"ticket-{row['token']}.pdf", pdf


def send_order_email(order_id):
    """Emails every ticket in the order as its own PDF. Records success or the reason it failed."""
    order = db.one("""SELECT o.id, o.public_ref, o.buyer_name, o.buyer_email, e.title, e.starts_at, e.venue, e.city, e.contact_email
                      FROM orders o JOIN events e ON e.id = o.event_id WHERE o.id = %s""", (order_id,))
    tix = load_order_tickets(order_id)
    if not emailer.email_enabled():
        db.run("UPDATE orders SET email_error = %s WHERE id = %s", ("Email isn't set up on this site, so your tickets weren't emailed.", order_id))
        return False
    attachments = [ticket_pdf_for(t["token"]) for t in tix]
    event = {"title": order["title"], "starts_at": order["starts_at"], "venue": order["venue"], "city": order["city"]}
    site = config.SITE_URL
    ok, err = emailer.send_email(
        order["buyer_email"], f"Your tickets for {order['title']}",
        emailer.ticket_email_html(order["buyer_name"], event, tix, order["public_ref"], site),
        emailer.ticket_email_text(order["buyer_name"], event, tix, order["public_ref"]),
        attachments=attachments, reply_to=order["contact_email"], idempotency_key=f"tickets-{order['public_ref']}")
    if ok:
        db.run("UPDATE orders SET emailed_at = now(), email_error = NULL WHERE id = %s", (order_id,))
    else:
        db.run("UPDATE orders SET email_error = %s WHERE id = %s", (err, order_id))
    return ok


# ---------------------------------------------------------------- check-in

def check_in(raw_code, event_id, scanner_id):
    """Admits a ticket exactly once.

    The whole race-condition defence is the single UPDATE below: Postgres locks the ticket row, so if two
    scanners submit the same ticket at the same instant, one UPDATE flips 'valid' -> 'used' and returns the
    row; the other waits, re-checks status = 'valid', finds it false and updates nothing."""
    token = tk.normalize_token(raw_code)
    with db.conn() as c:
        if not token:
            c.execute("INSERT INTO scans (event_id, code_hint, result, scanned_by) VALUES (%s,%s,'invalid',%s)",
                      (event_id, (raw_code or "")[:24], scanner_id))
            return {"result": "invalid", "message": "That isn't an Event Vault ticket code."}

        won = c.execute(
            """UPDATE tickets SET status = 'used', used_at = now(), used_by = %s
               WHERE token = %s AND event_id = %s AND status = 'valid' RETURNING id, tier_id, holder_name, seq, used_at""",
            (scanner_id, token, event_id)).fetchone()
        if won:
            tier = c.execute("SELECT name FROM ticket_tiers WHERE id = %s", (won["tier_id"],)).fetchone()
            c.execute("INSERT INTO scans (event_id, ticket_id, code_hint, result, scanned_by) VALUES (%s,%s,%s,'ok',%s)",
                      (event_id, won["id"], token[-9:], scanner_id))
            return {"result": "ok", "message": "Admitted.", "holder": won["holder_name"], "tier": tier["name"],
                    "seq": won["seq"], "at": won["used_at"].isoformat()}

        # Not admitted: work out why so the door staff see a clear reason.
        t = c.execute(
            """SELECT t.id, t.event_id, t.status, t.used_at, t.holder_name, t.seq, ti.name AS tier_name
               FROM tickets t JOIN ticket_tiers ti ON ti.id = t.tier_id WHERE t.token = %s""", (token,)).fetchone()
        if not t:
            result, msg = "invalid", "No ticket with this code exists."
        elif t["event_id"] != event_id:
            result, msg = "wrong_event", "This ticket is for a different event."
        elif t["status"] == "used":
            result, msg = "already_used", "This ticket has already been used."
        else:
            result, msg = "void", "This ticket has been cancelled."
        c.execute("INSERT INTO scans (event_id, ticket_id, code_hint, result, scanned_by) VALUES (%s,%s,%s,%s,%s)",
                  (event_id, t["id"] if t and t["event_id"] == event_id else None, token[-9:], result, scanner_id))
        out = {"result": result, "message": msg}
        if t and t["event_id"] == event_id:
            out.update(holder=t["holder_name"], tier=t["tier_name"], seq=t["seq"])
            if t["used_at"]:
                out["at"] = t["used_at"].isoformat()
        return out
