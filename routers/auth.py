# routers/auth.py
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from passlib.context import CryptContext
from jose import jwt
from pydantic import BaseModel

from db.database import get_db

router      = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY  = os.environ.get("SECRET_KEY", "change_me_in_production_please")
ALGORITHM   = "HS256"
TOKEN_EXPIRE_HOURS = 24


# ── Schemas ───────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    student_id: int | None
    email: str


# ── Helpers ───────────────────────────────────────────────────
def create_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(
        {"sub": user_id, "exp": expire},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


# ── Endpoints ─────────────────────────────────────────────────
@router.post(
    "/login",
    response_model=LoginResponse,
    summary="Login — returns JWT token",
    description="Accepts email + password, returns a JWT. Include it as `Authorization: Bearer <token>` on all protected routes.",
)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    row = await db.execute(
        text("""
            SELECT user_id, email, hashed_password, role::text,
                   student_id, is_active
            FROM   users WHERE email = :email
        """),
        {"email": payload.email},
    )
    user = row.mappings().first()

    if not user or not pwd_context.verify(payload.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account is inactive.")

    token = create_token(user["user_id"])

    return LoginResponse(
        access_token=token,
        role=user["role"],
        user_id=user["user_id"],
        student_id=user["student_id"],
        email=user["email"],
    )


@router.post(
    "/register-student",
    summary="Register a new student account (admin only in production)",
    description="Creates a user account linked to an existing student record.",
)
async def register_student(
    email: str,
    password: str,
    db: AsyncSession = Depends(get_db),
):
    # Check student exists
    student = await db.execute(
        text("SELECT student_id FROM students WHERE email = :email"),
        {"email": email},
    )
    student_row = student.mappings().first()
    if not student_row:
        raise HTTPException(status_code=404, detail=f"No student found with email {email}.")

    hashed = pwd_context.hash(password)

    try:
        await db.execute(
            text("""
                INSERT INTO users (email, hashed_password, role, student_id)
                VALUES (:email, :pw, 'student', :sid)
            """),
            {"email": email, "pw": hashed, "sid": student_row["student_id"]},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="User with this email already exists.")

    return {"success": True, "message": f"Student account created for {email}."}
