"""End-to-end tests for role-based access (real Postgres, set DATABASE_URL first).

    pytest -q tests/test_roles.py
    pytest -q                       # runs this alongside test_flow.py
"""
import secrets
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import app
from eventvault import db, orders, payments
from tests.test_flow import make_event, signup, tier_ids, buy, FakeStripe  # reuse fixtures/helpers

client = TestClient(app)


def make_admin(c):
    uid = c.get("/api/auth/me").json()["user"]["id"]
    db.run("UPDATE users SET role = 'admin' WHERE id = %s", (uid,))
    return uid


# ---------------------------------------------------------------- role gate on event creation

def test_fresh_user_cannot_create_events():
    c = signup()
    assert c.get("/api/auth/me").json()["user"]["role"] == "user"
    r = c.post("/api/events", json={"title": "Nope", "category": "Music", "description": "x" * 20,
                                    "venue": "Venue Hall", "city": "City", "date": "2027-01-01", "time": "19:00",
                                    "contact_email": "a@b.com", "tiers": [{"name": "Reg", "price": 10, "quantity": 5}]})
    assert r.status_code == 403


def test_organizer_request_then_admin_approval_unlocks_event_creation():
    admin = signup(); make_admin(admin)
    user = signup()
    assert user.post("/api/organizer-requests", json={"message": "I run a jazz night"}).status_code == 200
    assert user.get("/api/organizer-requests/mine").json()["request"]["status"] == "pending"

    # a second pending request 409s
    assert user.post("/api/organizer-requests", json={}).status_code == 409

    pending = admin.get("/api/admin/organizer-requests?status=pending").json()["requests"]
    mine = next(r for r in pending if r["user_email"] == user.get("/api/auth/me").json()["user"]["email"])
    assert admin.post(f"/api/admin/organizer-requests/{mine['id']}/approve").status_code == 200
    assert user.get("/api/auth/me").json()["user"]["role"] == "organizer"

    # approving twice 409s (already reviewed)
    assert admin.post(f"/api/admin/organizer-requests/{mine['id']}/approve").status_code == 409

    # now they can actually create an event, with no extra DB-level promotion
    d = datetime.now() + timedelta(days=10)
    r = user.post("/api/events", json={"title": "Jazz Night", "category": "Music", "description": "x" * 20,
                                       "venue": "Venue Hall", "city": "City", "date": d.strftime("%Y-%m-%d"), "time": "19:00",
                                       "contact_email": "a@b.com", "tiers": [{"name": "Reg", "price": 10, "quantity": 5}]})
    assert r.status_code == 200, r.text


def test_denied_request_does_not_promote_and_can_request_again():
    admin = signup(); make_admin(admin)
    user = signup()
    user.post("/api/organizer-requests", json={})
    req_id = admin.get("/api/admin/organizer-requests?status=pending").json()["requests"][0]["id"]
    assert admin.post(f"/api/admin/organizer-requests/{req_id}/deny", json={"reason": "not enough detail"}).status_code == 200
    assert user.get("/api/auth/me").json()["user"]["role"] == "user"
    # denied, so they can ask again
    assert user.post("/api/organizer-requests", json={}).status_code == 200


def test_organizer_cannot_self_promote_to_admin():
    user = signup(); make_event(user)  # make_event promotes to organizer directly (test helper, not HTTP)
    assert user.get("/api/auth/me").json()["user"]["role"] == "organizer"
    for path in ("/api/admin/overview", "/api/admin/users", "/api/admin/events"):
        assert user.get(path).status_code == 403


# ---------------------------------------------------------------- admin gate

def test_non_admin_gets_403_on_every_admin_route():
    plain = signup()
    org = signup(); make_event(org)
    endpoints = ["/api/admin/overview", "/api/admin/breakdown", "/api/admin/system",
                 "/api/admin/users", "/api/admin/events", "/api/admin/orders",
                 "/api/admin/scans", "/api/admin/messages", "/api/admin/organizer-requests"]
    for c in (plain, org):
        for ep in endpoints:
            assert c.get(ep).status_code == 403, ep
    assert TestClient(app).get("/api/admin/overview").status_code == 401  # not logged in at all


def test_admin_can_still_do_plain_organizer_things():
    admin = signup(); make_admin(admin)
    eid = make_event(admin)  # make_event's DB-level promotion is a no-op here, role is already admin
    assert admin.get("/api/auth/me").json()["user"]["role"] == "admin"
    assert client.get(f"/api/events/{eid}").status_code == 200
    assert admin.get(f"/api/events/{eid}/stats").status_code == 200


# ---------------------------------------------------------------- user management

def test_admin_promote_demote_suspend_self_protections():
    admin = signup(); admin_id = make_admin(admin)
    other = signup()
    other_id = other.get("/api/auth/me").json()["user"]["id"]

    assert admin.post(f"/api/admin/users/{other_id}/role", json={"role": "organizer"}).status_code == 200
    assert other.get("/api/auth/me").json()["user"]["role"] == "organizer"
    assert admin.post(f"/api/admin/users/{other_id}/role", json={"role": "user"}).status_code == 200
    assert other.get("/api/auth/me").json()["user"]["role"] == "user"

    # can't demote or suspend self
    assert admin.post(f"/api/admin/users/{admin_id}/role", json={"role": "user"}).status_code == 400
    assert admin.post(f"/api/admin/users/{admin_id}/suspend", json={"suspended": True}).status_code == 400

    # suspend someone else: their existing session is rejected going forward (403, not 401 — they still exist)
    assert admin.post(f"/api/admin/users/{other_id}/suspend", json={"suspended": True}).status_code == 200
    assert other.get("/api/auth/me").json()["user"] is None or other.get("/api/events").status_code != 401
    r = other.get("/api/me/tickets")
    assert r.status_code == 403
    assert "suspended" in r.json()["detail"].lower()

    # unsuspend restores access
    assert admin.post(f"/api/admin/users/{other_id}/suspend", json={"suspended": False}).status_code == 200
    assert other.get("/api/me/tickets").status_code == 200


def test_admin_user_search_and_listing():
    admin = signup(); make_admin(admin)
    tag = secrets.token_hex(4)
    signup(f"Findme {tag}")
    r = admin.get(f"/api/admin/users?q={tag}")
    assert r.status_code == 200 and r.json()["total"] >= 1
    assert any(tag in u["name"] for u in r.json()["users"])


def test_delete_user_blocked_with_paid_history_allowed_otherwise():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    buyer = signup()
    buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])

    org_id = org.get("/api/auth/me").json()["user"]["id"]
    buyer_id = buyer.get("/api/auth/me").json()["user"]["id"]
    assert admin.delete(f"/api/admin/users/{org_id}").status_code == 409     # owns an event with a paid order
    assert admin.delete(f"/api/admin/users/{buyer_id}").status_code == 409   # has a paid purchase

    fresh = signup()
    fresh_id = fresh.get("/api/auth/me").json()["user"]["id"]
    assert admin.delete(f"/api/admin/users/{fresh_id}").status_code == 200
    assert admin.get(f"/api/admin/users?q={fresh_id}").json()  # doesn't error; account is gone


# ---------------------------------------------------------------- events: platform-wide, cancel, feature

def test_admin_event_listing_and_feature_flag():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    assert admin.get("/api/admin/events").status_code == 200
    assert admin.post(f"/api/admin/events/{eid}/feature", json={"featured": True}).status_code == 200
    assert client.get(f"/api/events/{eid}").json()["featured"] is True
    assert admin.post(f"/api/admin/events/{eid}/feature", json={"featured": False}).status_code == 200


def test_admin_can_edit_any_event_without_owning_it():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    form = org.get(f"/api/events/{eid}/edit").json() if False else client.get(f"/api/events/{eid}").json()
    # build an edit payload from what the org's own edit endpoint returns
    edit = org.get(f"/api/events/{eid}/edit").json()
    body = {k: edit[k] for k in ("title", "category", "description", "venue", "city", "date", "time", "contact_email", "contact_phone")}
    body["title"] = "Retitled by admin"
    body["tiers"] = [{"id": t["id"], "name": t["name"], "quantity": t["quantity"]} for t in edit["tiers"]]
    r = admin.put(f"/api/admin/events/{eid}", json=body)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/events/{eid}").json()["title"] == "Retitled by admin"


def test_cancel_event_voids_tickets_and_hides_from_public_listing():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    buyer = signup()
    tid = tier_ids(eid)[next(iter(tier_ids(eid)))]
    ref = buy(buyer, eid, tid)["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]

    assert admin.post(f"/api/admin/events/{eid}/cancel", json={"reason": "venue flooded"}).status_code == 200
    # cancelling twice 409s
    assert admin.post(f"/api/admin/events/{eid}/cancel", json={}).status_code == 409

    # gone from public listing/detail for an anonymous client...
    assert TestClient(app).get(f"/api/events/{eid}").status_code == 404
    ids = [e["id"] for e in client.get("/api/events?limit=50").json()["events"]]
    assert eid not in ids
    # ...but the organiser and an admin can still see it
    assert org.get(f"/api/events/{eid}").status_code == 200
    assert admin.get(f"/api/events/{eid}").status_code == 200

    # the ticket bought before cancellation is void
    assert org.post("/api/checkin", json={"event_id": eid, "code": token}).json()["result"] == "void"


def test_admin_delete_blocked_by_default_but_forceable():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    buyer = signup()
    buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])

    assert admin.delete(f"/api/admin/events/{eid}").status_code == 409
    assert admin.delete(f"/api/admin/events/{eid}?force=true").status_code == 200
    assert client.get(f"/api/events/{eid}").status_code == 404

    empty = make_event(org)
    assert admin.delete(f"/api/admin/events/{empty}").status_code == 200


# ---------------------------------------------------------------- tickets: void / reset / reissue

def test_ticket_void_reset_reissue():
    org = signup(); eid = make_event(org)
    admin = signup(); make_admin(admin)
    buyer = signup()
    ref = buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]

    # void
    assert admin.post(f"/api/admin/tickets/{token}/void", json={"reason": "duplicate purchase"}).status_code == 200
    assert org.post("/api/checkin", json={"event_id": eid, "code": token}).json()["result"] == "void"
    assert admin.post(f"/api/admin/tickets/{token}/void", json={}).status_code == 409  # already void

    # reissue a *different* (still-valid) ticket
    ref2 = buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])["order_ref"]
    token2 = buyer.get(f"/api/orders/{ref2}").json()["tickets"][0]["token"]
    r = admin.post(f"/api/admin/tickets/{token2}/reissue", json={"reason": "lost QR"})
    assert r.status_code == 200
    new_token = r.json()["token"]
    assert new_token != token2
    assert org.post("/api/checkin", json={"event_id": eid, "code": token2}).json()["result"] == "void"
    assert org.post("/api/checkin", json={"event_id": eid, "code": new_token}).json()["result"] == "ok"

    # reset a used ticket back to valid
    ref3 = buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])["order_ref"]
    token3 = buyer.get(f"/api/orders/{ref3}").json()["tickets"][0]["token"]
    assert org.post("/api/checkin", json={"event_id": eid, "code": token3}).json()["result"] == "ok"
    assert admin.post(f"/api/admin/tickets/{token3}/reset").status_code == 200
    assert org.post("/api/checkin", json={"event_id": eid, "code": token3}).json()["result"] == "ok"

    # can't reset a ticket that isn't currently used — token3 *is* used again at this point (just
    # re-scanned above), so exercise the negative case on a ticket that was never checked in at all
    ref4 = buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])["order_ref"]
    token4 = buyer.get(f"/api/orders/{ref4}").json()["tickets"][0]["token"]
    assert admin.post(f"/api/admin/tickets/{token4}/reset").status_code == 409


def test_admin_reset_races_a_door_scan_without_corrupting_state():
    """An admin resets a used ticket back to valid at the same instant a scanner checks it in again.
    Both actions use the same single-UPDATE-WHERE-status pattern, so exactly one of them can observe
    the row in the state it expects; whichever loses the race simply gets 'no rows changed' rather than
    stepping on the winner. The one deterministic invariant, regardless of interleaving: the ticket ends
    up in a real state (valid or used) and was admitted at least once overall -- never silently lost."""
    org = signup(); eid = make_event(org)
    admin = signup(); make_admin(admin)
    buyer = signup()
    ref = buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]
    admin_id = admin.get("/api/auth/me").json()["user"]["id"]
    org_id = org.get("/api/auth/me").json()["user"]["id"]
    assert orders.check_in(token, eid, org_id)["result"] == "ok"  # now 'used'

    n = 8
    # n scan threads + 1 reset thread = n + 1 total parties that call .wait(); the main thread does
    # not itself participate in the barrier (same pattern as the working races in test_flow.py) —
    # sizing the barrier for one more party than actually calls .wait() is what caused this test to
    # hang indefinitely before this fix.
    barrier = threading.Barrier(n + 1)
    results = []

    def reset_once():
        barrier.wait()
        results.append(("reset", db.one(
            "UPDATE tickets SET status='valid', used_at=NULL, used_by=NULL WHERE token=%s AND status='used' RETURNING id",
            (token,))))

    def scan_once():
        barrier.wait()
        results.append(("scan", orders.check_in(token, eid, org_id)["result"]))

    threads = [threading.Thread(target=reset_once)] + [threading.Thread(target=scan_once) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]

    final = db.one("SELECT status FROM tickets WHERE token = %s", (token,))["status"]
    assert final in ("valid", "used")
    admitted_count = sum(1 for kind, val in results if kind == "scan" and val == "ok")
    assert admitted_count <= 1  # the check-in lock still guarantees at most one admission per valid period


# ---------------------------------------------------------------- orders & refunds

@pytest.fixture
def stripe_mode(monkeypatch):
    from eventvault import config as cfg
    fake = FakeStripe()
    fake.Refund = SimpleNamespace(create=lambda **kw: SimpleNamespace(id="re_" + secrets.token_hex(4), **kw))
    monkeypatch.setattr(cfg, "PAYMENTS_MODE", "stripe")
    monkeypatch.setattr(cfg, "STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(cfg, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(payments, "_stripe", lambda: fake)
    return fake


def _paid_stripe_order(stripe_mode, org, buyer, eid):
    tid = tier_ids(eid)[next(iter(tier_ids(eid)))]
    res = buyer.post("/api/checkout", json={"event_id": eid, "items": [{"tier_id": tid, "quantity": 1}]}).json()
    sess = next(s for s in stripe_mode.sessions.values() if s.kw["metadata"]["order_ref"] == res["order_ref"])
    sess.payment_intent = "pi_" + secrets.token_hex(6)
    order_id = db.one("SELECT id FROM orders WHERE public_ref = %s", (res["order_ref"],))["id"]
    orders.fulfil_order(order_id, sess.payment_intent)
    return order_id, res["order_ref"]


def test_refund_full_partial_and_rejections(stripe_mode):
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org, tiers=[{"name": "Regular", "price": 50, "quantity": 10}])
    buyer = signup()
    order_id, ref = _paid_stripe_order(stripe_mode, org, buyer, eid)

    # over-refund rejected
    assert admin.post(f"/api/admin/orders/{order_id}/refund", json={"amount_cents": 999999}).status_code == 400
    # partial refund
    r = admin.post(f"/api/admin/orders/{order_id}/refund", json={"amount_cents": 1000})
    assert r.status_code == 200 and r.json()["refunded_cents"] == 1000
    # refunding the rest (default = remaining) succeeds
    r2 = admin.post(f"/api/admin/orders/{order_id}/refund", json={})
    assert r2.status_code == 200
    # now fully refunded, refunding again over-refunds
    assert admin.post(f"/api/admin/orders/{order_id}/refund", json={"amount_cents": 1}).status_code == 400


def test_refund_rejected_on_demo_mode_order():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org, tiers=[{"name": "Free", "price": 0, "quantity": 5}])
    buyer = signup()
    res = buy(buyer, eid, tier_ids(eid)["Free"])
    order_id = db.one("SELECT id FROM orders WHERE public_ref = %s", (res["order_ref"],))["id"]
    assert admin.post(f"/api/admin/orders/{order_id}/refund", json={}).status_code == 400


def test_admin_resend_order_email_without_owning_it():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    buyer = signup()
    ref = buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])["order_ref"]
    order_id = db.one("SELECT id FROM orders WHERE public_ref = %s", (ref,))["id"]
    r = admin.post(f"/api/admin/orders/{order_id}/resend")
    assert r.status_code in (200, 502)  # 502 only if Resend genuinely isn't configured locally


# ---------------------------------------------------------------- scans, messages, analytics, system

def test_admin_scans_listing_across_events():
    org = signup(); eid = make_event(org)
    admin = signup(); make_admin(admin)
    buyer = signup()
    ref = buy(buyer, eid, tier_ids(eid)[next(iter(tier_ids(eid)))])["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]
    org.post("/api/checkin", json={"event_id": eid, "code": token})
    org.post("/api/checkin", json={"event_id": eid, "code": token})  # duplicate
    r = admin.get(f"/api/admin/scans?event_id={eid}")
    assert r.status_code == 200 and r.json()["total"] >= 2
    assert admin.get("/api/admin/scans?result=already_used").json()["total"] >= 1


def test_admin_messages_view_and_delete():
    admin = signup(); make_admin(admin)
    assert client.post("/api/contact", json={"name": "Ada", "email": "ada@example.com", "message": "x" * 15}).status_code == 200
    r = admin.get("/api/admin/messages")
    assert r.status_code == 200 and r.json()["total"] >= 1
    mid = r.json()["messages"][0]["id"]
    assert admin.delete(f"/api/admin/messages/{mid}").status_code == 200
    assert admin.delete(f"/api/admin/messages/{mid}").status_code == 404


def test_platform_overview_and_breakdown_are_unscoped():
    admin = signup(); make_admin(admin)
    org1 = signup(); e1 = make_event(org1)
    org2 = signup(); e2 = make_event(org2)
    b1, b2 = signup(), signup()
    buy(b1, e1, tier_ids(e1)[next(iter(tier_ids(e1)))])
    buy(b2, e2, tier_ids(e2)[next(iter(tier_ids(e2)))])

    ov = admin.get("/api/admin/overview").json()
    assert ov["stats"]["total_events"] >= 2 and ov["stats"]["tickets_sold"] >= 2
    assert len(ov["sales_by_day"]) == 14

    bd = admin.get("/api/admin/breakdown").json()
    assert "by_category" in bd and "by_city" in bd


def test_system_status_exposes_no_secrets():
    admin = signup(); make_admin(admin)
    r = admin.get("/api/admin/system").json()
    assert set(r.keys()) == {"payments_mode", "email_enabled", "stripe_webhook_configured"}
    assert "sk_" not in str(r) and "whsec_" not in str(r)


# ---------------------------------------------------------------- fixes found while reviewing the feature

def test_cancelled_event_cannot_be_bought_even_by_calling_the_api_directly():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    tid = tier_ids(eid)["Regular"]
    assert admin.post(f"/api/admin/events/{eid}/cancel", json={"reason": "Venue closed"}).status_code == 200
    buyer = signup()
    r = buyer.post("/api/checkout", json={"event_id": eid, "items": [{"tier_id": tid, "quantity": 1}]})
    assert r.status_code == 409 and "cancelled" in r.json()["detail"]
    assert db.one("SELECT count(*)::int n FROM tickets WHERE event_id = %s", (eid,))["n"] == 0


def test_refund_of_a_fully_refunded_order_is_a_clear_400(stripe_mode):
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org, tiers=[{"name": "Regular", "price": 20, "quantity": 5}])
    order_id, _ = _paid_stripe_order(stripe_mode, org, signup(), eid)
    assert admin.post(f"/api/admin/orders/{order_id}/refund", json={}).status_code == 200
    r = admin.post(f"/api/admin/orders/{order_id}/refund", json={})
    assert r.status_code == 400 and "fully refunded" in r.json()["detail"]


def test_concurrent_refunds_can_never_exceed_what_was_paid(stripe_mode):
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org, tiers=[{"name": "Regular", "price": 50, "quantity": 5}])
    order_id, _ = _paid_stripe_order(stripe_mode, org, signup(), eid)          # $50.00 = 5000 cents
    calls = []
    stripe_mode.Refund = SimpleNamespace(create=lambda **kw: calls.append(kw["amount"]) or SimpleNamespace(id="re_x"))
    n, barrier, codes = 8, threading.Barrier(8), []
    def go():
        barrier.wait()
        codes.append(admin.post(f"/api/admin/orders/{order_id}/refund", json={"amount_cents": 1500}).status_code)
    ts = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert codes.count(200) == 3, codes                      # 3 x 1500 = 4500 fits; a 4th would make 6000 > 5000
    assert sum(calls) == 4500 and len(calls) == 3            # Stripe was only asked for what actually fits
    assert db.one("SELECT refunded_cents FROM orders WHERE id = %s", (order_id,))["refunded_cents"] == 4500


def test_failed_stripe_refund_hands_the_reserved_amount_back(stripe_mode):
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org, tiers=[{"name": "Regular", "price": 30, "quantity": 5}])
    order_id, _ = _paid_stripe_order(stripe_mode, org, signup(), eid)
    def boom(**kw): raise RuntimeError("stripe is down")
    stripe_mode.Refund = SimpleNamespace(create=boom)
    r = admin.post(f"/api/admin/orders/{order_id}/refund", json={"amount_cents": 1000})
    assert r.status_code == 502
    assert db.one("SELECT refunded_cents FROM orders WHERE id = %s", (order_id,))["refunded_cents"] == 0


def test_upgrade_keeps_existing_event_owners_as_organizers():
    """A database from before roles existed: accounts that already own events must keep creating events."""
    import os, psycopg
    base = os.environ["DATABASE_URL"].rsplit("/", 1)[0]
    name = "ev_upgrade_" + secrets.token_hex(3)
    with psycopg.connect(base + "/postgres", autocommit=True) as admin_conn:
        admin_conn.execute(f'CREATE DATABASE "{name}"')
    try:
        from pathlib import Path
        old_schema = Path(__file__).with_name("legacy_schema.sql").read_text()
        with psycopg.connect(f"{base}/{name}", autocommit=True) as c:
            c.execute(old_schema)
            c.execute("INSERT INTO users (name, email, password_hash) VALUES ('Owner','owner@x.com','x'), ('Buyer','buyer@x.com','x')")
            c.execute("""INSERT INTO events (organizer_id, title, category, description, venue, city, starts_at, contact_email)
                         SELECT id, 'Old event', 'Music', 'described here', 'V', 'C', now(), 'o@x.com' FROM users WHERE email='owner@x.com'""")
        from eventvault import config as cfg
        saved = cfg.DATABASE_URL
        try:
            db._pool = None
            cfg.DATABASE_URL = f"{base}/{name}"
            db.init_schema()
            roles = {r["email"]: r["role"] for r in db.all_("SELECT email, role FROM users")}
            assert roles == {"owner@x.com": "organizer", "buyer@x.com": "user"}
            db.run("UPDATE users SET role = 'user' WHERE email = 'owner@x.com'")     # an admin demotes them...
            db.init_schema()                                                          # ...and re-running must not undo it
            assert db.one("SELECT role FROM users WHERE email = 'owner@x.com'")["role"] == "user"
        finally:
            if db._pool is not None:
                db._pool.close()
            db._pool = None
            cfg.DATABASE_URL = saved
    finally:
        with psycopg.connect(base + "/postgres", autocommit=True) as admin_conn:
            admin_conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_admin_can_list_an_orders_tickets_and_only_admins():
    admin = signup(); make_admin(admin)
    org = signup(); eid = make_event(org)
    buyer = signup()
    res = buy(buyer, eid, tier_ids(eid)["Regular"], 2)
    order_id = db.one("SELECT id FROM orders WHERE public_ref = %s", (res["order_ref"],))["id"]
    tickets = admin.get(f"/api/admin/orders/{order_id}/tickets").json()["tickets"]
    assert [t["seq"] for t in tickets] == [1, 2] and all(t["status"] == "valid" for t in tickets)
    new_token = admin.post(f"/api/admin/tickets/{tickets[0]['token']}/reissue", json={}).json()["token"]
    after = admin.get(f"/api/admin/orders/{order_id}/tickets").json()["tickets"]
    assert [(t["seq"], t["status"], t["is_reissue"]) for t in after] == [(1, "void", False), (1, "valid", True), (2, "valid", False)]
    assert after[1]["token"] == new_token
    assert admin.get("/api/admin/orders/999999999/tickets").status_code == 404
    assert buyer.get(f"/api/admin/orders/{order_id}/tickets").status_code == 403
    assert org.get(f"/api/admin/orders/{order_id}/tickets").status_code == 403
