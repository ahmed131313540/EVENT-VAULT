"""Create the tables and (once) fill them with demo events.

    python seed.py            # create tables if missing; add demo events only if there are no events yet
    python seed.py --reset    # DROP everything and start again (deletes real data!)

Set ADMIN_EMAIL and ADMIN_PASSWORD (env vars) to also create or promote a real, loggable-in admin
account -- this is the only way to get your first admin, since every other account starts as role
'user' and only an existing admin can promote anyone else.
"""
import os
import sys
from datetime import datetime, timedelta

from eventvault import db, security

ORGANISERS = ["Aurora Collective", "Northlight Live", "Harbor & Vine", "Summit Works", "Velvet Hour Events", "Open Table Studio"]

# title, category, city, venue, organiser index, days from now, hour, featured, description, tiers [(name, price USD, qty, already_sold)]
EVENTS = [
    ("Neon Nights Festival", "Festivals", "Berlin", "Arena Spree", 0, 34, 16, True,
     "Two days, three stages and a skyline of light. Neon Nights brings electronic, indie and live-band acts together on the river, with late-night food halls, art installations and a silent-disco tent that runs until sunrise.\n\nGates open at 4 PM. Early Bird is limited, and VIP includes fast-lane entry, a lounge with river views and a complimentary drink on arrival.",
     [("Early Bird", 45, 400, 372), ("Regular", 69, 1200, 610), ("VIP", 149, 150, 88)]),
    ("Symphony Under the Stars", "Music", "Lisbon", "Jardim da Estrela", 1, 12, 20, True,
     "A full orchestra plays film scores and classics in a candle-lit garden. Bring a blanket, arrive early for the picnic hour, and stay for the finale as the lights go down.\n\nSeated VIP tickets sit closest to the stage and include a welcome glass of wine.",
     [("Early Bird", 28, 200, 200), ("Regular", 39, 500, 341), ("VIP", 95, 60, 41)]),
    ("TechSummit 2026", "Technology", "Singapore", "Marina Convention Centre", 3, 58, 9, True,
     "Two days on AI, cloud and the future of software. Forty speakers from product teams, research labs and start-ups, hands-on labs in the afternoon, and a demo floor with more than sixty exhibitors.\n\nVIP passes include the speaker dinner and recordings of every session.",
     [("Early Bird", 120, 300, 244), ("Regular", 189, 900, 402), ("VIP", 420, 100, 37)]),
    ("Grand Vows Wedding Showcase", "Weddings", "Dubai", "Palm Terrace Hall", 4, 26, 11, False,
     "Meet the planners, florists, photographers and caterers behind the year's best celebrations. Walk through styled ceremony and reception rooms, taste menus and book on the day for exclusive show pricing.",
     [("Regular", 15, 600, 190), ("VIP", 55, 80, 22)]),
    ("Founders & Funders Conference", "Conferences", "London", "The Foundry Rooms", 3, 41, 9, False,
     "A one-day meeting point for early-stage founders and the investors who back them. Pitch clinics in the morning, curated one-to-one meetings after lunch, and an evening reception.",
     [("Early Bird", 79, 150, 118), ("Regular", 129, 350, 140), ("VIP", 299, 40, 12)]),
    ("Rooftop Sunset Party", "Parties", "New York", "Skyline Terrace", 4, 9, 18, False,
     "House, disco and golden-hour views over the river. Two floors, three bars and a DJ line-up that builds from sunset sets to a midnight close.",
     [("Early Bird", 25, 120, 120), ("Regular", 40, 300, 176), ("VIP", 90, 40, 33)]),
    ("Championship Night: Finals", "Sports", "Toronto", "Lakeshore Arena", 1, 21, 19, False,
     "The final game of the season, live. Family-friendly seating, big-screen replays and a fan zone open two hours before tip-off.",
     [("Regular", 35, 3000, 1830), ("VIP", 160, 200, 141)]),
    ("Watercolour for Beginners", "Workshops", "Istanbul", "Atölye Studio, Karaköy", 5, 16, 14, False,
     "Three relaxed hours learning washes, layering and simple landscapes. All materials are provided and no experience is needed. This session is free, and places are limited to keep groups small.",
     [("Free entry", 0, 24, 15)]),
    ("Sunset Sessions: Jazz & Wine", "Music", "Paris", "Cave Saint-Germain", 2, 19, 20, False,
     "An intimate evening with a quartet, natural wines by the glass and a menu of small plates. Seating is limited to 90 guests.",
     [("Regular", 32, 90, 54), ("VIP", 68, 20, 9)]),
    ("AI Builders Weekend", "Technology", "San Francisco", "Mission Bay Commons", 3, 47, 10, False,
     "Form a team, build something real in 36 hours and demo it to a panel of engineers and founders. Mentors, meals and cloud credits are included.",
     [("Early Bird", 20, 100, 100), ("Regular", 35, 300, 128)]),
    ("Midsummer Garden Wedding Fair", "Weddings", "Amsterdam", "Botanical Gardens Pavilion", 2, 63, 12, False,
     "Outdoor styling, floral design and a runway of dresses and suits in a glasshouse setting. Includes a tasting menu from three local caterers.",
     [("Regular", 18, 400, 96), ("VIP", 60, 60, 11)]),
    ("Independent Film Festival", "Festivals", "Toronto", "Cinema Row, Downtown", 5, 75, 13, False,
     "Ten days of features, shorts and documentaries from first-time directors, each followed by a conversation with the filmmakers.",
     [("Early Bird", 30, 250, 61), ("Regular", 48, 700, 152), ("VIP", 110, 80, 18)]),
]


def main():
    reset = "--reset" in sys.argv
    if reset and input("This deletes ALL EventVault data. Type 'yes' to continue: ").strip().lower() != "yes":
        sys.exit("Cancelled.")
    db.init_schema(reset=reset)
    print("Tables ready.")
    # Keep the demo organiser accounts' role current even on a re-run that skips reseeding events.
    db.run("UPDATE users SET role = 'organizer' WHERE email LIKE '%@demo.eventvault.invalid' AND role = 'user'")
    if db.one("SELECT 1 FROM events LIMIT 1"):
        print("Events already exist, so no demo events were added.")
        return
    org_ids = []
    for i, name in enumerate(ORGANISERS):
        row = db.one("""INSERT INTO users (name, email, password_hash, role) VALUES (%s,%s,'!','organizer')
                        ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, role = 'organizer' RETURNING id""",
                     (name, f"organiser{i + 1}@demo.eventvault.invalid"))
        org_ids.append(row["id"])
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    for title, cat, city, venue, org, days, hour, featured, desc, tiers in EVENTS:
        starts = (now + timedelta(days=days)).replace(hour=hour)
        with db.conn() as c:
            ev = c.execute(
                """INSERT INTO events (organizer_id, title, category, description, venue, city, starts_at, contact_email, featured)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (org_ids[org], title, cat, desc, venue, city, starts, f"hello@demo.eventvault.invalid", featured)).fetchone()
            for i, (tname, price, qty, sold) in enumerate(tiers):
                c.execute("INSERT INTO ticket_tiers (event_id, name, price_cents, quantity, sold, sort_order) VALUES (%s,%s,%s,%s,%s,%s)",
                          (ev["id"], tname, price * 100, qty, sold, i))
    print(f"Added {len(EVENTS)} demo events. Demo organisers can't log in; create your own account to host events.")


def ensure_admin():
    """Create or promote the account named by ADMIN_EMAIL/ADMIN_PASSWORD to role admin. Safe to call
    every run: if the account already exists, only its role changes (password is left alone so this
    doesn't clobber a password you've since changed by logging in and using the account normally)."""
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not email:
        return
    if not password and not db.one("SELECT 1 FROM users WHERE email = %s", (email,)):
        sys.exit("ADMIN_PASSWORD is required the first time you create ADMIN_EMAIL.")
    existing = db.one("SELECT id, role FROM users WHERE email = %s", (email,))
    if existing:
        db.run("UPDATE users SET role = 'admin' WHERE id = %s", (existing["id"],))
        print(f"{email} is now an admin.")
    else:
        db.run("INSERT INTO users (name, email, password_hash, role) VALUES (%s,%s,%s,'admin')",
               ("Admin", email, security.hash_password(password)))
        print(f"Created admin account {email}.")


if __name__ == "__main__":
    main()
    ensure_admin()
