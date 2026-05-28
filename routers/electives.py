# routers/electives.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import List
from datetime import datetime

from db.database import get_db
from routers.dependencies import get_current_user, require_admin

router = APIRouter()


class ElectivePreferenceItem(BaseModel):
    course_id: int
    preference_rank: int   # 1 = top choice


class SubmitPreferencesRequest(BaseModel):
    term_id: int
    preferences: List[ElectivePreferenceItem]


class PreferenceOut(BaseModel):
    preference_id: int
    student_id: int
    course_id: int
    course_name: str
    course_code: str
    program: str
    preference_rank: int
    submitted_at: datetime


class ElectiveSummaryEntry(BaseModel):
    course_id: int
    course_code: str
    course_name: str
    program: str
    total_interest: int
    rank_1_count: int
    rank_2_count: int
    rank_3_count: int


@router.post(
    "/submit",
    response_model=List[PreferenceOut],
    summary="Submit ranked elective preferences",
    description="Student submits their ranked elective choices. Replaces any existing preferences. Only Elective courses accepted.",
)
async def submit_preferences(
    payload: SubmitPreferencesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can submit elective preferences.")

    sid = current_user["student_id"]

    # Get student program
    student = await db.execute(
        text("SELECT program FROM students WHERE student_id = :sid"),
        {"sid": sid},
    )
    student_row = student.mappings().first()
    if not student_row:
        raise HTTPException(status_code=404, detail="Student not found.")

    # Validate all submitted courses are Electives
    course_ids = [p.course_id for p in payload.preferences]
    courses = await db.execute(
        text("""
            SELECT course_id, course_name, course_code, category::text
            FROM courses WHERE course_id = ANY(:ids)
        """),
        {"ids": course_ids},
    )
    course_map = {r["course_id"]: r for r in courses.mappings()}

    for pref in payload.preferences:
        c = course_map.get(pref.course_id)
        if not c:
            raise HTTPException(status_code=404, detail=f"Course {pref.course_id} not found.")
        if c["category"] != "Elective":
            raise HTTPException(
                status_code=400,
                detail=f"Course '{c['course_code']}' is a Core course. Only Elective preferences can be submitted here.",
            )

    # Validate no duplicate ranks
    ranks = [p.preference_rank for p in payload.preferences]
    if len(ranks) != len(set(ranks)):
        raise HTTPException(status_code=422, detail="Duplicate preference ranks are not allowed.")

    # Delete existing preferences and re-insert (full replace)
    await db.execute(
        text("DELETE FROM elective_preferences WHERE student_id = :sid"),
        {"sid": sid},
    )

    inserted = []
    for pref in payload.preferences:
        result = await db.execute(
            text("""
                INSERT INTO elective_preferences
                    (student_id, course_id, program, preference_rank, submitted_at)
                VALUES (:sid, :cid, :program, :rank, NOW())
                RETURNING preference_id, student_id, course_id, program, preference_rank, submitted_at
            """),
            {
                "sid":     sid,
                "cid":     pref.course_id,
                "program": student_row["program"],
                "rank":    pref.preference_rank,
            },
        )
        row = result.mappings().first()
        c = course_map[pref.course_id]
        inserted.append(PreferenceOut(
            **row,
            course_name=c["course_name"],
            course_code=c["course_code"],
        ))

    await db.commit()
    return inserted


@router.get(
    "/my-preferences",
    response_model=List[PreferenceOut],
    summary="Get student's current elective preferences",
)
async def get_my_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can view their own preferences.")

    rows = await db.execute(
        text("""
            SELECT ep.preference_id, ep.student_id, ep.course_id,
                   c.course_name, c.course_code, ep.program,
                   ep.preference_rank, ep.submitted_at
            FROM   elective_preferences ep
            JOIN   courses              c ON c.course_id = ep.course_id
            WHERE  ep.student_id = :sid
            ORDER  BY ep.preference_rank
        """),
        {"sid": current_user["student_id"]},
    )
    return [PreferenceOut(**r) for r in rows.mappings()]


@router.get(
    "/summary",
    response_model=List[ElectiveSummaryEntry],
    summary="Aggregated elective preference summary — admin only",
    description="Shows how many students want each elective, broken down by program and rank. Used by admin to decide which electives to run and schedule.",
)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    rows = await db.execute(
        text("""
            SELECT
                ep.course_id,
                c.course_code,
                c.course_name,
                ep.program,
                COUNT(*)                                            AS total_interest,
                COUNT(*) FILTER (WHERE ep.preference_rank = 1)     AS rank_1_count,
                COUNT(*) FILTER (WHERE ep.preference_rank = 2)     AS rank_2_count,
                COUNT(*) FILTER (WHERE ep.preference_rank = 3)     AS rank_3_count
            FROM   elective_preferences ep
            JOIN   courses              c ON c.course_id = ep.course_id
            GROUP  BY ep.course_id, c.course_code, c.course_name, ep.program
            ORDER  BY ep.program, total_interest DESC
        """)
    )
    return [ElectiveSummaryEntry(**r) for r in rows.mappings()]
