-- ============================================================
-- ROGUE UNIVERSITY PORTAL — 01_schema.sql
-- PostgreSQL 15+  |  Run before 02_seed.sql
-- ============================================================

-- ────────────────────────────────────────────────────────────
-- ENUMS
-- ────────────────────────────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE course_category AS ENUM ('Core', 'Elective');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE dept_name AS ENUM ('Fees', 'Documents', 'Medical', 'Hostel', 'Courses');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE dept_status AS ENUM ('Pending', 'Approved', 'Disapproved');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ────────────────────────────────────────────────────────────
-- 1. STUDENTS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS students (
    student_id   SERIAL PRIMARY KEY,
    name         VARCHAR(100)  NOT NULL,
    email        VARCHAR(150)  NOT NULL UNIQUE,
    program      VARCHAR(100)  NOT NULL,
    year         SMALLINT      NOT NULL CHECK (year BETWEEN 1 AND 5),
    created_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────
-- 2. ACADEMIC RECORDS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS academic_records (
    record_id    SERIAL PRIMARY KEY,
    student_id   INT           NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    level        VARCHAR(10)   NOT NULL CHECK (level IN ('10th','12th')),
    board        VARCHAR(50)   NOT NULL,
    percentage   NUMERIC(5,2)  NOT NULL CHECK (percentage BETWEEN 0 AND 100),
    recorded_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────
-- 3. TERMS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS terms (
    term_id      SERIAL PRIMARY KEY,
    term_name    VARCHAR(50)   NOT NULL,
    start_date   DATE          NOT NULL,
    end_date     DATE          NOT NULL,
    is_active    BOOLEAN       NOT NULL DEFAULT FALSE,
    CHECK (end_date > start_date)
);

-- ────────────────────────────────────────────────────────────
-- 4. COURSES
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS courses (
    course_id    SERIAL PRIMARY KEY,
    course_code  VARCHAR(20)   NOT NULL UNIQUE,
    course_name  VARCHAR(150)  NOT NULL,
    credits      SMALLINT      NOT NULL CHECK (credits > 0),
    category     course_category NOT NULL
);

-- ────────────────────────────────────────────────────────────
-- 5. SCHEDULES
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schedules (
    schedule_id  SERIAL PRIMARY KEY,
    course_id    INT           NOT NULL REFERENCES courses(course_id) ON DELETE CASCADE,
    day          VARCHAR(10)   NOT NULL
                     CHECK (day IN ('Monday','Tuesday','Wednesday',
                                    'Thursday','Friday','Saturday','Sunday')),
    start_time   TIME          NOT NULL,
    end_time     TIME          NOT NULL,
    CHECK (end_time > start_time)
);

CREATE INDEX IF NOT EXISTS idx_schedules_course ON schedules(course_id);

-- ────────────────────────────────────────────────────────────
-- 6. ENROLLMENTS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS enrollments (
    enrollment_id SERIAL PRIMARY KEY,
    student_id    INT           NOT NULL REFERENCES students(student_id)  ON DELETE CASCADE,
    course_id     INT           NOT NULL REFERENCES courses(course_id)    ON DELETE CASCADE,
    term_id       INT           NOT NULL REFERENCES terms(term_id)        ON DELETE CASCADE,
    enrolled_at   TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    UNIQUE (student_id, course_id, term_id)
);

-- ────────────────────────────────────────────────────────────
-- TRIGGER: block enrollment if time overlaps an existing course
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION check_schedule_overlap()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    conflict_count INT;
BEGIN
    SELECT COUNT(*) INTO conflict_count
    FROM   enrollments   e
    JOIN   schedules     s_existing ON s_existing.course_id = e.course_id
    JOIN   schedules     s_new      ON s_new.course_id      = NEW.course_id
    WHERE  e.student_id = NEW.student_id
    AND    e.term_id    = NEW.term_id
    AND    s_existing.day = s_new.day
    AND    (s_existing.start_time, s_existing.end_time)
            OVERLAPS
           (s_new.start_time, s_new.end_time);

    IF conflict_count > 0 THEN
        RAISE EXCEPTION 'SCHEDULE_CONFLICT: The new course overlaps with an already-enrolled course on the same day.';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enrollment_overlap ON enrollments;
CREATE TRIGGER trg_enrollment_overlap
BEFORE INSERT ON enrollments
FOR EACH ROW EXECUTE FUNCTION check_schedule_overlap();

-- ────────────────────────────────────────────────────────────
-- TRIGGER: block enrollment if not all 5 departments approved
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION check_verification_complete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    approved_count INT;
BEGIN
    SELECT COUNT(*) INTO approved_count
    FROM   verification_status
    WHERE  student_id = NEW.student_id
    AND    term_id    = NEW.term_id
    AND    status     = 'Approved';

    IF approved_count < 5 THEN
        RAISE EXCEPTION 'VERIFICATION_INCOMPLETE: Student has % / 5 department approvals. All 5 required before enrollment.', approved_count;
    END IF;
    RETURN NEW;
END;
$$;

-- ────────────────────────────────────────────────────────────
-- 7. VERIFICATION STATUS
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS verification_status (
    verification_id   SERIAL PRIMARY KEY,
    student_id        INT             NOT NULL REFERENCES students(student_id) ON DELETE CASCADE,
    term_id           INT             NOT NULL REFERENCES terms(term_id)       ON DELETE CASCADE,
    department        dept_name       NOT NULL,
    status            dept_status     NOT NULL DEFAULT 'Pending',
    hostel_preference TEXT,
    rejection_reason  TEXT,
    reviewed_by       VARCHAR(100),
    reviewed_at       TIMESTAMPTZ,
    UNIQUE (student_id, term_id, department)
);

-- ────────────────────────────────────────────────────────────
-- TRIGGER: once Approved, status cannot revert
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION lock_approved_status()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.status = 'Approved' AND NEW.status <> 'Approved' THEN
        RAISE EXCEPTION 'APPROVAL_LOCKED: Department "%" is already Approved and cannot be changed.', OLD.department;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_lock_approved ON verification_status;
CREATE TRIGGER trg_lock_approved
BEFORE UPDATE OF status ON verification_status
FOR EACH ROW EXECUTE FUNCTION lock_approved_status();

-- Now safe to attach the enrollment gate (verification_status exists)
DROP TRIGGER IF EXISTS trg_enrollment_gate ON enrollments;
CREATE TRIGGER trg_enrollment_gate
BEFORE INSERT ON enrollments
FOR EACH ROW EXECUTE FUNCTION check_verification_complete();

-- ────────────────────────────────────────────────────────────
-- 8. TRANSCRIPTS (archive on term reset)
-- ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transcripts (
    transcript_id   SERIAL PRIMARY KEY,
    student_id      INT             NOT NULL REFERENCES students(student_id),
    course_id       INT             NOT NULL REFERENCES courses(course_id),
    term_id         INT             NOT NULL REFERENCES terms(term_id),
    grade           VARCHAR(5),
    grade_points    NUMERIC(3,2),
    archived_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ────────────────────────────────────────────────────────────
-- 9. TERM RESET PROCEDURE
-- ────────────────────────────────────────────────────────────
CREATE OR REPLACE PROCEDURE reset_term(p_term_id INT)
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO transcripts (student_id, course_id, term_id, archived_at)
    SELECT student_id, course_id, term_id, NOW()
    FROM   enrollments WHERE term_id = p_term_id;

    DELETE FROM enrollments WHERE term_id = p_term_id;

    UPDATE verification_status
    SET    status = 'Pending', rejection_reason = NULL,
           reviewed_by = NULL, reviewed_at = NULL
    WHERE  term_id = p_term_id;

    RAISE NOTICE 'Term % archived and reset.', p_term_id;
END;
$$;
