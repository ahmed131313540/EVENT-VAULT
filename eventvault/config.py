import os
from pathlib import Path


def _load_dotenv():
    """Tiny .env loader for local development (Vercel injects real environment variables)."""
    path = Path(__file__).resolve().parent.parent / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

ON_VERCEL = bool(os.getenv("VERCEL"))

DATABASE_URL = (os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
                or "postgresql://postgres:eventvault@localhost:5432/eventvault")

# Sessions are signed with this. Locally a fixed dev value is fine; on Vercel it must be set.
SECRET_KEY = os.getenv("SECRET_KEY") or (None if ON_VERCEL else "dev-only-insecure-secret")

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", "EventVault <onboarding@resend.dev>")
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")
CURRENCY = os.getenv("CURRENCY", "usd").lower()

# "stripe" when a Stripe key is present, otherwise "demo" (orders complete instantly, no money moves).
PAYMENTS_MODE = "stripe" if STRIPE_SECRET_KEY else "demo"

CATEGORIES = ["Music", "Conferences", "Weddings", "Sports", "Workshops", "Festivals", "Parties", "Technology"]
MAX_TICKETS_PER_ORDER = 10
CHECKOUT_MINUTES = 31          # Stripe requires >= 30 min; seats stay reserved this long
