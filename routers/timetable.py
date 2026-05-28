# routers/timetable.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List
from datetime import date, time, datetime, timezone

from db.database import get_db
from routers.dependencies import get_current_user, require_admin, require_teacher

router = APIRouter()


class ChangeRequestCreate(BaseModel):
    course_id: int
    request_date: date       # the specific day being changed
    original_time: time
    new_time: Optional[time] = None   # None = class cancelled that day
    reason: str


class ChangeRequestOut(BaseModel):
    request_id: int
    course_id: int
    course_name: str
    requested_by: int
    request_date: date
    original_time: time
    new_time: Optional[time]
    reason: str
    status: str
    reviewed_by: Optional[int]
    reviewed_at: Optional[datetime]
    created_at: datetime


class ReviewRequest(BaseModel):
    status: str   # 'approved' or 'rejected'


@router.post(
    "/request",
    response_model=ChangeRequestOut,
    summary="Teacher requests a one-day timetable change",
    description="Teacher submits a request to change or cancel a class on a specific day. Goes to admin for approval.",
)
async def create_change_request(
    payload: ChangeRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_teacher),
):
    # Verify teacher is assigned to this course
    assignment = await db.execute(
        text("""
            SELECT assignment_id FROM teacher_course_assignments
            WHERE user_id = :uid AND course_id = :cid
        """),
        {"uid": current_user["user_id"], "cid": payload.course_id},
    )
    if not assignment.mappings().first() and current_user["role"] != "admin":
        raise HTTPException(
            status_code=403,
            detail="You are not assigned to this course.",
        )

    course = await db.execute(
        text("SELECT course_name FROM courses WHERE course_id = :cid"),
        {"cid": payload.course_id},
    )
    course_row = course.mappings().first()
    if not course_row:
        raise HTTPException(status_code=404, detail="Course not found.")

    result = await db.execute(
        text("""
            INSERT INTO timetable_change_requests
                (course_id, requested_by, request_date, original_time, new_time, reason, status, created_at)
            VALUES
                (:cid, :uid, :rdate, :orig, :new, :reason, 'pending', NOW())
            RETURNING
                request_id, course_id, requested_by, request_date,
                original_time, new_time, reason, status::text,
                reviewed_by, reviewed_at, created_at
        """),
        {
            "cid":    payload.course_id,
            "uid":    current_user["user_id"],
            "rdate":  payload.request_date,
            "orig":   payload.original_time,
            "new":    payload.new_time,
            "reason": payload.reason,
        },
    )
    await db.commit()
    row = result.mappings().first()

    return ChangeRequestOut(**row, course_name=course_row["course_name"])


@router.patch(
    "/{request_id}/review",
    response_model=ChangeRequestOut,
    summary="Admin approves or rejects a timetable change request",
    description="Once approved, the change is visible on enrolled students' dashboards.",
)
async def review_request(
    request_id: int,
    payload: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="Status must be 'approved' or 'rejected'.")

    result = await db.execute(
        text("""
            UPDATE timetable_change_requests
            SET    status      = :status,
                   reviewed_by = :uid,
                   reviewed_at = :now
            WHERE  request_id  = :rid
            RETURNING
                request_id, course_id, requested_by, request_date,
                original_time, new_time, reason, status::text,
                reviewed_by, reviewed_at, created_at
        """),
        {
            "status": payload.status,
            "uid":    current_user["user_id"],
            "now":    datetime.now(timezone.utc),
            "rid":    request_id,
        },
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Change request not found.")

    await db.commit()

    course = await db.execute(
        text("SELECT course_name FROM courses WHERE course_id = :cid"),
        {"cid": row["course_id"]},
    )
    course_name = course.mappings().first()["course_name"]

    return ChangeRequestOut(**row, course_name=course_name)


@router.get(
    "/pending",
    response_model=List[ChangeRequestOut],
    summary="Get all pending timetable change requests — admin only",
)
async def get_pending_requests(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    rows = await db.execute(
        text("""
            SELECT
                r.request_id, r.course_id, c.course_name,
                r.requested_by, r.request_date, r.original_time,
                r.new_time, r.reason, r.status::text,
                r.reviewed_by, r.reviewed_at, r.created_at
            FROM   timetable_change_requests r
            JOIN   courses                   c ON c.course_id = r.course_id
            WHERE  r.status = 'pending'
            ORDER  BY r.request_date ASC
        """)
    )
    return [ChangeRequestOut(**r) for r in rows.mappings()]


@router.get(
    "/course/{course_id}",
    response_model=List[ChangeRequestOut],
    summary="Get approved timetable changes for a course",
    description="Students see this on their dashboard to know about upcoming class changes.",
)
async def get_course_changes(
    course_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    rows = await db.execute(
        text("""
            SELECT
                r.request_id, r.course_id, c.course_name,
                r.requested_by, r.request_date, r.original_time,
                r.new_time, r.reason, r.status::text,
                r.reviewed_by, r.reviewed_at, r.created_at
            FROM   timetable_change_requests r
            JOIN   courses                   c ON c.course_id = r.course_id
            WHERE  r.course_id = :cid
            AND    r.status    = 'approved'
            AND    r.request_date >= CURRENT_DATE
            ORDER  BY r.request_date ASC
        """),
        {"cid": course_id},
    )
    return [ChangeRequestOut(**r) for r in rows.mappings()]


@router.get(
    "/teacher/my-timetable",
    summary="Get teacher's own course timetable",
    description="Returns all courses and their schedules for the currently logged-in teacher.",
)
async def get_teacher_timetable(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_teacher),
):
    rows = await db.execute(
        text("""
            SELECT
                c.course_id, c.course_code, c.course_name,
                c.credits, c.category::text,
                s.day, s.start_time, s.end_time,
                t.term_name
            FROM   teacher_course_assignments tca
            JOIN   courses                    c ON c.course_id = tca.course_id
            JOIN   terms                      t ON t.term_id   = tca.term_id
            LEFT   JOIN schedules             s ON s.course_id = c.course_id
            WHERE  tca.user_id  = :uid
            AND    t.is_active  = TRUE
            ORDER  BY s.day, s.start_time
        """),
        {"uid": current_user["user_id"]},
    )
    return [dict(r) for r in rows.mappings()]
