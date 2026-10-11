from contextlib import contextmanager
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_pool = None


def pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            config.DATABASE_URL, min_size=1, max_size=10, open=False, timeout=15, max_idle=30,
            check=ConnectionPool.check_connection,
            # prepare_threshold=None keeps this compatible with pgbouncer-style pooled connection strings
            kwargs={"prepare_threshold": None, "connect_timeout": 10, "row_factory": dict_row},
        )
        _pool.open()
    return _pool


@contextmanager
def conn():
    """A transaction: commits on success, rolls back if the block raises."""
    with pool().connection() as c:
        yield c


def one(sql, args=None):
    with conn() as c:
        return c.execute(sql, args).fetchone()


def all_(sql, args=None):
    with conn() as c:
        return c.execute(sql, args).fetchall()


def run(sql, args=None):
    with conn() as c:
        return c.execute(sql, args).rowcount


def init_schema(reset=False):
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with conn() as c:
        if reset:
            c.execute("DROP TABLE IF EXISTS organizer_requests, scans, tickets, order_items, orders, ticket_tiers, events, messages, users CASCADE")
        # Upgrading a database that predates roles? Note it before the schema adds users.role, so that
        # accounts which could already create events (they own at least one) keep that ability. Runs once:
        # after the upgrade the column exists, so later runs skip this and never re-promote anyone an admin
        # has since demoted.
        had_users = c.execute("SELECT to_regclass('public.users') IS NOT NULL AS t").fetchone()["t"]
        had_role = had_users and c.execute(
            "SELECT count(*) AS n FROM information_schema.columns WHERE table_name = 'users' AND column_name = 'role'").fetchone()["n"] > 0
        c.execute(sql)
        if had_users and not had_role:
            c.execute("UPDATE users SET role = 'organizer' WHERE role = 'user' AND EXISTS (SELECT 1 FROM events e WHERE e.organizer_id = users.id)")
