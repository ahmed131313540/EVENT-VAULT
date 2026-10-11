import base64
import hashlib
import hmac
import json
import os
import re
import time

from . import config

SESSION_DAYS = 14
COOKIE_NAME = "ev_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ConfigError(RuntimeError):
    pass


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk, _unb64(digest))
    except Exception:
        return False        # includes the "!" placeholder used by demo organisers, which can't log in


def _secret() -> bytes:
    if not config.SECRET_KEY:
        raise ConfigError("SECRET_KEY is not set. Add it in your Vercel project's Environment Variables.")
    return config.SECRET_KEY.encode()


def make_session(user_id: int) -> str:
    body = _b64(json.dumps({"u": user_id, "e": int(time.time()) + SESSION_DAYS * 86400}).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_session(token: str):
    """Returns the user id inside a valid, unexpired session cookie, else None."""
    try:
        body, sig = token.split(".")
        good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(_unb64(body))
        return data["u"] if data["e"] > time.time() else None
    except ConfigError:
        raise
    except Exception:
        return None
