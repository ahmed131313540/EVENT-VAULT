"""End-to-end tests against a real Postgres (set DATABASE_URL first).

    pip install pytest httpx
    pytest -q
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret")
from app import app                                     # noqa: E402
from eventvault import config, db, orders, payments     # noqa: E402

client = TestClient(app)


def signup(name="Test Person"):
    c = TestClient(app)
    email = f"t{secrets.token_hex(5)}@example.com"
    r = c.post("/api/auth/register", json={"name": name, "email": email, "password": "correct horse battery"})
    assert r.status_code == 200, r.text
    return c


def make_organizer(c):
    """Promote the account behind TestClient c to role organizer, bypassing the request/approve
    HTTP flow — direct-to-DB, the way the RBAC spec calls for in tests. Only touches a plain 'user' —
    never downgrades an account a test has already made 'admin' (make_event() calls this
    unconditionally, so an admin calling make_event() must stay admin)."""
    uid = c.get("/api/auth/me").json()["user"]["id"]
    db.run("UPDATE users SET role = 'organizer' WHERE id = %s AND role = 'user'", (uid,))


def make_event(c, tiers=None, days=10):
    make_organizer(c)
    d = datetime.now() + timedelta(days=days)
    body = {"title": "Test Gala " + secrets.token_hex(3), "category": "Music", "description": "A long enough description for the test event.",
            "venue": "Test Hall", "city": "Testville", "date": d.strftime("%Y-%m-%d"), "time": "19:30",
            "contact_email": "host@example.com",
            "tiers": tiers or [{"name": "Early Bird", "price": 20, "quantity": 5}, {"name": "Regular", "price": 30, "quantity": 50},
                               {"name": "VIP", "price": 90, "quantity": 5}]}
    r = c.post("/api/events", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def tier_ids(event_id):
    return {t["name"]: t["id"] for t in client.get(f"/api/events/{event_id}").json()["tiers"]}


def buy(c, event_id, tier_id, qty=1):
    r = c.post("/api/checkout", json={"event_id": event_id, "items": [{"tier_id": tier_id, "quantity": qty}]})
    assert r.status_code == 200, r.text
    return r.json()


def test_auth_and_permissions():
    c = signup()
    assert c.get("/api/auth/me").json()["user"]["name"] == "Test Person"
    assert TestClient(app).get("/api/me/tickets").status_code == 401
    assert TestClient(app).post("/api/events", json={}).status_code in (401, 422)
    bad = TestClient(app).post("/api/auth/login", json={"email": "nobody@example.com", "password": "whatever123"})
    assert bad.status_code == 401


def test_tiers_and_separate_price_records():
    org = signup()
    eid = make_event(org)
    detail = client.get(f"/api/events/{eid}").json()
    assert [t["name"] for t in detail["tiers"]] == ["Early Bird", "Regular", "VIP"]
    assert [t["price_cents"] for t in detail["tiers"]] == [2000, 3000, 9000]


def test_purchase_issues_unique_qr_pdf_tickets():
    org, buyer = signup("Host"), signup("Buyer One")
    eid = make_event(org)
    res = buy(buyer, eid, tier_ids(eid)["VIP"], 3)
    assert res["mode"] == "demo"
    order = buyer.get(f"/api/orders/{res['order_ref']}").json()
    assert order["status"] == "paid" and len(order["tickets"]) == 3
    tokens = [t["token"] for t in order["tickets"]]
    assert len(set(tokens)) == 3 and all(re.fullmatch(r"EV-[A-Z0-9]{4}(-[A-Z0-9]{4}){3}", t) for t in tokens)
    pdf = buyer.get(f"/api/tickets/{tokens[0]}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert TestClient(app).get(f"/api/tickets/{tokens[0]}/pdf").status_code == 401        # not logged in
    assert signup().get(f"/api/tickets/{tokens[0]}/pdf").status_code == 404                # someone else's ticket


def test_checkin_admits_once_then_blocks_reentry():
    org, buyer = signup("Host"), signup("Buyer")
    eid = make_event(org)
    token = buy(buyer, eid, tier_ids(eid)["Regular"])["order_ref"]
    token = buyer.get(f"/api/orders/{token}").json()["tickets"][0]["token"]
    first = org.post("/api/checkin", json={"event_id": eid, "code": token}).json()
    assert first["result"] == "ok" and first["holder"] == "Buyer"
    again = org.post("/api/checkin", json={"event_id": eid, "code": token}).json()
    assert again["result"] == "already_used" and again["at"]
    # typing the code in lower case without dashes is accepted, and is still a duplicate
    typed = org.post("/api/checkin", json={"event_id": eid, "code": token.replace("-", "").lower()}).json()
    assert typed["result"] == "already_used"
    assert org.post("/api/checkin", json={"event_id": eid, "code": "EV-AAAA-BBBB-CCCC-DDDD"}).json()["result"] == "invalid"
    assert org.post("/api/checkin", json={"event_id": eid, "code": "hello"}).json()["result"] == "invalid"
    assert buyer.post("/api/checkin", json={"event_id": eid, "code": token}).status_code == 403   # only the organiser can scan


def test_ticket_for_another_event_is_rejected():
    org, buyer = signup(), signup()
    e1, e2 = make_event(org), make_event(org)
    ref = buy(buyer, e1, tier_ids(e1)["Regular"])["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]
    assert org.post("/api/checkin", json={"event_id": e2, "code": token}).json()["result"] == "wrong_event"
    assert org.post("/api/checkin", json={"event_id": e1, "code": token}).json()["result"] == "ok"   # the block didn't burn it


def test_two_devices_scanning_the_same_ticket_only_one_succeeds():
    org, buyer = signup(), signup()
    eid = make_event(org)
    ref = buy(buyer, eid, tier_ids(eid)["Regular"])["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]
    uid = db.one("SELECT id FROM users WHERE email = %s", (org.get("/api/auth/me").json()["user"]["email"],))["id"]

    for round_ in range(3):                                   # repeat: races are probabilistic
        if round_:
            db.run("UPDATE tickets SET status = 'valid', used_at = NULL WHERE token = %s", (token,))
        n = 16
        barrier, results = threading.Barrier(n), []
        def scan():
            barrier.wait()
            results.append(orders.check_in(token, eid, uid)["result"])
        threads = [threading.Thread(target=scan) for _ in range(n)]
        [t.start() for t in threads]; [t.join() for t in threads]
        assert results.count("ok") == 1, results
        assert results.count("already_used") == n - 1, results


def test_two_devices_over_http_only_one_succeeds():
    org, buyer = signup(), signup()
    eid = make_event(org)
    ref = buy(buyer, eid, tier_ids(eid)["Regular"])["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]
    n, barrier, results = 12, threading.Barrier(12), []
    def scan():
        barrier.wait()
        results.append(org.post("/api/checkin", json={"event_id": eid, "code": token}).json()["result"])
    threads = [threading.Thread(target=scan) for _ in range(n)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sorted(results) == ["already_used"] * (n - 1) + ["ok"]


def test_last_seats_cannot_be_oversold():
    org = signup()
    eid = make_event(org, tiers=[{"name": "Regular", "price": 10, "quantity": 3}])
    tid = tier_ids(eid)["Regular"]
    buyers = [signup() for _ in range(8)]
    barrier, out = threading.Barrier(8), []
    def go(b):
        barrier.wait()
        r = b.post("/api/checkout", json={"event_id": eid, "items": [{"tier_id": tid, "quantity": 1}]})
        out.append(r.status_code)
    threads = [threading.Thread(target=go, args=(b,)) for b in buyers]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert out.count(200) == 3 and out.count(409) == 5, out
    assert client.get(f"/api/events/{eid}").json()["sold_out"] is True
    assert db.one("SELECT count(*)::int n FROM tickets WHERE event_id = %s", (eid,))["n"] == 3


def test_free_tier_needs_no_payment():
    org, buyer = signup(), signup()
    eid = make_event(org, tiers=[{"name": "Free entry", "price": 0, "quantity": 10}])
    assert buy(buyer, eid, tier_ids(eid)["Free entry"])["mode"] == "free"


def test_cannot_delete_event_with_buyers_but_can_edit_capacity_up():
    org, buyer = signup(), signup()
    eid = make_event(org)
    buy(buyer, eid, tier_ids(eid)["Regular"], 2)
    assert org.delete(f"/api/events/{eid}").status_code == 409
    form = org.get(f"/api/events/{eid}/edit").json()
    tiers = [{"id": t["id"], "name": t["name"], "quantity": t["quantity"] + 5} for t in form["tiers"]]
    body = {k: form[k] for k in ("title", "category", "description", "venue", "city", "date", "time", "contact_email", "contact_phone")}
    assert org.put(f"/api/events/{eid}", json={**body, "tiers": tiers}).status_code == 200
    low = [{"id": t["id"], "name": t["name"], "quantity": 1} for t in form["tiers"]]
    assert org.put(f"/api/events/{eid}", json={**body, "tiers": low}).status_code == 409
    empty = make_event(org)
    assert org.delete(f"/api/events/{empty}").status_code == 200
    assert client.get(f"/api/events/{empty}").status_code == 404


def test_stats_endpoint():
    org, buyer = signup(), signup()
    eid = make_event(org)
    ref = buy(buyer, eid, tier_ids(eid)["VIP"], 2)["order_ref"]
    token = buyer.get(f"/api/orders/{ref}").json()["tickets"][0]["token"]
    org.post("/api/checkin", json={"event_id": eid, "code": token}); org.post("/api/checkin", json={"event_id": eid, "code": token})
    s = org.get(f"/api/events/{eid}/stats").json()
    assert s["totals"]["sold"] == 2 and s["totals"]["revenue_cents"] == 18000 and s["totals"]["checked_in"] == 1
    assert s["blocked_duplicates"] == 1 and len(s["sales_by_day"]) == 14
    assert buyer.get(f"/api/events/{eid}/stats").status_code == 403


# ---------------------------------------------------------------- Stripe (with a fake Stripe client)

class FakeStripe:
    def __init__(self):
        import stripe
        self.Webhook = stripe.Webhook           # real signature verification from the official library
        self.prices, self.sessions = [], {}
        self.Product = SimpleNamespace(create=lambda **kw: SimpleNamespace(id="prod_" + secrets.token_hex(4)))
        def price_create(**kw):
            p = SimpleNamespace(id="price_" + secrets.token_hex(4)); self.prices.append((p.id, kw)); return p
        self.Price = SimpleNamespace(create=price_create)
        def session_create(**kw):
            s = SimpleNamespace(id="cs_test_" + secrets.token_hex(6), url="https://checkout.stripe.test/pay", payment_status="unpaid", kw=kw)
            self.sessions[s.id] = s; return s
        self.checkout = SimpleNamespace(Session=SimpleNamespace(create=session_create, retrieve=lambda sid: self.sessions[sid]))


@pytest.fixture
def stripe_mode(monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(config, "PAYMENTS_MODE", "stripe")
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_fake")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(payments, "_stripe", lambda: fake)
    return fake


def signed(payload: dict):
    body = json.dumps(payload).encode()
    t = int(time.time())
    sig = hmac.new(b"whsec_test", f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def test_stripe_each_tier_gets_its_own_price_and_webhook_issues_tickets(stripe_mode):
    org, buyer = signup(), signup("Stripe Buyer")
    eid = make_event(org)
    rows = db.all_("SELECT name, stripe_price_id FROM ticket_tiers WHERE event_id = %s ORDER BY sort_order", (eid,))
    ids = [r["stripe_price_id"] for r in rows]
    assert all(i and i.startswith("price_") for i in ids) and len(set(ids)) == 3          # separate Price IDs

    tid = tier_ids(eid)["VIP"]
    res = buy(buyer, eid, tid, 2)
    assert res["mode"] == "stripe" and res["url"].startswith("https://checkout.stripe.test")
    sess = next(iter(stripe_mode.sessions.values()))
    assert sess.kw["line_items"] == [{"price": rows[2]["stripe_price_id"], "quantity": 2}]
    assert buyer.get(f"/api/orders/{res['order_ref']}").json()["status"] == "pending"

    # seats are held while payment is pending
    assert client.get(f"/api/events/{eid}").json()["tiers"][2]["available"] == 3

    # webhook with a bad signature is refused
    body, headers = signed({"type": "checkout.session.completed", "data": {"object": {"metadata": {"order_id": "1"}, "payment_status": "paid"}}})
    assert client.post("/api/webhooks/stripe", content=body, headers={**headers, "Stripe-Signature": "t=1,v1=bad"}).status_code == 400

    order_id = db.one("SELECT id FROM orders WHERE public_ref = %s", (res["order_ref"],))["id"]
    body, headers = signed({"type": "checkout.session.completed",
                            "data": {"object": {"id": sess.id, "payment_status": "paid", "metadata": {"order_id": str(order_id)}}}})
    for _ in range(2):                                    # Stripe retries deliveries: must be idempotent
        assert client.post("/api/webhooks/stripe", content=body, headers=headers).status_code == 200
    o = buyer.get(f"/api/orders/{res['order_ref']}").json()
    assert o["status"] == "paid" and len(o["tickets"]) == 2
    assert db.one("SELECT sold FROM ticket_tiers WHERE id = %s", (tid,))["sold"] == 2


def test_stripe_success_page_verifies_payment_even_without_webhook(stripe_mode):
    org, buyer = signup(), signup()
    eid = make_event(org)
    res = buy(buyer, eid, tier_ids(eid)["Regular"])
    next(iter(stripe_mode.sessions.values())).payment_status = "paid"
    o = buyer.get(f"/api/orders/{res['order_ref']}").json()
    assert o["status"] == "paid" and len(o["tickets"]) == 1


def test_expired_checkout_releases_seats(stripe_mode):
    org, buyer = signup(), signup()
    eid = make_event(org, tiers=[{"name": "Regular", "price": 10, "quantity": 2}])
    tid = tier_ids(eid)["Regular"]
    buy(buyer, eid, tid, 2)
    assert client.get(f"/api/events/{eid}").json()["sold_out"] is True
    db.run("UPDATE orders SET expires_at = now() - interval '1 minute' WHERE event_id = %s", (eid,))
    assert client.get(f"/api/events/{eid}").json()["tiers"][0]["available"] == 2
