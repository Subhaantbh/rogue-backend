# routers/dashboard.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from db.database import get_db
from schemas.schemas import DashboardResponse, StudentBase, AcademicRecord, CourseOut, ScheduleOut, VerificationOut

router = APIRouter()


@router.get(
    "/student/{email}/dashboard",
    response_model=DashboardResponse,
    summary="Full student dashboard",
    description="Returns student profile, academic history, enrolled courses with schedule grid, and 5-department verification tracker.",
)
async def get_dashboard(email: str, db: AsyncSession = Depends(get_db)):

    # ── 1. Student ───────────────────────────────────────────
    student_row = await db.execute(
        text("SELECT student_id, name, email, program, year FROM students WHERE email = :email"),
        {"email": email},
    )
    student = student_row.mappings().first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student '{email}' not found.")

    sid = student["student_id"]

    # ── 2. Academic records ──────────────────────────────────
    ar_rows = await db.execute(
        text("SELECT level, board, percentage FROM academic_records WHERE student_id = :sid ORDER BY level"),
        {"sid": sid},
    )
    academic_records = [AcademicRecord(**r) for r in ar_rows.mappings()]

    # ── 3. Active term ───────────────────────────────────────
    term_row = await db.execute(
        text("SELECT term_id, term_name FROM terms WHERE is_active = TRUE LIMIT 1")
    )
    term = term_row.mappings().first()
    if not term:
        raise HTTPException(status_code=404, detail="No active term found.")

    tid = term["term_id"]

    # ── 4. Enrolled courses + schedules ──────────────────────
    course_rows = await db.execute(
        text("""
            SELECT c.course_id, c.course_code, c.course_name, c.credits, c.category::text,
                   s.schedule_id, s.day, s.start_time, s.end_time
            FROM   enrollments e
            JOIN   courses     c ON c.course_id   = e.course_id
            LEFT   JOIN schedules s ON s.course_id = c.course_id
            WHERE  e.student_id = :sid AND e.term_id = :tid
            ORDER  BY c.course_id, s.day, s.start_time
        """),
        {"sid": sid, "tid": tid},
    )

    # Aggregate schedules under each course
    course_map: dict = {}
    for r in course_rows.mappings():
        cid = r["course_id"]
        if cid not in course_map:
            course_map[cid] = CourseOut(
                course_id=cid,
                course_code=r["course_code"],
                course_name=r["course_name"],
                credits=r["credits"],
                category=r["category"],
                schedules=[],
            )
        if r["schedule_id"]:
            course_map[cid].schedules.append(
                ScheduleOut(
                    schedule_id=r["schedule_id"],
                    day=r["day"],
                    start_time=r["start_time"],
                    end_time=r["end_time"],
                )
            )

    # ── 5. Verification tracker ──────────────────────────────
    ver_rows = await db.execute(
        text("""
            SELECT verification_id, department::text, status::text,
                   hostel_preference, rejection_reason, reviewed_by, reviewed_at
            FROM   verification_status
            WHERE  student_id = :sid AND term_id = :tid
            ORDER  BY department
        """),
        {"sid": sid, "tid": tid},
    )
    verification = [VerificationOut(**r) for r in ver_rows.mappings()]

    return DashboardResponse(
        student=StudentBase(**student),
        academic_records=academic_records,
        enrolled_courses=list(course_map.values()),
        verification=verification,
        term_id=tid,
        term_name=term["term_name"],
    )
