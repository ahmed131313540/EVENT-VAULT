CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
    id                BIGSERIAL PRIMARY KEY,
    organizer_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title             TEXT NOT NULL,
    category          TEXT NOT NULL,
    description       TEXT NOT NULL,
    venue             TEXT NOT NULL,
    city              TEXT NOT NULL,
    starts_at         TIMESTAMP NOT NULL,              -- venue-local wall-clock time
    contact_email     TEXT NOT NULL,
    contact_phone     TEXT,
    image             BYTEA,
    image_type        TEXT,
    featured          BOOLEAN NOT NULL DEFAULT false,
    stripe_product_id TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS events_starts_idx ON events (starts_at);
CREATE INDEX IF NOT EXISTS events_organizer_idx ON events (organizer_id);

CREATE TABLE IF NOT EXISTS ticket_tiers (
    id              BIGSERIAL PRIMARY KEY,
    event_id        BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    price_cents     INTEGER NOT NULL CHECK (price_cents >= 0),
    quantity        INTEGER NOT NULL CHECK (quantity > 0),
    sold            INTEGER NOT NULL DEFAULT 0,
    stripe_price_id TEXT,                               -- one Stripe Price per tier
    sort_order      INTEGER NOT NULL DEFAULT 0,
    CHECK (sold >= 0 AND sold <= quantity)
);
CREATE INDEX IF NOT EXISTS tiers_event_idx ON ticket_tiers (event_id);

CREATE TABLE IF NOT EXISTS orders (
    id                BIGSERIAL PRIMARY KEY,
    public_ref        TEXT NOT NULL UNIQUE,
    user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_id          BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid', 'expired', 'failed')),
    payment_mode      TEXT NOT NULL CHECK (payment_mode IN ('stripe', 'demo', 'free')),
    total_cents       INTEGER NOT NULL,
    currency          TEXT NOT NULL,
    buyer_name        TEXT NOT NULL,
    buyer_email       TEXT NOT NULL,
    stripe_session_id TEXT UNIQUE,
    expires_at        TIMESTAMPTZ NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at           TIMESTAMPTZ,
    emailed_at        TIMESTAMPTZ,
    email_error       TEXT
);
CREATE INDEX IF NOT EXISTS orders_user_idx ON orders (user_id);
CREATE INDEX IF NOT EXISTS orders_event_idx ON orders (event_id);

CREATE TABLE IF NOT EXISTS order_items (
    id               BIGSERIAL PRIMARY KEY,
    order_id         BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    tier_id          BIGINT NOT NULL REFERENCES ticket_tiers(id) ON DELETE CASCADE,
    quantity         INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS items_tier_idx ON order_items (tier_id);

CREATE TABLE IF NOT EXISTS tickets (
    id          BIGSERIAL PRIMARY KEY,
    token       TEXT NOT NULL UNIQUE,                   -- what the QR code contains
    order_id    BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    event_id    BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    tier_id     BIGINT NOT NULL REFERENCES ticket_tiers(id) ON DELETE CASCADE,
    holder_name TEXT NOT NULL,
    seq         INTEGER NOT NULL,                       -- "ticket 2 of 3" within its order
    status      TEXT NOT NULL DEFAULT 'valid' CHECK (status IN ('valid', 'used', 'void')),
    used_at     TIMESTAMPTZ,
    used_by     BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (order_id, seq)                              -- backstop: an order can only be fulfilled once
);
CREATE INDEX IF NOT EXISTS tickets_event_idx ON tickets (event_id);
CREATE INDEX IF NOT EXISTS tickets_order_idx ON tickets (order_id);

CREATE TABLE IF NOT EXISTS scans (
    id         BIGSERIAL PRIMARY KEY,
    event_id   BIGINT NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    ticket_id  BIGINT REFERENCES tickets(id) ON DELETE SET NULL,
    code_hint  TEXT,
    result     TEXT NOT NULL,                           -- ok | already_used | wrong_event | invalid | void
    scanned_by BIGINT REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS scans_event_idx ON scans (event_id, created_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id         BIGSERIAL PRIMARY KEY,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------- role-based access (additive)
ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT NOT NULL DEFAULT 'user'
    CHECK (role IN ('user', 'organizer', 'admin'));
ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS organizer_requests (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message      TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'denied')),
    reviewed_by  BIGINT REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS organizer_requests_status_idx ON organizer_requests (status, created_at);
-- one open request per user at a time
CREATE UNIQUE INDEX IF NOT EXISTS organizer_requests_one_pending
    ON organizer_requests (user_id) WHERE status = 'pending';

ALTER TABLE events ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'cancelled'));
ALTER TABLE events ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMPTZ;

ALTER TABLE orders ADD COLUMN IF NOT EXISTS stripe_payment_intent_id TEXT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refunded_cents INTEGER NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ;

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS void_reason TEXT;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS reissued_from BIGINT REFERENCES tickets(id) ON DELETE SET NULL;

-- A reissued ticket inserts a new row at the same (order_id, seq) slot as the ticket it replaces, once
-- that old row is voided. The original inline UNIQUE(order_id, seq) forbids that outright, so replace it
-- with a partial unique index that only enforces "at most one *active* ticket per slot" (its auto-generated
-- name follows Postgres's default <table>_<col1>_<col2>_key convention, so this is safe to run against a
-- database that still has the original constraint from before reissue existed, and a no-op otherwise).
ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_order_id_seq_key;
CREATE UNIQUE INDEX IF NOT EXISTS tickets_order_seq_active_unique ON tickets (order_id, seq) WHERE status <> 'void';
