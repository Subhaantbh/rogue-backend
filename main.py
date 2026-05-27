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

# ── Logging ──────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rogue_portal")

# ── CORS origins ─────────────────────────────────────────────
# Add your exact Framer preview/published URLs here.
# The wildcard ("*") works for development; restrict for production.
ALLOWED_ORIGINS: list[str] = [
    "*",                                   # dev / Framer preview
    "https://*.framer.app",               # all Framer preview sites
    "https://*.framer.website",           # published Framer sites
]

FRAMER_ORIGIN = os.environ.get("FRAMER_ORIGIN", "")   # set in Railway env vars
if FRAMER_ORIGIN:
    ALLOWED_ORIGINS.append(FRAMER_ORIGIN)


# ── Lifespan (startup / shutdown) ────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀  Rogue Portal API starting up")
    yield
    await engine.dispose()
    logger.info("✅  Database connections closed")


# ── App ───────────────────────────────────────────────────────
app = FastAPI(
    title="Rogue University Portal API",
    version="1.0.0",
    description=(
        "Backend for Vijaybhoomi's rogue scheduling portal. "
        "Handles student dashboards, course enrollment with conflict detection, "
        "and 5-department pre-verification approval pipeline."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ── CORS middleware ───────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.(framer\.app|framer\.website)$",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


# ── Global exception handler ──────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "error_code": "INTERNAL_ERROR", "message": "An unexpected error occurred."},
    )


# ── Routers ───────────────────────────────────────────────────
app.include_router(
    dashboard.router,
    prefix="/api",
    tags=["Dashboard"],
)
app.include_router(
    enrollment.router,
    prefix="/api/registration",
    tags=["Enrollment"],
)
app.include_router(
    verification.router,
    prefix="/api/verification",
    tags=["Verification"],
)


# ── Health + root ─────────────────────────────────────────────
@app.get("/", tags=["Health"])
async def root():
    return {
        "service": "Rogue University Portal API",
        "status": "ok",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
