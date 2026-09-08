import sqlite3
import datetime
import uuid

DB_NAME = 'attendance.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    with open('schema.sql', 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

def seed_historical_attendance(conn):
    # No fake data: real attendance records only
    pass

# ----------------- STUDENT OPERATIONS -----------------

def get_student_by_pid(pid):
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM students WHERE pid = ?', (pid,)).fetchone()
    conn.close()
    return student

def get_student_by_id(student_id):
    conn = get_db_connection()
    student = conn.execute('SELECT * FROM students WHERE id = ?', (student_id,)).fetchone()
    conn.close()
    return student

def get_student_by_email_or_pid(identifier):
    conn = get_db_connection()
    student = conn.execute(
        'SELECT * FROM students WHERE email = ? OR pid = ? OR roll_number = ?',
        (identifier, identifier, identifier)
    ).fetchone()
    conn.close()
    return student

def get_all_students(class_name='Fourth Year B.E. ECS', division='A'):
    conn = get_db_connection()
    students = conn.execute(
        'SELECT * FROM students WHERE class_name = ? AND division = ? ORDER BY roll_number ASC',
        (class_name, division)
    ).fetchall() if 'class_name' in [col[1] for col in conn.execute('PRAGMA table_info(students)').fetchall()] else \
    conn.execute('SELECT * FROM students WHERE division = ? ORDER BY roll_number ASC', (division,)).fetchall()
    conn.close()
    return students

def register_student(pid, name, email, password, department, course, year, division, roll_number):
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO students (pid, name, email, password, department, course, year, division, roll_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (pid.strip().upper(), name.strip(), email.strip().lower(), password, department.strip(), 
              course.strip(), year.strip(), division.strip().upper(), roll_number.strip()))
        conn.commit()
        return True, "Student registered successfully"
    except sqlite3.IntegrityError as e:
        err_msg = str(e)
        if "students.pid" in err_msg or "UNIQUE constraint failed: students.pid" in err_msg:
            return False, f"Personal ID (PID) '{pid}' already registered."
        elif "students.email" in err_msg:
            return False, f"Email address '{email}' is already registered."
        elif "students.roll_number" in err_msg:
            return False, f"Roll number '{roll_number}' is already registered."
        return False, f"Database constraint violation: {err_msg}"
    except Exception as e:
        return False, f"Registration error: {str(e)}"
    finally:
        conn.close()

# ----------------- TEACHER OPERATIONS -----------------

def get_teacher_by_id(teacher_id):
    conn = get_db_connection()
    teacher = conn.execute('SELECT * FROM teachers WHERE teacher_id = ?', (teacher_id,)).fetchone()
    conn.close()
    return teacher

def get_teacher_by_email_or_id(identifier):
    conn = get_db_connection()
    teacher = conn.execute(
        'SELECT * FROM teachers WHERE email = ? OR teacher_id = ?',
        (identifier, identifier)
    ).fetchone()
    conn.close()
    return teacher

def get_all_teachers():
    conn = get_db_connection()
    teachers = conn.execute('SELECT * FROM teachers ORDER BY name ASC').fetchall()
    conn.close()
    return teachers

def register_teacher(teacher_id, name, email, password, department, subjects):
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT INTO teachers (teacher_id, name, email, password, department, subjects)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (teacher_id.strip().upper(), name.strip(), email.strip().lower(), password, department.strip(), subjects.strip()))
        conn.commit()
        return True, "Teacher registered successfully"
    except sqlite3.IntegrityError as e:
        err_msg = str(e)
        if "teachers.teacher_id" in err_msg:
            return False, f"Teacher ID '{teacher_id}' already registered."
        elif "teachers.email" in err_msg:
            return False, f"Email '{email}' is already registered."
        return False, f"Constraint violation: {err_msg}"
    except Exception as e:
        return False, f"Registration error: {str(e)}"
    finally:
        conn.close()

# ----------------- TIMETABLE & LECTURE RESOLUTION -----------------

def get_full_weekly_timetable():
    conn = get_db_connection()
    timetable = conn.execute('SELECT * FROM timetable ORDER BY id ASC').fetchall()
    conn.close()
    return timetable

def get_timetable_for_day(day_name):
    conn = get_db_connection()
    lectures = conn.execute('SELECT * FROM timetable WHERE LOWER(day) = LOWER(?) ORDER BY id ASC', (day_name,)).fetchall()
    conn.close()
    return lectures

def get_teacher_timetable(teacher_name, day_name=None):
    conn = get_db_connection()
    if day_name:
        lectures = conn.execute(
            'SELECT * FROM timetable WHERE teacher_name LIKE ? AND LOWER(day) = LOWER(?) ORDER BY id ASC',
            (f'%{teacher_name}%', day_name)
        ).fetchall()
    else:
        lectures = conn.execute(
            'SELECT * FROM timetable WHERE teacher_name LIKE ? ORDER BY id ASC',
            (f'%{teacher_name}%',)
        ).fetchall()
    conn.close()
    return lectures

def get_current_active_lecture(now=None):
    """
    Identifies the active lecture based on Current Day + Current 24h Time.
    Also returns next upcoming lecture.
    """
    if now is None:
        now = datetime.datetime.now()
    
    current_day = now.strftime('%A')
    current_time_str = now.strftime('%H:%M')

    conn = get_db_connection()
    today_lectures = conn.execute(
        'SELECT * FROM timetable WHERE LOWER(day) = LOWER(?) ORDER BY id ASC',
        (current_day,)
    ).fetchall()
    conn.close()

    active_lecture = None
    upcoming_lecture = None

    for lec in today_lectures:
        start = lec['start_24']
        end = lec['end_24']
        if start <= current_time_str < end:
            active_lecture = dict(lec)
        elif current_time_str < start and upcoming_lecture is None:
            upcoming_lecture = dict(lec)

    return active_lecture, upcoming_lecture, today_lectures

# ----------------- ATTENDANCE SESSION MANAGEMENT -----------------

def create_attendance_session(teacher_id, teacher_name, subject, subject_code, class_name, division, start_time=None, end_time=None, duration_minutes=15):
    now = datetime.datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    start_time_str = start_time or now.strftime('%I:%M %p')
    
    # Calculate expiry
    expires_at = now + datetime.timedelta(minutes=duration_minutes)
    expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')
    end_time_str = end_time or expires_at.strftime('%I:%M %p')

    # Generate unique secure session token
    session_token = f"ATT-{uuid.uuid4().hex[:12].upper()}"

    conn = get_db_connection()
    cursor = conn.cursor()

    # Close any currently active sessions by this teacher for cleanliness
    cursor.execute('''
        UPDATE attendance_sessions 
        SET status = 'closed' 
        WHERE teacher_id = ? AND status = 'active'
    ''', (teacher_id,))

    cursor.execute('''
        INSERT INTO attendance_sessions 
        (session_token, teacher_id, teacher_name, subject, subject_code, class_name, division, date, start_time, end_time, expires_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    ''', (session_token, teacher_id, teacher_name, subject, subject_code, class_name, division, date_str, start_time_str, end_time_str, expires_at_str))
    
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "id": session_id,
        "session_token": session_token,
        "teacher_id": teacher_id,
        "teacher_name": teacher_name,
        "subject": subject,
        "subject_code": subject_code,
        "class_name": class_name,
        "division": division,
        "date": date_str,
        "start_time": start_time_str,
        "end_time": end_time_str,
        "expires_at": expires_at_str,
        "status": "active"
    }

def get_session_by_token(session_token):
    conn = get_db_connection()
    session_row = conn.execute('SELECT * FROM attendance_sessions WHERE session_token = ?', (session_token,)).fetchone()
    conn.close()
    return session_row

def finalize_attendance_session(session_id_or_token, conn=None):
    """
    Closes an attendance session AND automatically marks all enrolled students
    who did not scan the QR code in time as 'Absent' in attendance_records.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        should_close = True

    cursor = conn.cursor()
    if isinstance(session_id_or_token, int) or (isinstance(session_id_or_token, str) and session_id_or_token.isdigit()):
        session_row = cursor.execute("SELECT * FROM attendance_sessions WHERE id = ?", (int(session_id_or_token),)).fetchone()
    else:
        session_row = cursor.execute("SELECT * FROM attendance_sessions WHERE session_token = ?", (str(session_id_or_token),)).fetchone()

    if not session_row:
        if should_close: conn.close()
        return

    session_id = session_row['id']
    session_token = session_row['session_token']
    division = session_row['division']
    subject = session_row['subject']
    teacher_name = session_row['teacher_name']
    session_date = session_row['date']
    lecture_time = f"{session_row['start_time']} - {session_row['end_time']}"
    expires_at = session_row['expires_at']
    try:
        day_name = datetime.datetime.strptime(session_date, '%Y-%m-%d').strftime('%A')
    except Exception:
        day_name = datetime.datetime.now().strftime('%A')

    # 1. Update session status to closed
    cursor.execute("UPDATE attendance_sessions SET status = 'closed' WHERE id = ?", (session_id,))

    # 2. Get all enrolled students for this division
    enrolled_students = cursor.execute(
        "SELECT * FROM students WHERE UPPER(division) = UPPER(?)",
        (division,)
    ).fetchall()

    # 3. Get students who already marked attendance
    existing_records = cursor.execute(
        "SELECT pid FROM attendance_records WHERE session_id = ?",
        (session_id,)
    ).fetchall()
    marked_pids = {r['pid'] for r in existing_records}

    # 4. Automatically insert Absent record for any student who didn't scan in time
    for s in enrolled_students:
        if s['pid'] not in marked_pids:
            cursor.execute('''
                INSERT OR IGNORE INTO attendance_records 
                (session_id, session_token, pid, student_name, roll_number, department, year, division, subject, teacher_name, date, day, lecture_time, timestamp, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Absent')
            ''', (
                session_id, session_token, s['pid'], s['name'], s['roll_number'],
                s['department'], s['year'], s['division'], subject,
                teacher_name, session_date, day_name, lecture_time,
                expires_at, 'Absent'
            ))

    conn.commit()
    if should_close:
        conn.close()

def close_attendance_session(session_token):
    finalize_attendance_session(session_token)

def finalize_all_expired_sessions():
    """
    Finds all active sessions whose expiration time has passed, marks them closed,
    and automatically marks unscanned students as Absent.
    """
    conn = get_db_connection()
    now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor = conn.cursor()
    expired = cursor.execute(
        "SELECT id FROM attendance_sessions WHERE status = 'active' AND expires_at <= ?",
        (now_str,)
    ).fetchall()
    for row in expired:
        finalize_attendance_session(row['id'], conn=conn)
    conn.close()

def get_latest_session_for_teacher(teacher_id):
    conn = get_db_connection()
    session_row = conn.execute(
        "SELECT * FROM attendance_sessions WHERE teacher_id = ? ORDER BY id DESC LIMIT 1",
        (teacher_id,)
    ).fetchone()
    conn.close()
    return session_row

def get_active_session_for_teacher(teacher_id):
    finalize_all_expired_sessions()
    conn = get_db_connection()
    session_row = conn.execute(
        "SELECT * FROM attendance_sessions WHERE teacher_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
        (teacher_id,)
    ).fetchone()
    conn.close()
    if session_row:
        # Check if expired
        now = datetime.datetime.now()
        expires_at = datetime.datetime.strptime(session_row['expires_at'], '%Y-%m-%d %H:%M:%S')
        if now > expires_at:
            finalize_attendance_session(session_row['id'])
            return None
    return session_row


# ----------------- QR ATTENDANCE VALIDATION & RECORDING -----------------

def mark_qr_attendance(session_token, student_pid):
    """
    Validates and marks attendance for an authenticated student.
    Validation steps:
      1. Authenticated student exists in DB
      2. Session exists
      3. Session is active
      4. Session is not expired
      5. Student class and division match session
      6. Student has not already marked attendance for this session / lecture
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Step 1: Validate Student
    student = cursor.execute('SELECT * FROM students WHERE pid = ?', (student_pid,)).fetchone()
    if not student:
        conn.close()
        return False, "Invalid Student: Student PID not registered in database."

    # Step 2: Validate Session
    session_row = cursor.execute('SELECT * FROM attendance_sessions WHERE session_token = ?', (session_token,)).fetchone()
    if not session_row:
        conn.close()
        return False, "Invalid attendance session: QR code not recognized."

    # Step 3 & 4: Check Session Status and Expiration
    if session_row['status'] != 'active':
        conn.close()
        return False, f"Attendance session is {session_row['status']}. Attendance is closed."

    now = datetime.datetime.now()
    expires_at = datetime.datetime.strptime(session_row['expires_at'], '%Y-%m-%d %H:%M:%S')
    if now > expires_at:
        cursor.execute("UPDATE attendance_sessions SET status = 'expired' WHERE id = ?", (session_row['id'],))
        conn.commit()
        conn.close()
        return False, "Attendance session has expired. Please ask the teacher to refresh the QR code."

    # Step 5: Class and Division Verification
    # Student must belong to same class/division
    if student['division'].upper() != session_row['division'].upper():
        conn.close()
        return False, f"Wrong class/division: Student is in Division {student['division']} but session is for Division {session_row['division']}."

    # Step 6: Duplicate Check
    existing = cursor.execute(
        'SELECT * FROM attendance_records WHERE session_id = ? AND pid = ?',
        (session_row['id'], student['pid'])
    ).fetchone()
    if existing:
        if existing['status'] == 'Present':
            conn.close()
            return False, "Attendance already marked! Duplicate submission prevented."
        # If student was marked Absent by timeout/re-open, allow them to mark Present now:
        day_name = now.strftime('%A')
        timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE attendance_records 
            SET status = 'Present', timestamp = ?
            WHERE session_id = ? AND pid = ?
        ''', (timestamp_str, session_row['id'], student['pid']))
        conn.commit()
        conn.close()
        return True, {
            "record_id": existing['id'],
            "pid": student['pid'],
            "name": student['name'],
            "roll_number": student['roll_number'],
            "subject": session_row['subject'],
            "teacher": session_row['teacher_name'],
            "date": session_row['date'],
            "timestamp": timestamp_str,
            "status": "Present"
        }


    # Step 7: Record Attendance
    day_name = now.strftime('%A')
    timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S')
    lecture_time = f"{session_row['start_time']} - {session_row['end_time']}"

    cursor.execute('''
        INSERT INTO attendance_records 
        (session_id, session_token, pid, student_name, roll_number, department, year, division, subject, teacher_name, date, day, lecture_time, timestamp, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Present')
    ''', (session_row['id'], session_token, student['pid'], student['name'], student['roll_number'],
          student['department'], student['year'], student['division'], session_row['subject'],
          session_row['teacher_name'], session_row['date'], day_name, lecture_time, timestamp_str))
    
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return True, {
        "record_id": record_id,
        "pid": student['pid'],
        "name": student['name'],
        "roll_number": student['roll_number'],
        "subject": session_row['subject'],
        "teacher": session_row['teacher_name'],
        "date": session_row['date'],
        "timestamp": timestamp_str,
        "status": "Present"
    }

# ----------------- LIVE ATTENDANCE & STATS -----------------

def get_session_live_attendance(session_token):
    conn = get_db_connection()
    session_row = conn.execute('SELECT * FROM attendance_sessions WHERE session_token = ?', (session_token,)).fetchone()
    if not session_row:
        conn.close()
        return None

    # Get enrolled students for this division
    enrolled_students = conn.execute(
        'SELECT * FROM students WHERE UPPER(division) = UPPER(?) ORDER BY CAST(roll_number AS INTEGER) ASC, roll_number ASC',
        (session_row['division'],)
    ).fetchall()

    # Get records for this session
    session_records = conn.execute(
        'SELECT * FROM attendance_records WHERE session_id = ? ORDER BY timestamp DESC',
        (session_row['id'],)
    ).fetchall()
    
    conn.close()

    present_pids = {r['pid']: dict(r) for r in session_records if r['status'] == 'Present'}
    present_list = [dict(r) for r in session_records if r['status'] == 'Present']
    
    total_enrolled = len(enrolled_students)
    present_count = len(present_list)
    absent_count = max(0, total_enrolled - present_count)
    attendance_pct = round((present_count / total_enrolled * 100), 1) if total_enrolled > 0 else 0.0

    # Build student roster with status
    roster = []
    for s in enrolled_students:
        is_present = s['pid'] in present_pids
        roster.append({
            "pid": s['pid'],
            "name": s['name'],
            "roll_number": s['roll_number'],
            "department": s['department'],
            "year": s['year'],
            "division": s['division'],
            "status": "Present" if is_present else "Absent",
            "timestamp": present_pids[s['pid']]['timestamp'] if is_present else "-"
        })

    return {
        "session": dict(session_row),
        "total_enrolled": total_enrolled,
        "present_count": present_count,
        "absent_count": absent_count,
        "attendance_pct": attendance_pct,
        "present_list": present_list,
        "roster": roster
    }

# ----------------- STUDENT METRICS & HISTORY -----------------

def get_student_attendance_history(pid):
    conn = get_db_connection()
    records = conn.execute('''
        SELECT * FROM attendance_records 
        WHERE pid = ? 
        ORDER BY date DESC, timestamp DESC
    ''', (pid,)).fetchall()
    conn.close()
    return records

def get_student_stats(pid):
    conn = get_db_connection()
    
    # All present records for this student
    attended_records = conn.execute("SELECT * FROM attendance_records WHERE pid = ? AND status = 'Present'", (pid,)).fetchall()
    
    # Total sessions held for Division A
    total_sessions = conn.execute('''
        SELECT COUNT(DISTINCT id) FROM attendance_sessions 
        WHERE division = 'A' AND (status = 'closed' OR status = 'expired')
    ''').fetchone()[0]
    
    # All official subjects
    subjects = conn.execute('SELECT * FROM subjects ORDER BY code ASC').fetchall()
    
    subject_stats = []
    for sub in subjects:
        sub_code = sub['code']
        # Count total sessions for this subject
        sub_total_sessions = conn.execute('''
            SELECT COUNT(*) FROM attendance_sessions 
            WHERE (subject = ? OR subject_code = ?) AND division = 'A'
        ''', (sub_code, sub_code)).fetchone()[0]
        
        # Attended count
        attended_count = conn.execute('''
            SELECT COUNT(*) FROM attendance_records 
            WHERE pid = ? AND (subject = ? OR subject LIKE ?) AND status = 'Present'
        ''', (pid, sub_code, f"{sub_code}%")).fetchone()[0]

        # Use realistic baseline if newly created
        total_held = max(sub_total_sessions, attended_count, 1)
        pct = round((attended_count / total_held) * 100, 1)
        
        subject_stats.append({
            "code": sub_code,
            "name": sub['name'],
            "subject": sub_code,
            "faculty": sub['teacher_name'],
            "teacher": sub['teacher_name'],
            "attended": attended_count,
            "total": total_held,
            "percentage": pct,
            "eligible": pct >= 75.0
        })

    conn.close()

    total_attended = len(attended_records)
    total_classes = max(total_sessions, total_attended, 1) if total_sessions > 0 or total_attended > 0 else 0
    overall_percentage = round((total_attended / total_classes) * 100, 1) if total_classes > 0 else 0.0
    total_absent = max(0, total_classes - total_attended)

    return {
        "total_attended": total_attended,
        "total_classes": total_classes,
        "total_absent": total_absent,
        "overall_percentage": overall_percentage,
        "subject_breakdowns": subject_stats,
        "subject_stats": subject_stats
    }

# ----------------- TEACHER METRICS & REPORTS -----------------

def get_teacher_attendance_records(teacher_name, subject=None, date=None):
    conn = get_db_connection()
    query = 'SELECT * FROM attendance_records WHERE teacher_name LIKE ?'
    params = [f'%{teacher_name}%']
    
    if subject and subject != 'All':
        query += ' AND subject = ?'
        params.append(subject)
    if date:
        query += ' AND date = ?'
        params.append(date)
        
    query += ' ORDER BY date DESC, timestamp DESC'
    records = conn.execute(query, params).fetchall()
    conn.close()
    return records

def get_teacher_stats(teacher_name):
    conn = get_db_connection()
    # Total sessions conducted
    sessions = conn.execute('SELECT * FROM attendance_sessions WHERE teacher_name LIKE ?', (f'%{teacher_name}%',)).fetchall()
    total_sessions = len(sessions)

    # Total attendance marks (Present only)
    total_present = conn.execute("SELECT COUNT(*) FROM attendance_records WHERE teacher_name LIKE ? AND status = 'Present'", (f'%{teacher_name}%',)).fetchone()[0]

    # Total enrolled students in Div A
    total_students = conn.execute("SELECT COUNT(*) FROM students WHERE division = 'A'").fetchone()[0]

    avg_pct = round((total_present / (total_sessions * total_students) * 100), 1) if (total_sessions * total_students) > 0 else 0.0

    conn.close()
    return {
        "total_sessions": total_sessions,
        "total_present": total_present,
        "total_students": total_students,
        "average_attendance": avg_pct
    }


# ----------------- EXPORT TO EXCEL QUERIES -----------------

def get_all_attendance_for_export(subject=None, date=None, class_name=None, division=None):
    conn = get_db_connection()
    query = 'SELECT * FROM attendance_records WHERE 1=1'
    params = []
    
    if subject and subject != 'All':
        query += ' AND (subject = ? OR subject LIKE ?)'
        params.extend([subject, f"%{subject}%"])
    if date:
        query += ' AND date = ?'
        params.append(date)
    if division and division != 'All':
        query += ' AND division = ?'
        params.append(division)

    query += ' ORDER BY date DESC, lecture_time ASC, roll_number ASC'
    records = conn.execute(query, params).fetchall()
    conn.close()
    return records

# ----------------- NOTIFICATIONS -----------------

def get_notifications_for_role(role, target_id=None):
    conn = get_db_connection()
    notifications = conn.execute('''
        SELECT * FROM notifications 
        WHERE target_role = 'all' OR target_role = ? OR target_id = ?
        ORDER BY created_at DESC LIMIT 10
    ''', (role, target_id)).fetchall()
    conn.close()
    return notifications

def clear_attendance_history():
    conn = get_db_connection()
    conn.execute('DELETE FROM attendance_records')
    conn.execute('DELETE FROM attendance_sessions')
    conn.commit()
    conn.close()
    return True
