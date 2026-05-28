# main.py
# ============================================================
# ROGUE UNIVERSITY PORTAL — FastAPI backend
# Deploy target: Railway.app
# ============================================================
import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from db.database import engine
from routers import dashboard, enrollment, verification
from routers import auth, grades, sandbox, polls, electives, timetable

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rogue_portal")

ALLOWED_ORIGINS: list[str] = [
    "*",
    "https://*.framer.app",
    "https://*.framer.website",
]

FRAMER_ORIGIN = os.environ.get("FRAMER_ORIGIN", "")
if FRAMER_ORIGIN:
    ALLOWED_ORIGINS.append(FRAMER_ORIGIN)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀  Rogue Portal API starting up")
    yield
    await engine.dispose()
    logger.info("✅  Database connections closed")


app = FastAPI(
    title="Rogue University Portal API",
    version="2.0.0",
    description=(
        "Full backend for Vijaybhoomi's rogue scheduling portal. "
        "Handles auth (3 roles), student dashboards, course enrollment, "
        "sandbox heatmap, course polls, elective preferences, "
        "grade management, and timetable change requests."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.(framer\.app|framer\.website)$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
    )


# ── Auth ──────────────────────────────────────────────────────
app.include_router(auth.router,         prefix="/api/auth",         tags=["Auth"])

# ── Student ───────────────────────────────────────────────────
app.include_router(dashboard.router,    prefix="/api",              tags=["Dashboard"])
app.include_router(enrollment.router,   prefix="/api/registration", tags=["Enrollment"])
app.include_router(sandbox.router,      prefix="/api/sandbox",      tags=["Sandbox"])
app.include_router(electives.router,    prefix="/api/electives",    tags=["Electives"])

# ── Teacher ───────────────────────────────────────────────────
app.include_router(grades.router,       prefix="/api/grades",       tags=["Grades"])
app.include_router(timetable.router,    prefix="/api/timetable",    tags=["Timetable"])

# ── Admin ─────────────────────────────────────────────────────
app.include_router(verification.router, prefix="/api/verification", tags=["Verification"])
app.include_router(polls.router,        prefix="/api/polls",        tags=["Polls"])


# ── Health ────────────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "Rogue University Portal API",
        "version": "2.0.0",
        "status":  "ok",
        "docs":    "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
