# routers/sandbox.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from datetime import time, datetime
from typing import List

from db.database import get_db
from routers.dependencies import get_current_user, require_admin

router = APIRouter()


class SandboxDrop(BaseModel):
    course_id: int
    preferred_day: str
    preferred_start: time
    preferred_end: time


class SandboxOut(BaseModel):
    preference_id: int
    student_id: int
    course_id: int
    program: str
    preferred_day: str
    preferred_start: time
    preferred_end: time
    recorded_at: datetime


class HeatmapEntry(BaseModel):
    program: str
    course_id: int
    course_name: str
    preferred_day: str
    preferred_start: time
    count: int


@router.post(
    "/drop",
    response_model=SandboxOut,
    summary="Save final drag-drop position for a course",
    description="Student saves their preferred slot for a course. Upserts — only the final position is stored.",
)
async def save_sandbox_drop(
    payload: SandboxDrop,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can save sandbox preferences.")

    # Get student record and program
    student = await db.execute(
        text("SELECT student_id, program FROM students WHERE student_id = :sid"),
        {"sid": current_user["student_id"]},
    )
    student_row = student.mappings().first()
    if not student_row:
        raise HTTPException(status_code=404, detail="Student record not found.")

    result = await db.execute(
        text("""
            INSERT INTO sandbox_preferences
                (student_id, course_id, program, preferred_day, preferred_start, preferred_end, recorded_at)
            VALUES
                (:sid, :cid, :program, :day, :start, :end, NOW())
            ON CONFLICT (student_id, course_id) DO UPDATE
                SET preferred_day   = EXCLUDED.preferred_day,
                    preferred_start = EXCLUDED.preferred_start,
                    preferred_end   = EXCLUDED.preferred_end,
                    recorded_at     = EXCLUDED.recorded_at
            RETURNING *
        """),
        {
            "sid":     student_row["student_id"],
            "cid":     payload.course_id,
            "program": student_row["program"],
            "day":     payload.preferred_day,
            "start":   payload.preferred_start,
            "end":     payload.preferred_end,
        },
    )
    await db.commit()
    return SandboxOut(**result.mappings().first())


@router.get(
    "/my-preferences",
    response_model=List[SandboxOut],
    summary="Get current student's saved sandbox preferences",
)
async def get_my_sandbox(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can view their own sandbox.")

    rows = await db.execute(
        text("""
            SELECT * FROM sandbox_preferences
            WHERE student_id = :sid ORDER BY preferred_day, preferred_start
        """),
        {"sid": current_user["student_id"]},
    )
    return [SandboxOut(**r) for r in rows.mappings()]


@router.get(
    "/heatmap",
    response_model=List[HeatmapEntry],
    summary="Aggregated heatmap data — admin only",
    description="Returns preference counts grouped by program, course, day, and time slot. Used to visualise student learning preferences.",
)
async def get_heatmap(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    rows = await db.execute(
        text("""
            SELECT
                sp.program,
                sp.course_id,
                c.course_name,
                sp.preferred_day,
                sp.preferred_start,
                COUNT(*) AS count
            FROM   sandbox_preferences sp
            JOIN   courses             c ON c.course_id = sp.course_id
            GROUP  BY sp.program, sp.course_id, c.course_name,
                      sp.preferred_day, sp.preferred_start
            ORDER  BY sp.program, count DESC
        """)
    )
    return [HeatmapEntry(**r) for r in rows.mappings()]


@router.get(
    "/heatmap/by-program/{program}",
    response_model=List[HeatmapEntry],
    summary="Heatmap filtered by degree program — admin only",
)
async def get_heatmap_by_program(
    program: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    rows = await db.execute(
        text("""
            SELECT
                sp.program,
                sp.course_id,
                c.course_name,
                sp.preferred_day,
                sp.preferred_start,
                COUNT(*) AS count
            FROM   sandbox_preferences sp
            JOIN   courses             c ON c.course_id = sp.course_id
            WHERE  sp.program = :program
            GROUP  BY sp.program, sp.course_id, c.course_name,
                      sp.preferred_day, sp.preferred_start
            ORDER  BY count DESC
        """),
        {"program": program},
    )
    return [HeatmapEntry(**r) for r in rows.mappings()]
