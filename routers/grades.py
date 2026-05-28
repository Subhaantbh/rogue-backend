# routers/grades.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone

from db.database import get_db
from routers.dependencies import get_current_user, require_teacher

router = APIRouter()


class GradeUpdate(BaseModel):
    enrollment_id: int
    grade: str
    grade_points: float


class GradeOut(BaseModel):
    grade_id: int
    enrollment_id: int
    grade: Optional[str]
    grade_points: Optional[float]
    updated_by: int
    updated_at: datetime


@router.patch(
    "/update",
    response_model=GradeOut,
    summary="Update a student grade",
    description="Only the teacher assigned to that course for that term can update the grade.",
)
async def update_grade(
    payload: GradeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_teacher),
):
    # Verify this teacher is assigned to the course this enrollment belongs to
    check = await db.execute(
        text("""
            SELECT tca.assignment_id
            FROM   enrollments             e
            JOIN   teacher_course_assignments tca
                   ON tca.course_id = e.course_id
                   AND tca.term_id  = e.term_id
            WHERE  e.enrollment_id = :eid
            AND    tca.user_id     = :uid
        """),
        {"eid": payload.enrollment_id, "uid": current_user["user_id"]},
    )
    if not check.mappings().first():
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to the course this enrollment belongs to.",
        )

    # Upsert grade
    result = await db.execute(
        text("""
            INSERT INTO grades (enrollment_id, grade, grade_points, updated_by, updated_at)
            VALUES (:eid, :grade, :gp, :uid, :now)
            ON CONFLICT (enrollment_id) DO UPDATE
                SET grade        = EXCLUDED.grade,
                    grade_points = EXCLUDED.grade_points,
                    updated_by   = EXCLUDED.updated_by,
                    updated_at   = EXCLUDED.updated_at
            RETURNING grade_id, enrollment_id, grade, grade_points, updated_by, updated_at
        """),
        {
            "eid":   payload.enrollment_id,
            "grade": payload.grade,
            "gp":    payload.grade_points,
            "uid":   current_user["user_id"],
            "now":   datetime.now(timezone.utc),
        },
    )
    await db.commit()
    return GradeOut(**result.mappings().first())


@router.get(
    "/enrollment/{enrollment_id}",
    response_model=GradeOut,
    summary="Get grade for an enrollment",
)
async def get_grade(
    enrollment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Students can only see their own grades
    if current_user["role"] == "student":
        owner_check = await db.execute(
            text("""
                SELECT e.enrollment_id FROM enrollments e
                JOIN   students s ON s.student_id = e.student_id
                JOIN   users    u ON u.student_id = s.student_id
                WHERE  e.enrollment_id = :eid AND u.user_id = :uid
            """),
            {"eid": enrollment_id, "uid": current_user["user_id"]},
        )
        if not owner_check.mappings().first():
            raise HTTPException(status_code=403, detail="You can only view your own grades.")

    row = await db.execute(
        text("""
            SELECT grade_id, enrollment_id, grade, grade_points, updated_by, updated_at
            FROM   grades WHERE enrollment_id = :eid
        """),
        {"eid": enrollment_id},
    )
    grade = row.mappings().first()
    if not grade:
        raise HTTPException(status_code=404, detail="No grade recorded yet for this enrollment.")
    return GradeOut(**grade)
