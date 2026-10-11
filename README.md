# Event Vault

A ticketed event platform: tiered pricing (Early Bird / Regular / VIP), unique QR-coded PDF tickets emailed automatically, and a camera-based check-in scanner that blocks duplicate and simultaneous re-entry.

**Stack:** PostgreSQL · FastAPI · Stripe Checkout · Resend (email) · vanilla JS + Leaflet-free hand-rolled router · deployed on Vercel

```
public/index.html              the app shell (navbar, footer, SVG icon sprite)
public/assets/css/style.css    the dark-luxury theme
public/assets/js/core.js       router, API client, toasts, modal, search
public/assets/js/pages-*.js    every page (home, events, dashboard, scanner, ...)
app.py                         API entrypoint — Vercel runs this as a function
eventvault/                    Python backend: db, security, payments, tickets, orders, routes
seed.py                        creates tables + demo events
tests/test_flow.py             end-to-end tests, including the race condition
vercel.json  .python-version  requirements.txt     deployment config
```

## 1. Run it locally (VS Code terminal)

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1          # Windows PowerShell   (Mac/Linux: source .venv/bin/activate)
pip install -r requirements.txt
docker compose up -d                # local Postgres (Docker Desktop must be running)
python seed.py                      # tables + 12 demo events
uvicorn app:app --reload            # open http://localhost:8000
```
No `.env` needed for local demo mode: without `STRIPE_SECRET_KEY`, checkout completes instantly with no charge ("demo" mode) so you can test the full flow with zero setup. Without `RESEND_API_KEY`, tickets aren't emailed, but the order page still shows every QR ticket with a **Download PDF** button and a **Resend email** button that becomes usable once you add a key.

API docs: http://localhost:8000/api/docs. Tests: `pip install pytest httpx && pytest -q` (uses your local `DATABASE_URL`).

## 2. Put it on GitHub

```bash
git init
git add .
git commit -m "Event Vault: tiered ticketing with QR check-in"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/eventvault.git
git push -u origin main
```
`.gitignore` already keeps `.env` and `.venv` out of the repo.

## 3. Create the hosted database (Neon)

1. neon.tech → **Create project**.
2. **Connect** → copy the string with **Connection pooling ON** (host contains `-pooler`) for Vercel, and one with pooling **off** for seeding.
3. Seed it once from your machine:
```powershell
$env:DATABASE_URL="postgresql://USER:PASSWORD@HOST/neondb?sslmode=require"   # the non-pooled string
python seed.py
```

## 4. Stripe (optional, but needed for real payments)

Without this, every checkout runs in **demo mode**: no card is charged, the order completes immediately, and tickets are issued right away. This is fine for testing or demoing — add Stripe when you're ready to take real payments.

1. dashboard.stripe.com → **Developers → API keys** → copy the **Secret key** (`sk_test_...` while testing).
2. Set it as `STRIPE_SECRET_KEY` (Vercel env var, step 6). The app creates a Stripe **Product** per event and a separate **Price** per ticket tier automatically the first time each event is saved or booked — you don't need to create these in the Stripe dashboard yourself.
3. **Webhooks** (so a ticket is issued even if the buyer closes the tab before returning): **Developers → Webhooks → Add endpoint** → URL `https://YOUR-SITE.vercel.app/api/webhooks/stripe` → events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.expired`. Copy the **Signing secret** (`whsec_...`) into `STRIPE_WEBHOOK_SECRET`.
   Even without a webhook configured, the order confirmation page verifies payment directly with Stripe when the buyer lands on it, so tickets still get issued — the webhook just makes it reliable if they never come back.

## 5. Resend (optional, for emailed tickets)

1. resend.com → sign up → **API Keys → Create API Key**.
2. Set it as `RESEND_API_KEY`. The default `EMAIL_FROM` (`onboarding@resend.dev`) works immediately with no domain setup, for testing. To send from your own address, verify a domain in Resend and set `EMAIL_FROM` to `Event Vault <tickets@yourdomain.com>`.

## 6. Deploy on Vercel

1. vercel.com → **Add New… → Project** → import your `eventvault` GitHub repo.
2. Vercel detects FastAPI automatically; leave build settings as they are.
3. **Environment Variables**:

| Name | Required | Value |
|---|---|---|
| `DATABASE_URL` | yes | Neon **pooled** connection string |
| `SECRET_KEY` | yes | any long random string (used to sign login sessions) |
| `STRIPE_SECRET_KEY` | optional | from step 4 |
| `STRIPE_WEBHOOK_SECRET` | optional | from step 4 |
| `RESEND_API_KEY` | optional | from step 5 |
| `EMAIL_FROM` | optional | defaults to a Resend testing address |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | only when running `seed.py` | creates or promotes your first admin (not needed on Vercel itself) |

4. **Deploy**. Then run `seed.py` against the same `DATABASE_URL` once (step 3) if you haven't already — Vercel doesn't run it for you.
5. Every `git push` to `main` redeploys automatically.

## Roles and the admin panel

Every account has one of three roles:

| Role | Can do |
|---|---|
| `user` (default) | Browse, buy tickets, download tickets. Can **request** organizer access. Cannot create events. |
| `organizer` | Everything a user can, plus create/edit/delete **their own** events, see their own stats and scan tickets at their own events. |
| `admin` | Everything an organizer can, plus the **Admin** section (`/#/admin`): users, all events, orders and refunds, ticket void/reissue/reset, scan logs, organizer requests, contact messages, platform analytics and a system status page. |

**Getting your first admin.** New accounts are never admins. Set these two variables once, run the seed script, then remove them:

```powershell
$env:ADMIN_EMAIL="you@example.com"
$env:ADMIN_PASSWORD="a long password"
python seed.py
```
(Mac/Linux: `ADMIN_EMAIL=... ADMIN_PASSWORD=... python seed.py`.) Run it against the same `DATABASE_URL` your site uses. If the email already exists, that account is simply promoted. Then log in and open **Admin** from the avatar menu.

**Becoming an organizer.** A user opens **Create Event**, writes a line about what they'll host and presses *Request Organizer Access*. The request appears under **Admin → Requests**; approving it makes them an organizer. Admins can also change any user's role directly under **Admin → Users**.

**Upgrading an existing database.** Run `python seed.py` once against it. It adds the new columns and keeps everyone who already owns an event as an organizer, so nobody loses access.

**Refunds** need Stripe configured and only work for orders paid after this update (older orders don't store the payment reference Stripe needs; the admin panel tells you so and you can refund those in the Stripe dashboard). Cancelling an event voids its tickets but does not refund anyone automatically. Refund each order explicitly.

## Troubleshooting

- **"Can't reach the database"**: `DATABASE_URL` is wrong or missing in Vercel → fix it under Settings → Environment Variables, then **Deployments → ⋯ → Redeploy**.
- **"The database tables don't exist yet"**: run `python seed.py` against the same `DATABASE_URL` Vercel is using.
- **Checkout always completes instantly with no Stripe page**: that's demo mode, meaning `STRIPE_SECRET_KEY` isn't set. Add it and redeploy to take real payments.
- **Tickets aren't arriving by email**: check the order page — it shows the exact reason (`RESEND_API_KEY` missing, or the error Resend returned) and lets you resend once fixed.
- **Camera scanner shows "Camera unavailable"**: the browser needs HTTPS (Vercel provides this automatically) and camera permission; on iOS this only works in Safari, not an in-app browser.

## How the requirements are met

1. **Tiered pricing** — each event has Early Bird / Regular / VIP tiers (or any names you choose); each paid tier gets its own Stripe **Price** object, created automatically (`eventvault/payments.py`).
2. **QR-coded PDF ticket, emailed via Resend** — on payment, `orders.fulfil_order()` issues one row per ticket with a unique token, renders a branded PDF with an embedded QR code (`eventvault/tickets.py`), and emails every ticket as an attachment (`eventvault/emailer.py`).
3. **Camera check-in scanner** — `/#/scanner` uses the jsQR library against the device camera, decodes the code client-side, and posts it to `/api/checkin`.
4. **Duplicate / race-condition safety** — a ticket's `status` only ever flips `valid → used` inside a single `UPDATE ... WHERE status = 'valid'` statement (`orders.check_in`), which Postgres executes atomically per row: if two scans arrive at the same instant, the database guarantees exactly one `UPDATE` matches the row and returns it — the other gets zero rows affected and is told "already used." This is verified by an automated test that fires 16 simultaneous scans at one ticket (`tests/test_flow.py::test_two_devices_scanning_the_same_ticket_only_one_succeeds`) and confirms exactly one succeeds, every time.
