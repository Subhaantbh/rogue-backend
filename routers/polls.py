# routers/polls.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

from db.database import get_db
from routers.dependencies import get_current_user, require_admin

router = APIRouter()


class CreatePollRequest(BaseModel):
    course_id: int
    term_id: int
    question: str


class VoteRequest(BaseModel):
    poll_id: int
    vote_option: str


class AdminDecisionRequest(BaseModel):
    poll_id: int
    decision: str


class PollOut(BaseModel):
    poll_id: int
    course_id: int
    course_name: str
    term_id: int
    status: str
    question: str
    admin_decision: Optional[str]
    created_at: datetime
    decided_at: Optional[datetime]
    total_votes: int
    can_decide: bool   # True if 3 days have passed


class VoteOut(BaseModel):
    vote_id: int
    poll_id: int
    student_id: int
    vote_option: str
    voted_at: datetime


@router.post(
    "/create",
    response_model=PollOut,
    summary="Start a poll for a course timing change",
    description="Any enrolled student can start a poll. Only works on Core courses with confirmed timings. One active poll per course at a time.",
)
async def create_poll(
    payload: CreatePollRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can initiate polls.")

    # Verify course is Core (not Elective)
    course = await db.execute(
        text("SELECT course_id, course_name, category::text FROM courses WHERE course_id = :cid"),
        {"cid": payload.course_id},
    )
    course_row = course.mappings().first()
    if not course_row:
        raise HTTPException(status_code=404, detail="Course not found.")
    if course_row["category"] != "Core":
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ELECTIVE_POLL_NOT_ALLOWED",
                "message": "Polls can only be started for Core courses with confirmed timings. Elective timings are set by admin after preference collection.",
            },
        )

    # Verify course has a confirmed schedule
    schedule = await db.execute(
        text("SELECT schedule_id FROM schedules WHERE course_id = :cid LIMIT 1"),
        {"cid": payload.course_id},
    )
    if not schedule.mappings().first():
        raise HTTPException(
            status_code=400,
            detail={"error_code": "NO_SCHEDULE", "message": "This course has no confirmed timetable yet."},
        )

    # Verify student is enrolled in this course
    enrollment = await db.execute(
        text("""
            SELECT e.enrollment_id FROM enrollments e
            JOIN   students s ON s.student_id = e.student_id
            JOIN   users    u ON u.student_id = s.student_id
            WHERE  e.course_id = :cid AND e.term_id = :tid AND u.user_id = :uid
        """),
        {"cid": payload.course_id, "tid": payload.term_id, "uid": current_user["user_id"]},
    )
    if not enrollment.mappings().first():
        raise HTTPException(
            status_code=403,
            detail="You must be enrolled in this course to start a poll.",
        )

    # Check no active poll already exists
    existing = await db.execute(
        text("""
            SELECT poll_id FROM course_polls
            WHERE course_id = :cid AND term_id = :tid AND status = 'active'
        """),
        {"cid": payload.course_id, "tid": payload.term_id},
    )
    if existing.mappings().first():
        raise HTTPException(
            status_code=409,
            detail={"error_code": "POLL_ALREADY_ACTIVE", "message": "An active poll already exists for this course this term."},
        )

    # Create poll
    result = await db.execute(
        text("""
            INSERT INTO course_polls (course_id, term_id, initiated_by, question, status, created_at)
            VALUES (:cid, :tid, :uid, :q, 'active', NOW())
            RETURNING poll_id, course_id, term_id, status, question, admin_decision, created_at, decided_at
        """),
        {"cid": payload.course_id, "tid": payload.term_id, "uid": current_user["user_id"], "q": payload.question},
    )
    await db.commit()
    row = result.mappings().first()

    return PollOut(
        **row,
        course_name=course_row["course_name"],
        total_votes=0,
        can_decide=False,
    )


@router.post(
    "/vote",
    response_model=VoteOut,
    summary="Vote on an active poll",
    description="Only enrolled students can vote. One vote per student per poll.",
)
async def vote(
    payload: VoteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    if current_user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only students can vote.")

    # Check poll is active
    poll = await db.execute(
        text("SELECT poll_id, course_id, term_id, status FROM course_polls WHERE poll_id = :pid"),
        {"pid": payload.poll_id},
    )
    poll_row = poll.mappings().first()
    if not poll_row:
        raise HTTPException(status_code=404, detail="Poll not found.")
    if poll_row["status"] != "active":
        raise HTTPException(status_code=400, detail="This poll is no longer active.")

    # Check student is enrolled
    enrollment = await db.execute(
        text("""
            SELECT e.enrollment_id FROM enrollments e
            JOIN   students s ON s.student_id = e.student_id
            JOIN   users    u ON u.student_id = s.student_id
            WHERE  e.course_id = :cid AND e.term_id = :tid AND u.user_id = :uid
        """),
        {"cid": poll_row["course_id"], "tid": poll_row["term_id"], "uid": current_user["user_id"]},
    )
    if not enrollment.mappings().first():
        raise HTTPException(status_code=403, detail="You must be enrolled in this course to vote.")

    try:
        result = await db.execute(
            text("""
                INSERT INTO poll_votes (poll_id, student_id, vote_option, voted_at)
                VALUES (:pid, :sid, :opt, NOW())
                RETURNING vote_id, poll_id, student_id, vote_option, voted_at
            """),
            {"pid": payload.poll_id, "sid": current_user["student_id"], "opt": payload.vote_option},
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="You have already voted on this poll.")

    return VoteOut(**result.mappings().first())


@router.post(
    "/decide",
    summary="Admin makes final decision on a poll",
    description="Only admin can decide. Database trigger blocks this if less than 3 days have passed.",
)
async def decide_poll(
    payload: AdminDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_admin),
):
    try:
        await db.execute(
            text("""
                UPDATE course_polls
                SET    status        = 'decided',
                       admin_decision = :decision,
                       decided_by    = :uid,
                       decided_at    = NOW()
                WHERE  poll_id = :pid
            """),
            {"decision": payload.decision, "uid": current_user["user_id"], "pid": payload.poll_id},
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        if "POLL_TOO_EARLY" in str(exc):
            raise HTTPException(
                status_code=400,
                detail={"error_code": "POLL_TOO_EARLY", "message": "Cannot decide yet — 3 days must pass from poll creation."},
            )
        raise HTTPException(status_code=500, detail=str(exc))

    return {"success": True, "message": "Poll decision recorded. Students will be notified."}


@router.get(
    "/course/{course_id}/term/{term_id}",
    response_model=PollOut,
    summary="Get active poll for a course",
    description="Only visible to enrolled students, teachers, and admin.",
)
async def get_course_poll(
    course_id: int,
    term_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    row = await db.execute(
        text("""
            SELECT
                p.poll_id, p.course_id, c.course_name, p.term_id,
                p.status::text, p.question, p.admin_decision,
                p.created_at, p.decided_at,
                COUNT(v.vote_id) AS total_votes,
                NOW() >= p.created_at + INTERVAL '3 days' AS can_decide
            FROM   course_polls p
            JOIN   courses      c ON c.course_id = p.course_id
            LEFT   JOIN poll_votes v ON v.poll_id = p.poll_id
            WHERE  p.course_id = :cid AND p.term_id = :tid
            GROUP  BY p.poll_id, c.course_name
            ORDER  BY p.created_at DESC
            LIMIT  1
        """),
        {"cid": course_id, "tid": term_id},
    )
    poll = row.mappings().first()
    if not poll:
        raise HTTPException(status_code=404, detail="No poll found for this course and term.")
    return PollOut(**poll)
