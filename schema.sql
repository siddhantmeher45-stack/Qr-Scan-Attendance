-- ==========================================================
-- QR-BASED COLLEGE ATTENDANCE MANAGEMENT SYSTEM SCHEMA
-- Class: Fourth Year B.E. ECS, Div: A, Sem: VII (2026-2027)
-- ==========================================================

DROP TABLE IF EXISTS attendance_records;
DROP TABLE IF EXISTS attendance_sessions;
DROP TABLE IF EXISTS timetable;
DROP TABLE IF EXISTS subjects;
DROP TABLE IF EXISTS teachers;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS notifications;

-- 1. STUDENTS TABLE
CREATE TABLE students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pid TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT 'ECS',
    course TEXT NOT NULL DEFAULT 'Electronics & Computer Science',
    year TEXT NOT NULL DEFAULT 'Fourth Year',
    division TEXT NOT NULL DEFAULT 'A',
    roll_number TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. TEACHERS TABLE
CREATE TABLE teachers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    teacher_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT 'ECS',
    subjects TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. SUBJECTS TABLE
CREATE TABLE subjects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    teacher_code TEXT NOT NULL,
    teacher_name TEXT NOT NULL
);

-- 4. TIMETABLE TABLE
CREATE TABLE timetable (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    start_24 TEXT NOT NULL,
    end_24 TEXT NOT NULL,
    subject TEXT NOT NULL,
    subject_code TEXT NOT NULL,
    teacher_name TEXT NOT NULL,
    teacher_code TEXT NOT NULL,
    class_name TEXT NOT NULL DEFAULT 'Fourth Year B.E. ECS',
    division TEXT NOT NULL DEFAULT 'A',
    room TEXT NOT NULL,
    batch TEXT NOT NULL DEFAULT 'All'
);

-- 5. ATTENDANCE SESSIONS TABLE
CREATE TABLE attendance_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_token TEXT UNIQUE NOT NULL,
    teacher_id TEXT NOT NULL,
    teacher_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    subject_code TEXT NOT NULL,
    class_name TEXT NOT NULL,
    division TEXT NOT NULL,
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    status TEXT NOT NULL DEFAULT 'active', -- 'active', 'closed', 'expired'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 6. ATTENDANCE RECORDS TABLE
CREATE TABLE attendance_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    session_token TEXT NOT NULL,
    pid TEXT NOT NULL,
    student_name TEXT NOT NULL,
    roll_number TEXT NOT NULL,
    department TEXT NOT NULL,
    year TEXT NOT NULL,
    division TEXT NOT NULL,
    subject TEXT NOT NULL,
    teacher_name TEXT NOT NULL,
    date TEXT NOT NULL,
    day TEXT NOT NULL,
    lecture_time TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'Present',
    FOREIGN KEY (session_id) REFERENCES attendance_sessions(id),
    UNIQUE (session_id, pid) -- Duplicate prevention per session
);

-- 7. NOTIFICATIONS TABLE
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_role TEXT NOT NULL DEFAULT 'all', -- 'all', 'student', 'teacher'
    target_id TEXT,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'info', -- 'info', 'success', 'warning'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================================
-- SEED DATA
-- ==========================================================

-- Subjects & Faculty Mapping
INSERT INTO subjects (code, name, teacher_code, teacher_name) VALUES
('PLCA', 'Programmable Logic Controllers & Automation', 'VR', 'Mrs. Vishakha Rane'),
('DL', 'Deep Learning', 'SK', 'Mrs. Shilpa Katre'),
('ND', 'Network Design', 'PG', 'Dr. Pandharinath Ghonge'),
('DICD', 'Digital Integrated Circuit Design', 'MI', 'Dr. Md. Imaduddin'),
('BCD', 'Blockchain & Distributed Ledger', 'AC', 'Ms. Aishwarya Churi');

-- Teachers
INSERT INTO teachers (teacher_id, name, email, password, department, subjects) VALUES
('T_VR', 'Mrs. Vishakha Rane', 'vr@college.edu', 'teacher123', 'ECS', 'PLCA'),
('T_SK', 'Mrs. Shilpa Katre', 'sk@college.edu', 'teacher123', 'ECS', 'DL'),
('T_PG', 'Dr. Pandharinath Ghonge', 'pg@college.edu', 'teacher123', 'ECS', 'ND'),
('T_MI', 'Dr. Md. Imaduddin', 'mi@college.edu', 'teacher123', 'ECS', 'DICD'),
('T_AC', 'Ms. Aishwarya Churi', 'ac@college.edu', 'teacher123', 'ECS', 'BCD');

-- Students table starts empty (students register via /register?role=student)
-- Official Timetable (Fourth Year B.E. ECS, Semester VII, Division A, 2026-2027)
-- MONDAY
INSERT INTO timetable (day, start_time, end_time, start_24, end_24, subject, subject_code, teacher_name, teacher_code, room, batch) VALUES
('Monday', '10:00 AM', '11:00 AM', '10:00', '11:00', 'PLCA', 'PLCA', 'Mrs. Vishakha Rane', 'VR', '206', 'All'),
('Monday', '11:00 AM', '12:00 PM', '11:00', '12:00', 'Mentoring', 'MENT', 'Faculty Mentor', 'MENT', '206', 'All'),
('Monday', '12:00 PM', '01:00 PM', '12:00', '13:00', 'BCD', 'BCD', 'Ms. Aishwarya Churi', 'AC', '206', 'All'),
('Monday', '01:00 PM', '02:00 PM', '13:00', '14:00', 'Lunch Break', 'BREAK', 'Faculty', 'BREAK', '-', 'All'),
('Monday', '02:00 PM', '04:00 PM', '14:00', '16:00', 'PLCA Lab (B1) / BCD Lab (B2)', 'LAB', 'Mrs. Vishakha Rane / Ms. Aishwarya Churi', 'VR/AC', 'Wireless / SSL1', 'B1/B2'),
('Monday', '04:00 PM', '05:00 PM', '16:00', '17:00', 'Research / Library', 'LIB', 'Library Staff', 'LIB', 'Library', 'All');

-- TUESDAY
INSERT INTO timetable (day, start_time, end_time, start_24, end_24, subject, subject_code, teacher_name, teacher_code, room, batch) VALUES
('Tuesday', '10:00 AM', '11:00 AM', '10:00', '11:00', 'BCD', 'BCD', 'Ms. Aishwarya Churi', 'AC', '206', 'All'),
('Tuesday', '11:00 AM', '12:00 PM', '11:00', '12:00', 'DL', 'DL', 'Mrs. Shilpa Katre', 'SK', '206', 'All'),
('Tuesday', '12:00 PM', '01:00 PM', '12:00', '13:00', 'PLCA', 'PLCA', 'Mrs. Vishakha Rane', 'VR', '206 SL', 'All'),
('Tuesday', '01:00 PM', '02:00 PM', '13:00', '14:00', 'Lunch Break', 'BREAK', 'Faculty', 'BREAK', '-', 'All'),
('Tuesday', '02:00 PM', '03:00 PM', '14:00', '15:00', 'Capstone Project', 'CAP', 'Project Guide', 'GUIDE', 'Project Lab', 'All'),
('Tuesday', '03:00 PM', '05:00 PM', '15:00', '17:00', 'EEP', 'EEP', 'EEP Faculty', 'EEP', '206', 'All');

-- WEDNESDAY
INSERT INTO timetable (day, start_time, end_time, start_24, end_24, subject, subject_code, teacher_name, teacher_code, room, batch) VALUES
('Wednesday', '10:00 AM', '11:00 AM', '10:00', '11:00', 'ND / DICD', 'ND/DICD', 'Dr. Pandharinath Ghonge / Dr. Md. Imaduddin', 'PG/MI', 'SSL1 / Embedded', 'All'),
('Wednesday', '11:00 AM', '12:00 PM', '11:00', '12:00', 'Library', 'LIB', 'Library Incharge', 'LIB', 'Library', 'All'),
('Wednesday', '12:00 PM', '01:00 PM', '12:00', '13:00', 'DL', 'DL', 'Mrs. Shilpa Katre', 'SK', '206', 'All'),
('Wednesday', '01:00 PM', '02:00 PM', '13:00', '14:00', 'Lunch Break', 'BREAK', 'Faculty', 'BREAK', '-', 'All'),
('Wednesday', '02:00 PM', '03:00 PM', '14:00', '15:00', 'BCD Lab (B1) / PLCA Lab (B2)', 'LAB', 'Ms. Aishwarya Churi / Mrs. Vishakha Rane', 'AC/VR', 'SSL1 / Wireless', 'B1/B2'),
('Wednesday', '03:00 PM', '04:00 PM', '15:00', '16:00', 'Capstone Project', 'CAP', 'Project Guide', 'GUIDE', '206', 'All'),
('Wednesday', '04:00 PM', '05:00 PM', '16:00', '17:00', 'Capstone Project', 'CAP', 'Project Guide', 'GUIDE', '206', 'All');

-- THURSDAY
INSERT INTO timetable (day, start_time, end_time, start_24, end_24, subject, subject_code, teacher_name, teacher_code, room, batch) VALUES
('Thursday', '10:00 AM', '11:00 AM', '10:00', '11:00', 'BCD', 'BCD', 'Ms. Aishwarya Churi', 'AC', '206', 'All'),
('Thursday', '11:00 AM', '12:00 PM', '11:00', '12:00', 'PLCA', 'PLCA', 'Mrs. Vishakha Rane', 'VR', '206', 'All'),
('Thursday', '12:00 PM', '01:00 PM', '12:00', '13:00', 'DL', 'DL', 'Mrs. Shilpa Katre', 'SK', '206', 'All'),
('Thursday', '01:00 PM', '02:00 PM', '13:00', '14:00', 'Lunch Break', 'BREAK', 'Faculty', 'BREAK', '-', 'All'),
('Thursday', '02:00 PM', '04:00 PM', '14:00', '16:00', 'Capstone Project', 'CAP', 'Project Guide', 'GUIDE', 'Project Lab', 'All');

-- FRIDAY
INSERT INTO timetable (day, start_time, end_time, start_24, end_24, subject, subject_code, teacher_name, teacher_code, room, batch) VALUES
('Friday', '10:00 AM', '01:00 PM', '10:00', '13:00', 'OE (Open Elective)', 'OE', 'OE Faculty', 'OE', 'Central Hall', 'All'),
('Friday', '01:00 PM', '02:00 PM', '13:00', '14:00', 'Lunch Break', 'BREAK', 'Faculty', 'BREAK', '-', 'All'),
('Friday', '02:00 PM', '03:00 PM', '14:00', '15:00', 'DL', 'DL', 'Mrs. Shilpa Katre', 'SK', '207', 'All'),
('Friday', '03:00 PM', '04:00 PM', '15:00', '16:00', 'PLCA', 'PLCA', 'Mrs. Vishakha Rane', 'VR', '207', 'All'),
('Friday', '04:00 PM', '05:00 PM', '16:00', '17:00', 'BCD', 'BCD', 'Ms. Aishwarya Churi', 'AC', '207 SL', 'All');

-- Sample Initial Notifications
INSERT INTO notifications (target_role, title, message, type) VALUES
('all', 'QR Attendance System Live', 'Welcome to the new QR-Code based Attendance Management System. Face detection has been decommissioned.', 'info'),
('student', 'Personal ID (PID) Verification', 'Ensure you view or download your permanent Student QR from the dashboard for profile verification.', 'info'),
('teacher', 'Timetable Synchronized', 'Fourth Year B.E. ECS Division A timetable for 2026-2027 is now actively mapped to all lecture attendance sessions.', 'success');
