# routers/enrollment.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from asyncpg import PostgresError  # type: ignore

from db.database import get_db
from schemas.schemas import EnrollRequest, EnrollResponse

router = APIRouter()


@router.post(
    "/enroll",
    response_model=EnrollResponse,
    summary="Enroll student in a course",
    description=(
        "Validates prerequisites (all 5 dept approvals) and checks for schedule conflicts "
        "using PostgreSQL OVERLAPS before inserting the enrollment row. "
        "Returns a structured JSON error on conflict or missing approvals."
    ),
)
async def enroll_student(payload: EnrollRequest, db: AsyncSession = Depends(get_db)):

    # ── 1. Resolve student ───────────────────────────────────
    student_row = await db.execute(
        text("SELECT student_id FROM students WHERE email = :email"),
        {"email": payload.student_email},
    )
    student = student_row.mappings().first()
    if not student:
        raise HTTPException(status_code=404, detail=f"Student '{payload.student_email}' not found.")
    sid = student["student_id"]

    # ── 2. Resolve course ────────────────────────────────────
    course_row = await db.execute(
        text("SELECT course_id FROM courses WHERE course_code = :code"),
        {"code": payload.course_code},
    )
    course = course_row.mappings().first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Course '{payload.course_code}' not found.")
    cid = course["course_id"]

    # ── 3. Pre-flight: explicit OVERLAPS check (SQL layer) ───
    # This gives a clean API-level error BEFORE hitting the trigger,
    # so Framer gets a structured JSON response, not a 500.
    overlap_check = await db.execute(
        text("""
            SELECT
                c_existing.course_code  AS conflicting_code,
                c_existing.course_name  AS conflicting_name,
                s_existing.day,
                s_existing.start_time,
                s_existing.end_time,
                s_new.start_time        AS new_start,
                s_new.end_time          AS new_end
            FROM   enrollments   e
            JOIN   schedules     s_existing ON s_existing.course_id = e.course_id
            JOIN   courses       c_existing ON c_existing.course_id = e.course_id
            JOIN   schedules     s_new      ON s_new.course_id      = :new_course_id
            WHERE  e.student_id = :sid
            AND    e.term_id    = :tid
            AND    s_existing.day = s_new.day
            AND    (s_existing.start_time, s_existing.end_time)
                    OVERLAPS
                   (s_new.start_time, s_new.end_time)
            LIMIT 1
        """),
        {"new_course_id": cid, "sid": sid, "tid": payload.term_id},
    )
    conflict = overlap_check.mappings().first()

    if conflict:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "SCHEDULE_CONFLICT",
                "message": (
                    f"'{payload.course_code}' clashes with already-enrolled course "
                    f"'{conflict['conflicting_code']} – {conflict['conflicting_name']}' "
                    f"on {conflict['day']} "
                    f"({conflict['start_time'].strftime('%H:%M')}–{conflict['end_time'].strftime('%H:%M')})."
                ),
                "conflicting_course": conflict["conflicting_code"],
                "day": conflict["day"],
                "existing_slot": f"{conflict['start_time'].strftime('%H:%M')}–{conflict['end_time'].strftime('%H:%M')}",
                "new_slot": f"{conflict['new_start'].strftime('%H:%M')}–{conflict['new_end'].strftime('%H:%M')}",
            },
        )

    # ── 4. Pre-flight: verification gate (explicit check) ────
    approval_count = await db.execute(
        text("""
            SELECT COUNT(*) AS n
            FROM   verification_status
            WHERE  student_id = :sid AND term_id = :tid AND status = 'Approved'
        """),
        {"sid": sid, "tid": payload.term_id},
    )
    approved = approval_count.scalar()
    if approved < 5:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "VERIFICATION_INCOMPLETE",
                "message": f"Only {approved}/5 departments have approved. All 5 required before enrollment.",
                "approved_count": approved,
                "required": 5,
            },
        )

    # ── 5. Insert (triggers act as final safety net) ─────────
    try:
        result = await db.execute(
            text("""
                INSERT INTO enrollments (student_id, course_id, term_id)
                VALUES (:sid, :cid, :tid)
                RETURNING enrollment_id
            """),
            {"sid": sid, "cid": cid, "tid": payload.term_id},
        )
        enrollment_id = result.scalar()
        await db.commit()
    except Exception as exc:
        await db.rollback()
        msg = str(exc)

        # Parse named exception codes raised by our triggers
        if "SCHEDULE_CONFLICT" in msg:
            raise HTTPException(status_code=409, detail={"error_code": "SCHEDULE_CONFLICT", "message": msg})
        if "VERIFICATION_INCOMPLETE" in msg:
            raise HTTPException(status_code=403, detail={"error_code": "VERIFICATION_INCOMPLETE", "message": msg})
        if "duplicate key" in msg.lower():
            raise HTTPException(status_code=409, detail={"error_code": "ALREADY_ENROLLED", "message": "Student is already enrolled in this course for this term."})

        raise HTTPException(status_code=500, detail={"error_code": "DB_ERROR", "message": msg})

    return EnrollResponse(
        success=True,
        message=f"Successfully enrolled in '{payload.course_code}' for term {payload.term_id}.",
        enrollment_id=enrollment_id,
    )
