from fastapi import HTTPException, Request

from . import config, db, security


def site_url(request: Request) -> str:
    if config.SITE_URL:
        return config.SITE_URL
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host.split(',')[0].strip()}"


def current_user(request: Request):
    token = request.cookies.get(security.COOKIE_NAME)
    if not token:
        return None
    try:
        uid = security.read_session(token)
    except security.ConfigError as e:
        raise HTTPException(500, str(e))
    if not uid:
        return None
    return db.one("SELECT id, name, email, role, suspended_at FROM users WHERE id = %s", (uid,))


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Please log in to continue.")
    if user["suspended_at"]:
        raise HTTPException(403, "Your account has been suspended. Contact support if you think this is a mistake.")
    return user


def require_role(*roles):
    """Dependency factory: require_role("organizer", "admin") etc. Always implies require_user
    (logged in, not suspended) first."""
    def dep(request: Request):
        user = require_user(request)
        if user["role"] not in roles:
            raise HTTPException(403, "You don't have permission to do that.")
        return user
    return dep


def require_organizer(request: Request):
    return require_role("organizer", "admin")(request)


def require_admin(request: Request):
    return require_role("admin")(request)


def owned_event(event_id: int, user):
    """404 if the event doesn't exist, 403 if this user isn't its organiser. No admin bypass here on
    purpose: platform-wide power lives in exactly one place (routes_admin.py), so this stays exactly
    as strict for an admin acting as an organizer as it is for anyone else. The one deliberate
    exception — an admin scanning at someone else's event door — is owned_event_or_admin, below,
    used only by /api/checkin."""
    ev = db.one("SELECT * FROM events WHERE id = %s", (event_id,))
    if not ev:
        raise HTTPException(404, "Event not found.")
    if ev["organizer_id"] != user["id"]:
        raise HTTPException(403, "Only the organiser of this event can do that.")
    return ev


def owned_event_or_admin(event_id: int, user):
    """Like owned_event, but an admin may also pass for any event. Reserved for /api/checkin — an
    admin should be able to scan tickets at any event's door — and nowhere else; every other
    organizer-scoped route keeps owned_event's strict, no-exceptions check."""
    ev = db.one("SELECT * FROM events WHERE id = %s", (event_id,))
    if not ev:
        raise HTTPException(404, "Event not found.")
    if ev["organizer_id"] != user["id"] and user["role"] != "admin":
        raise HTTPException(403, "Only the organiser of this event can do that.")
    return ev
