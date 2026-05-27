# routers/verification.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime, timezone

from db.database import get_db
from schemas.schemas import VerificationOut, VerificationPatch

router = APIRouter()

VALID_STATUSES = {"Pending", "Approved", "Disapproved"}


@router.get(
    "/{status_id}",
    response_model=VerificationOut,
    summary="Get a single verification record",
)
async def get_verification(status_id: int, db: AsyncSession = Depends(get_db)):
    row = await db.execute(
        text("""
            SELECT verification_id, department::text, status::text,
                   hostel_preference, rejection_reason, reviewed_by, reviewed_at
            FROM   verification_status WHERE verification_id = :id
        """),
        {"id": status_id},
    )
    record = row.mappings().first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Verification record {status_id} not found.")
    return VerificationOut(**record)


@router.patch(
    "/{status_id}",
    response_model=VerificationOut,
    summary="Update department verification status",
    description=(
        "Changes the status of a department verification row. "
        "The database trigger (trg_lock_approved) enforces the rule: "
        "once 'Approved', the status CANNOT be changed. "
        "An additional API-layer guard returns a 409 before hitting the DB."
    ),
)
async def patch_verification(
    status_id: int,
    payload: VerificationPatch,
    db: AsyncSession = Depends(get_db),
):
    if payload.status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status '{payload.status}'. Must be one of {sorted(VALID_STATUSES)}.",
        )

    # ── Read current record ──────────────────────────────────
    row = await db.execute(
        text("""
            SELECT verification_id, department::text, status::text,
                   hostel_preference, rejection_reason, reviewed_by, reviewed_at
            FROM   verification_status WHERE verification_id = :id
        """),
        {"id": status_id},
    )
    record = row.mappings().first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Verification record {status_id} not found.")

    # ── API-layer approval lock ──────────────────────────────
    if record["status"] == "Approved" and payload.status != "Approved":
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "APPROVAL_LOCKED",
                "message": (
                    f"Department '{record['department']}' is already Approved. "
                    "Approved statuses are permanent and cannot be revoked."
                ),
            },
        )

    # ── Disapproved requires a reason ───────────────────────
    if payload.status == "Disapproved" and not payload.rejection_reason:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "REASON_REQUIRED", "message": "A rejection_reason is required when disapproving."},
        )

    # ── Update ───────────────────────────────────────────────
    try:
        updated = await db.execute(
            text("""
                UPDATE verification_status
                SET    status           = :status,
                       rejection_reason = :reason,
                       reviewed_by      = :reviewer,
                       reviewed_at      = :reviewed_at
                WHERE  verification_id  = :id
                RETURNING
                    verification_id, department::text, status::text,
                    hostel_preference, rejection_reason, reviewed_by, reviewed_at
            """),
            {
                "status":      payload.status,
                "reason":      payload.rejection_reason,
                "reviewer":    payload.reviewed_by,
                "reviewed_at": datetime.now(timezone.utc),
                "id":          status_id,
            },
        )
        updated_record = updated.mappings().first()
        await db.commit()
    except Exception as exc:
        await db.rollback()
        msg = str(exc)
        if "APPROVAL_LOCKED" in msg:
            raise HTTPException(
                status_code=409,
                detail={"error_code": "APPROVAL_LOCKED", "message": "Database trigger: Approved status cannot be revoked."},
            )
        raise HTTPException(status_code=500, detail={"error_code": "DB_ERROR", "message": msg})

    return VerificationOut(**updated_record)


@router.get(
    "/student/{student_id}/term/{term_id}",
    response_model=list[VerificationOut],
    summary="All verification rows for a student in a term",
)
async def get_student_verification(
    student_id: int, term_id: int, db: AsyncSession = Depends(get_db)
):
    rows = await db.execute(
        text("""
            SELECT verification_id, department::text, status::text,
                   hostel_preference, rejection_reason, reviewed_by, reviewed_at
            FROM   verification_status
            WHERE  student_id = :sid AND term_id = :tid
            ORDER  BY department
        """),
        {"sid": student_id, "tid": term_id},
    )
    return [VerificationOut(**r) for r in rows.mappings()]
