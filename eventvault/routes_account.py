"""Self-serve organizer access: a plain user requests it, an admin approves or denies (see
routes_admin.py). Not self-service and not automatic on its own — this only ever creates a
pending request row; only an admin route can flip a user's role."""
import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import db
from .deps import require_user

router = APIRouter(prefix="/api")


class OrganizerRequestIn(BaseModel):
    message: str = Field(default="", max_length=500)


@router.post("/organizer-requests")
def request_organizer(body: OrganizerRequestIn, request: Request):
    user = require_user(request)
    if user["role"] in ("organizer", "admin"):
        raise HTTPException(409, "You can already create events.")
    try:
        db.run("INSERT INTO organizer_requests (user_id, message) VALUES (%s, %s)", (user["id"], body.message.strip()))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "You already have a request pending review.")
    return {"ok": True}


@router.get("/organizer-requests/mine")
def my_organizer_request(request: Request):
    user = require_user(request)
    row = db.one(
        """SELECT id, message, status, reviewed_at, created_at FROM organizer_requests
           WHERE user_id = %s ORDER BY created_at DESC LIMIT 1""", (user["id"],))
    if row:
        row["created_at"] = row["created_at"].isoformat()
        row["reviewed_at"] = row["reviewed_at"].isoformat() if row["reviewed_at"] else None
    return {"request": row}
