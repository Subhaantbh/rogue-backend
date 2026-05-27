# schemas/schemas.py
from __future__ import annotations
from datetime import time, datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr


# ── Student ───────────────────────────────────────────────────
class AcademicRecord(BaseModel):
    level: str
    board: str
    percentage: float

    model_config = {"from_attributes": True}


class StudentBase(BaseModel):
    student_id: int
    name: str
    email: str
    program: str
    year: int

    model_config = {"from_attributes": True}


# ── Schedule / Course ─────────────────────────────────────────
class ScheduleOut(BaseModel):
    schedule_id: int
    day: str
    start_time: time
    end_time: time

    model_config = {"from_attributes": True}


class CourseOut(BaseModel):
    course_id: int
    course_code: str
    course_name: str
    credits: int
    category: str
    schedules: List[ScheduleOut] = []

    model_config = {"from_attributes": True}


# ── Verification ──────────────────────────────────────────────
class VerificationOut(BaseModel):
    verification_id: int
    department: str
    status: str
    hostel_preference: Optional[str] = None
    rejection_reason: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class VerificationPatch(BaseModel):
    status: str                          # 'Approved' | 'Disapproved' | 'Pending'
    rejection_reason: Optional[str] = None
    reviewed_by: Optional[str] = None


# ── Dashboard (composite) ─────────────────────────────────────
class DashboardResponse(BaseModel):
    student: StudentBase
    academic_records: List[AcademicRecord]
    enrolled_courses: List[CourseOut]
    verification: List[VerificationOut]
    term_id: int
    term_name: str


# ── Enrollment ────────────────────────────────────────────────
class EnrollRequest(BaseModel):
    student_email: EmailStr
    course_code: str
    term_id: int


class EnrollResponse(BaseModel):
    success: bool
    message: str
    enrollment_id: Optional[int] = None


# ── Generic ───────────────────────────────────────────────────
class ErrorResponse(BaseModel):
    success: bool = False
    error_code: str
    message: str
