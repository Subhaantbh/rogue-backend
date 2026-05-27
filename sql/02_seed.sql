-- ============================================================
-- ROGUE UNIVERSITY PORTAL — 02_seed.sql
-- Run AFTER 01_schema.sql
-- ============================================================
BEGIN;

-- ── TERM ─────────────────────────────────────────────────────
INSERT INTO terms (term_name, start_date, end_date, is_active)
VALUES ('Semester 1 – 2025', '2025-08-01', '2025-12-15', TRUE)
ON CONFLICT DO NOTHING;

-- ── STUDENTS ─────────────────────────────────────────────────
INSERT INTO students (name, email, program, year) VALUES
    ('Subhaan',  'subhaan.hai@vijaybhoomi.edu.in', 'B.Tech CSE', 1),
    ('Aadarsh',  'aadarsh@vijaybhoomi.edu.in',     'B.Tech CSE', 1),
    ('Yash',     'yash@vijaybhoomi.edu.in',         'B.Tech CSE', 1),
    ('Rebecca',  'rebecca@vijaybhoomi.edu.in',      'B.Tech CSE', 1)
ON CONFLICT (email) DO NOTHING;

-- ── ACADEMIC RECORDS (Subhaan only) ──────────────────────────
INSERT INTO academic_records (student_id, level, board, percentage)
SELECT student_id, '10th', 'IGCSE', 70.00
FROM   students WHERE email = 'subhaan.hai@vijaybhoomi.edu.in'
ON CONFLICT DO NOTHING;

INSERT INTO academic_records (student_id, level, board, percentage)
SELECT student_id, '12th', 'IB', 47.00
FROM   students WHERE email = 'subhaan.hai@vijaybhoomi.edu.in'
ON CONFLICT DO NOTHING;

-- ── COURSES ──────────────────────────────────────────────────
INSERT INTO courses (course_code, course_name, credits, category) VALUES
    ('CS101', 'Introduction to Programming',       4, 'Core'),
    ('HU201', 'Creative Writing & Communication',  3, 'Elective'),
    ('MA101', 'Calculus I',                        4, 'Core'),
    ('CS102', 'Digital Logic Design',              3, 'Core'),
    ('HU202', 'Critical Thinking & Ethics',        2, 'Elective')
ON CONFLICT (course_code) DO NOTHING;

-- ── SCHEDULES ────────────────────────────────────────────────
-- CS101: Monday 11:00–12:30  (will CONFLICT with HU201)
INSERT INTO schedules (course_id, day, start_time, end_time)
SELECT course_id, 'Monday', '11:00', '12:30' FROM courses WHERE course_code = 'CS101'
ON CONFLICT DO NOTHING;

-- HU201: Monday 11:30–13:00  ← OVERLAPS CS101 by 1 hour
INSERT INTO schedules (course_id, day, start_time, end_time)
SELECT course_id, 'Monday', '11:30', '13:00' FROM courses WHERE course_code = 'HU201'
ON CONFLICT DO NOTHING;

-- MA101: Tuesday 09:00–10:30  (no conflicts)
INSERT INTO schedules (course_id, day, start_time, end_time)
SELECT course_id, 'Tuesday', '09:00', '10:30' FROM courses WHERE course_code = 'MA101'
ON CONFLICT DO NOTHING;

-- CS102: Wednesday 14:00–15:30
INSERT INTO schedules (course_id, day, start_time, end_time)
SELECT course_id, 'Wednesday', '14:00', '15:30' FROM courses WHERE course_code = 'CS102'
ON CONFLICT DO NOTHING;

-- HU202: Thursday 10:00–11:00
INSERT INTO schedules (course_id, day, start_time, end_time)
SELECT course_id, 'Thursday', '10:00', '11:00' FROM courses WHERE course_code = 'HU202'
ON CONFLICT DO NOTHING;

-- ── VERIFICATION STATUS — all 4 students, all 5 depts ────────
DO $$
DECLARE
    v_sid   INT;
    v_email TEXT;
    v_dept  dept_name;
    v_emails TEXT[] := ARRAY[
        'subhaan.hai@vijaybhoomi.edu.in',
        'aadarsh@vijaybhoomi.edu.in',
        'yash@vijaybhoomi.edu.in',
        'rebecca@vijaybhoomi.edu.in'
    ];
BEGIN
    FOREACH v_email IN ARRAY v_emails LOOP
        SELECT student_id INTO v_sid FROM students WHERE email = v_email;
        FOREACH v_dept IN ARRAY ARRAY[
            'Fees'::dept_name, 'Documents'::dept_name,
            'Medical'::dept_name, 'Hostel'::dept_name, 'Courses'::dept_name
        ] LOOP
            INSERT INTO verification_status (student_id, term_id, department, status)
            VALUES (v_sid, 1, v_dept, 'Pending')
            ON CONFLICT (student_id, term_id, department) DO NOTHING;
        END LOOP;
    END LOOP;
END;
$$;

-- ── HOSTEL TEST — Subhaan's preference ───────────────────────
UPDATE verification_status
SET    hostel_preference = 'Block C, Room 302'
WHERE  student_id = (SELECT student_id FROM students WHERE email = 'subhaan.hai@vijaybhoomi.edu.in')
AND    term_id    = 1
AND    department = 'Hostel';

COMMIT;
