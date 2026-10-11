"""EventVault: API + website.

Local:   uvicorn app:app --reload        ->  http://localhost:8000
Vercel:  detected automatically (FastAPI instance named `app`); public/ is served from the CDN.
"""
from pathlib import Path

import psycopg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import PoolTimeout

from eventvault import config, routes_account, routes_admin, routes_auth, routes_orders, routes_organizer, routes_public

app = FastAPI(title="EventVault", docs_url="/api/docs", openapi_url="/api/openapi.json")
for r in (routes_auth.router, routes_public.router, routes_organizer.router, routes_orders.router,
          routes_account.router, routes_admin.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.exception_handler(RequestValidationError)
def validation_error(request: Request, exc: RequestValidationError):
    err = exc.errors()[0]
    field = str(err["loc"][-1]).replace("_", " ")
    msg = err.get("msg", "is invalid")
    return JSONResponse({"detail": f"Please check the {field} field: {msg}."}, status_code=422)


@app.exception_handler(psycopg.OperationalError)
@app.exception_handler(PoolTimeout)
def db_down(request: Request, exc: Exception):
    return JSONResponse({"detail": "Can't reach the database. Check that DATABASE_URL is set correctly."}, status_code=503)


@app.exception_handler(psycopg.errors.UndefinedTable)
def no_tables(request: Request, exc: Exception):
    return JSONResponse({"detail": "The database tables don't exist yet. Run: python seed.py"}, status_code=503)


# Locally there is no CDN, so serve public/ ourselves. On Vercel the platform serves public/.
if not config.ON_VERCEL:
    app.mount("/", StaticFiles(directory=Path(__file__).parent / "public", html=True), name="public")
