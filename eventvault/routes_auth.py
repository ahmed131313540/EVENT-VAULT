import psycopg
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import db, security
from .deps import current_user

router = APIRouter(prefix="/api/auth")


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=200)
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=128)


def _start_session(request: Request, response: Response, user_id: int):
    try:
        token = security.make_session(user_id)
    except security.ConfigError as e:
        raise HTTPException(500, str(e))
    secure = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip() == "https"
    response.set_cookie(security.COOKIE_NAME, token, max_age=security.SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=secure, path="/")


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response):
    email = body.email.strip().lower()
    if not security.EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    try:
        user = db.one("INSERT INTO users (name, email, password_hash) VALUES (%s,%s,%s) RETURNING id, name, email, role, suspended_at",
                      (body.name.strip(), email, security.hash_password(body.password)))
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, "An account with this email already exists. Try logging in.")
    _start_session(request, response, user["id"])
    return {"user": user}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    row = db.one("SELECT id, name, email, password_hash, role, suspended_at FROM users WHERE email = %s", (body.email.strip().lower(),))
    if not row or not security.verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Incorrect email or password.")
    if row["suspended_at"]:
        raise HTTPException(403, "Your account has been suspended. Contact support if you think this is a mistake.")
    _start_session(request, response, row["id"])
    return {"user": {"id": row["id"], "name": row["name"], "email": row["email"], "role": row["role"], "suspended_at": row["suspended_at"]}}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(security.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return {"user": current_user(request)}
