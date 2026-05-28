# routers/dependencies.py
from __future__ import annotations
import os
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from db.database import get_db

SECRET_KEY  = os.environ.get("SECRET_KEY", "change_me_in_production_please")
ALGORITHM   = "HS256"
bearer      = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Decode JWT and return the current user row."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        if user_id is None:
            raise ValueError
    except (JWTError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    row = await db.execute(
        text("""
            SELECT user_id, email, role::text, student_id,
                   can_approve_departments, is_active
            FROM   users WHERE user_id = :uid
        """),
        {"uid": user_id},
    )
    user = row.mappings().first()
    if not user or not user["is_active"]:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    return dict(user)


def require_role(*roles: str):
    """Dependency factory — restricts endpoint to specific roles."""
    async def checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role(s): {list(roles)}. Your role: {current_user['role']}",
            )
        return current_user
    return checker


# Convenience shorthands
require_student = require_role("student")
require_teacher = require_role("teacher", "admin")
require_admin   = require_role("admin")
require_any     = require_role("student", "teacher", "admin")
