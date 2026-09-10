import os
import sqlite3
import datetime
import uuid
import math
import hmac
import hashlib
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'attendance.db')
SCHEMA_PATH = os.path.join(BASE_DIR, 'schema.sql')

# Dynamic QR code rotation window (25 seconds) and HMAC signing secret
DYNAMIC_QR_WINDOW = 25
DYNAMIC_QR_SECRET = os.getenv('DYNAMIC_QR_SECRET', 'attendqr_dynamic_secret_2026_superkey')

def get_current_time():
    """
    Returns current datetime in Indian Standard Time (IST, UTC+5:30) as a naive datetime,
    ensuring accurate college local time on cloud hosting (Railway, AWS, etc.) without comparison errors.
    """
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(os.getenv('COLLEGE_TIMEZONE', 'Asia/Kolkata'))
        return datetime.datetime.now(tz).replace(tzinfo=None)
    except Exception:
        ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        return datetime.datetime.now(ist).replace(tzinfo=None)

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
    except Exception:
        pass
    return conn

def migrate_db_schema():
    """
    Automatically alters existing SQLite database tables to include geofencing
    and location verification columns if they do not already exist, preserving data.
    """
    if not os.path.exists(DB_NAME):
        init_db()
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        if 'students' not in tables or 'attendance_sessions' not in tables or 'attendance_records' not in tables:
            conn.close()
            init_db()
            return

        # 1. Update attendance_sessions
        session_cols = [c[1] for c in cursor.execute('PRAGMA table_info(attendance_sessions)').fetchall()]
        if 'latitude' not in session_cols:
            cursor.execute('ALTER TABLE attendance_sessions ADD COLUMN latitude REAL')
        if 'longitude' not in session_cols:
            cursor.execute('ALTER TABLE attendance_sessions ADD COLUMN longitude REAL')
        if 'radius_meters' not in session_cols:
            cursor.execute('ALTER TABLE attendance_sessions ADD COLUMN radius_meters REAL DEFAULT 50.0')
        if 'geofence_enabled' not in session_cols:
            cursor.execute('ALTER TABLE attendance_sessions ADD COLUMN geofence_enabled INTEGER DEFAULT 1')

        # 2. Update attendance_records
        record_cols = [c[1] for c in cursor.execute('PRAGMA table_info(attendance_records)').fetchall()]
        if 'student_lat' not in record_cols:
            cursor.execute('ALTER TABLE attendance_records ADD COLUMN student_lat REAL')
        if 'student_lng' not in record_cols:
            cursor.execute('ALTER TABLE attendance_records ADD COLUMN student_lng REAL')
        if 'distance_meters' not in record_cols:
            cursor.execute('ALTER TABLE attendance_records ADD COLUMN distance_meters REAL')
        if 'geofence_verified' not in record_cols:
            cursor.execute('ALTER TABLE attendance_records ADD COLUMN geofence_verified INTEGER DEFAULT 1')

        conn.commit()
    except Exception as e:
        print(f"Schema migration warning: {e}")
    finally:
        conn.close()

# Run migration on module load
migrate_db_schema()

def init_db():
    conn = get_db_connection()
    with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()

def seed_historical_attendance(conn):
    # No fake data: real attendance records only
    pass

# ----------------- GEOFENCING & DYNAMIC QR UTILITIES -----------------

def calculate_distance_meters(lat1, lon1, lat2, lon2):
    """
    Calculates geodesic distance between two GPS coordinates using the Haversine formula.
    Returns distance in meters rounded to 2 decimal places.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
        R = 6371000.0  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)
        a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return round(R * c, 2)
    except Exception as e:
        print(f"Error calculating distance: {e}")
        return None

def get_dynamic_qr_payload(session_token, window_seconds=DYNAMIC_QR_WINDOW):
    """
    Generates a dynamic temporary QR code payload rotating every `window_seconds`.
    Format: SESSION_TOKEN:DYNAMIC_HASH:WINDOW_INDEX
    """
    now_ts = int(time.time())
    window_index = now_ts // window_seconds
    seconds_remaining = window_seconds - (now_ts % window_seconds)

    data = f"{session_token}:{window_index}".encode('utf-8')
    dynamic_code = hmac.new(DYNAMIC_QR_SECRET.encode('utf-8'), data, hashlib.sha256).hexdigest()[:8].upper()
    payload = f"{session_token}:{dynamic_code}:{window_index}"
    return {
        "payload": payload,
        "session_token": session_token,
        "dynamic_code": dynamic_code,
        "window_index": window_index,
        "seconds_remaining": seconds_remaining,
        "window_seconds": window_seconds
    }

def validate_dynamic_qr_payload(scanned_payload, window_seconds=DYNAMIC_QR_WINDOW):
    """
    Validates dynamic QR code token.
    Accepts:
      1) Dynamic format: SESSION_TOKEN:DYNAMIC_CODE:WINDOW_INDEX
      2) Direct session token: SESSION_TOKEN (for manual token fallback)
    Returns (is_valid, session_token, error_message)
    """
    if not scanned_payload:
        return False, None, "Invalid scan: Attendance Session ID is empty."

    scanned_payload = scanned_payload.strip()
    parts = scanned_payload.split(':')

    if len(parts) == 3:
        token, scanned_code, scanned_window_str = parts[0], parts[1], parts[2]
        try:
            scanned_window = int(scanned_window_str)
        except ValueError:
            return False, token, "Invalid dynamic QR code structure."

        current_ts = int(time.time())
        current_window = current_ts // window_seconds

        # Allow current window and previous window (grace period for network/scan lag)
        valid_windows = [current_window, current_window - 1]

        if scanned_window not in valid_windows:
            return False, token, "QR Code expired. Please scan the newly refreshed QR code displayed on the screen."

        expected_data = f"{token}:{scanned_window}".encode('utf-8')
        expected_code = hmac.new(DYNAMIC_QR_SECRET.encode('utf-8'), expected_data, hashlib.sha256).hexdigest()[:8].upper()

        if not hmac.compare_digest(scanned_code.upper(), expected_code):
            return False, token, "Invalid QR security signature. Please scan the current lecture QR."

        return True, token, None

    elif len(parts) == 1:
        # Fallback to direct token if teacher provided code or student entered manually
        token = parts[0]
        return True, token, None

    return False, None, "Unrecognized QR code format."

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
        now = get_current_time()
    
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

def create_attendance_session(teacher_id, teacher_name, subject, subject_code, class_name, division, start_time=None, end_time=None, duration_minutes=15, latitude=None, longitude=None, radius_meters=50.0, geofence_enabled=1):
    now = get_current_time()
    date_str = now.strftime('%Y-%m-%d')
    start_time_str = start_time or now.strftime('%I:%M %p')
    
    # Calculate expiry
    expires_at = now + datetime.timedelta(minutes=duration_minutes)
    expires_at_str = expires_at.strftime('%Y-%m-%d %H:%M:%S')
    end_time_str = end_time or expires_at.strftime('%I:%M %p')

    # Parse and validate geofence parameters
    lat_val = float(latitude) if latitude is not None and str(latitude).strip() != '' else None
    lng_val = float(longitude) if longitude is not None and str(longitude).strip() != '' else None
    radius_val = float(radius_meters) if radius_meters is not None and str(radius_meters).strip() != '' else 50.0
    geo_enabled_val = 1 if (geofence_enabled and lat_val is not None and lng_val is not None) else 0

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
        (session_token, teacher_id, teacher_name, subject, subject_code, class_name, division, date, start_time, end_time, expires_at, status, latitude, longitude, radius_meters, geofence_enabled)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
    ''', (session_token, teacher_id, teacher_name, subject, subject_code, class_name, division, date_str, start_time_str, end_time_str, expires_at_str, lat_val, lng_val, radius_val, geo_enabled_val))
    
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Functional notification for students
    loc_info = f" (Geofence: {int(radius_val)}m)" if geo_enabled_val else ""
    add_notification(
        target_role='student',
        title=f"Attendance Started: {subject}",
        message=f"{teacher_name} initiated attendance for {subject} (Div {division}){loc_info}. Scan live QR now.",
        type='info'
    )

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
        "status": "active",
        "latitude": lat_val,
        "longitude": lng_val,
        "radius_meters": radius_val,
        "geofence_enabled": geo_enabled_val
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
        day_name = get_current_time().strftime('%A')

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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    now_str = get_current_time().strftime('%Y-%m-%d %H:%M:%S')
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
        now = get_current_time()
        expires_at = datetime.datetime.strptime(session_row['expires_at'], '%Y-%m-%d %H:%M:%S')
        if now > expires_at:
            finalize_attendance_session(session_row['id'])
            return None
    return session_row


# ----------------- QR ATTENDANCE VALIDATION & RECORDING -----------------

def mark_qr_attendance(session_token_or_payload, student_pid, student_lat=None, student_lng=None, accuracy=None):
    """
    Validates and marks attendance for an authenticated student.
    Validation steps:
      1. Dynamic QR validity (time window expiration and cryptographic signature)
      2. Authenticated student exists in DB
      3. Session exists and is active & not expired
      4. Geofencing: Verifies student GPS is within teacher's allowed classroom radius
      5. Student class and division match session
      6. Duplicate prevention per session
      7. Record verified attendance with GPS coordinates & distance
      8. Issue real-time functional notifications
    """
    # Step 1: Validate Dynamic QR Payload
    is_valid_qr, session_token, qr_err = validate_dynamic_qr_payload(session_token_or_payload)
    if not is_valid_qr:
        return False, qr_err

    conn = get_db_connection()
    cursor = conn.cursor()

    # Step 2: Validate Student
    student = cursor.execute('SELECT * FROM students WHERE pid = ?', (student_pid,)).fetchone()
    if not student:
        conn.close()
        return False, "Invalid Student: Student PID not registered in database."

    # Step 3: Validate Session
    session_row = cursor.execute('SELECT * FROM attendance_sessions WHERE session_token = ?', (session_token,)).fetchone()
    if not session_row:
        conn.close()
        return False, "Invalid attendance session: QR code not recognized."

    # Check Session Status and Expiration
    if session_row['status'] != 'active':
        conn.close()
        return False, f"Attendance session is {session_row['status']}. Attendance is closed."

    now = get_current_time()
    expires_at = datetime.datetime.strptime(session_row['expires_at'], '%Y-%m-%d %H:%M:%S')
    if now > expires_at:
        cursor.execute("UPDATE attendance_sessions SET status = 'expired' WHERE id = ?", (session_row['id'],))
        conn.commit()
        conn.close()
        return False, "Attendance session has expired. Please ask the teacher to refresh the QR code."

    # Step 4: Geofencing Verification (Backend Distance Calculation)
    geo_enabled = bool(session_row['geofence_enabled']) if 'geofence_enabled' in session_row.keys() else False
    teacher_lat = session_row['latitude'] if 'latitude' in session_row.keys() else None
    teacher_lng = session_row['longitude'] if 'longitude' in session_row.keys() else None
    allowed_radius = float(session_row['radius_meters']) if ('radius_meters' in session_row.keys() and session_row['radius_meters'] is not None) else 50.0

    distance = None
    student_lat_val = None
    student_lng_val = None

    if geo_enabled and teacher_lat is not None and teacher_lng is not None:
        if student_lat is None or student_lng is None or str(student_lat).strip() == '' or str(student_lng).strip() == '':
            conn.close()
            return False, "GPS Location Required: Classroom geofencing is enabled for this lecture. Tap the 🔒/settings icon in your browser address bar → allow Location, and retry scanning."

        try:
            student_lat_val = float(student_lat)
            student_lng_val = float(student_lng)
            teacher_lat_val = float(teacher_lat)
            teacher_lng_val = float(teacher_lng)
        except (ValueError, TypeError):
            conn.close()
            return False, "Invalid GPS coordinates received from your device."

        distance = calculate_distance_meters(teacher_lat_val, teacher_lng_val, student_lat_val, student_lng_val)

        if distance is None:
            conn.close()
            return False, "Unable to compute location distance."

        # Indoor GPS & Wi-Fi triangulation tolerance:
        # Laptops indoors typically report Wi-Fi BSSID location (accuracy ±100m to 200m).
        # Mobile phones indoors report cellular/GPS location (accuracy ±50m to 150m).
        # Add device accuracy buffer and ensure minimum 250m classroom/lab radius tolerance
        # so students in the same room are verified, while rejecting remote proxy scans (>250m).
        device_accuracy = 0.0
        if accuracy is not None:
            try:
                device_accuracy = max(0.0, float(accuracy))
            except Exception:
                pass

        effective_radius = max(float(allowed_radius) + device_accuracy, 250.0)

        # Reject if outside allowed radius
        if distance > effective_radius:
            conn.close()
            # Functional notification for rejected attendance
            add_notification(
                target_role='student',
                target_id=student_pid,
                title='Attendance Rejected (Outside Geofence)',
                message=f"Attendance for {session_row['subject']} rejected: You were {round(distance, 1)}m away from classroom (Allowed: {int(effective_radius)}m).",
                type='danger'
            )
            return False, f"Location verification failed: You are {round(distance, 1)}m away from the classroom (Maximum allowed: {int(effective_radius)}m)."
    else:
        if student_lat is not None and student_lng is not None:
            try:
                student_lat_val = float(student_lat)
                student_lng_val = float(student_lng)
                if teacher_lat is not None and teacher_lng is not None:
                    distance = calculate_distance_meters(float(teacher_lat), float(teacher_lng), student_lat_val, student_lng_val)
            except Exception:
                pass

    # Step 5: Class and Division Verification
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
        # If student was marked Absent previously, update to Present
        day_name = now.strftime('%A')
        timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE attendance_records 
            SET status = 'Present', timestamp = ?, student_lat = ?, student_lng = ?, distance_meters = ?, geofence_verified = 1
            WHERE session_id = ? AND pid = ?
        ''', (timestamp_str, student_lat_val, student_lng_val, distance, session_row['id'], student['pid']))
        conn.commit()
        conn.close()

        # Success notification
        dist_text = f" ({round(distance, 1)}m from teacher)" if distance is not None else ""
        add_notification(
            target_role='student',
            target_id=student_pid,
            title='Attendance Marked Present',
            message=f"Attendance updated to Present for {session_row['subject']}{dist_text}.",
            type='success'
        )

        return True, {
            "record_id": existing['id'],
            "pid": student['pid'],
            "name": student['name'],
            "roll_number": student['roll_number'],
            "subject": session_row['subject'],
            "teacher": session_row['teacher_name'],
            "date": session_row['date'],
            "timestamp": timestamp_str,
            "status": "Present",
            "distance_meters": distance
        }

    # Step 7: Record Attendance
    day_name = now.strftime('%A')
    timestamp_str = now.strftime('%Y-%m-%d %H:%M:%S')
    lecture_time = f"{session_row['start_time']} - {session_row['end_time']}"

    cursor.execute('''
        INSERT INTO attendance_records 
        (session_id, session_token, pid, student_name, roll_number, department, year, division, subject, teacher_name, date, day, lecture_time, timestamp, status, student_lat, student_lng, distance_meters, geofence_verified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Present', ?, ?, ?, 1)
    ''', (session_row['id'], session_token, student['pid'], student['name'], student['roll_number'],
          student['department'], student['year'], student['division'], session_row['subject'],
          session_row['teacher_name'], session_row['date'], day_name, lecture_time, timestamp_str,
          student_lat_val, student_lng_val, distance))
    
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Functional notification for successful attendance
    dist_text = f" (Verified inside {int(allowed_radius)}m zone, actual: {round(distance, 1)}m)" if distance is not None else ""
    add_notification(
        target_role='student',
        target_id=student_pid,
        title='Attendance Verified ✓',
        message=f"Attendance successfully recorded for {session_row['subject']}{dist_text}.",
        type='success'
    )

    return True, {
        "record_id": record_id,
        "pid": student['pid'],
        "name": student['name'],
        "roll_number": student['roll_number'],
        "subject": session_row['subject'],
        "teacher": session_row['teacher_name'],
        "date": session_row['date'],
        "timestamp": timestamp_str,
        "status": "Present",
        "distance_meters": distance
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

def check_and_notify_shortage(student_pid, overall_percentage):
    """
    Checks if a student with attendance shortage (<75%) needs a notification,
    preventing duplicate notification spam on every reload.
    """
    conn = get_db_connection()
    today_str = get_current_time().strftime('%Y-%m-%d')
    existing = conn.execute('''
        SELECT id FROM notifications 
        WHERE target_id = ? AND title LIKE '%Shortage%' AND created_at LIKE ?
    ''', (student_pid, f"{today_str}%")).fetchone()
    conn.close()

    if not existing:
        add_notification(
            target_role='student',
            target_id=student_pid,
            title='⚠️ Attendance Shortage Alert',
            message=f"Your current overall attendance is {overall_percentage}%, which is below the mandatory 75% threshold. Please attend all upcoming lectures.",
            type='warning'
        )

def get_student_stats(pid):
    conn = get_db_connection()
    
    # All present records for this student
    attended_records = conn.execute("SELECT * FROM attendance_records WHERE pid = ? AND status = 'Present'", (pid,)).fetchall()
    
    # Total distinct sessions held for Division A
    total_sessions = conn.execute('''
        SELECT COUNT(DISTINCT id) FROM attendance_sessions 
        WHERE division = 'A' AND (status = 'closed' OR status = 'expired' OR id IN (SELECT DISTINCT session_id FROM attendance_records))
    ''').fetchone()[0]
    
    # All official subjects
    subjects = conn.execute('SELECT * FROM subjects ORDER BY code ASC').fetchall()
    
    subject_stats = []
    shortage_subjects = []
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

        total_held = max(sub_total_sessions, attended_count)
        if total_held > 0:
            pct = round((attended_count / total_held) * 100, 1)
        else:
            pct = 0.0  # No sessions held yet for this subject — show 0, not fake 100%
        
        is_eligible = pct >= 75.0
        if total_held > 0 and not is_eligible:
            shortage_subjects.append(sub_code)

        subject_stats.append({
            "code": sub_code,
            "name": sub['name'],
            "subject": sub_code,
            "faculty": sub['teacher_name'],
            "teacher": sub['teacher_name'],
            "attended": attended_count,
            "total": total_held,
            "percentage": pct,
            "eligible": is_eligible
        })

    conn.close()

    total_attended = len(attended_records)
    total_classes = max(total_sessions, total_attended)
    if total_classes > 0:
        overall_percentage = round((total_attended / total_classes) * 100, 1)
    else:
        overall_percentage = 0.0  # No sessions held yet — show 0, not fake 100%

    total_absent = max(0, total_classes - total_attended)
    has_shortage = (total_classes >= 1 and overall_percentage < 75.0)

    # Automatically trigger shortage warning notification for student
    if has_shortage:
        check_and_notify_shortage(pid, overall_percentage)

    return {
        "total_attended": total_attended,
        "total_classes": total_classes,
        "total_absent": total_absent,
        "overall_percentage": overall_percentage,
        "has_shortage": has_shortage,
        "shortage_subjects": shortage_subjects,
        "subject_breakdowns": subject_stats,
        "subject_stats": subject_stats
    }

# ----------------- TEACHER METRICS, ANALYTICS & REPORTS -----------------

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

def get_teacher_analytics(teacher_name=None, division='A'):
    """
    Comprehensive real database analytics:
    - Overall attendance %
    - Subject-wise attendance breakdown
    - Present / Absent counts
    - Attendance trend across recent sessions
    - Low-attendance students (<75%)
    """
    conn = get_db_connection()

    # 1. Total sessions held for division (with records or closed/expired)
    sessions_query = "SELECT * FROM attendance_sessions WHERE division = ? AND (status IN ('closed', 'expired') OR id IN (SELECT DISTINCT session_id FROM attendance_records))"
    params = [division]
    if teacher_name:
        sessions_query += " AND teacher_name LIKE ?"
        params.append(f"%{teacher_name}%")
    sessions_query += " ORDER BY date DESC, start_time DESC"
    sessions = conn.execute(sessions_query, params).fetchall()

    total_sessions = len(sessions)
    session_ids = [s['id'] for s in sessions]

    # 2. Total enrolled students in division
    enrolled_students = conn.execute("SELECT * FROM students WHERE division = ? ORDER BY CAST(roll_number AS INTEGER) ASC, roll_number ASC", (division,)).fetchall()
    total_enrolled = len(enrolled_students)

    # 3. Overall attendance counts
    if session_ids:
        placeholders = ','.join('?' * len(session_ids))
        total_present = conn.execute(f"SELECT COUNT(*) FROM attendance_records WHERE session_id IN ({placeholders}) AND status = 'Present'", session_ids).fetchone()[0]
        total_absent = conn.execute(f"SELECT COUNT(*) FROM attendance_records WHERE session_id IN ({placeholders}) AND status = 'Absent'", session_ids).fetchone()[0]
    else:
        total_present = 0
        total_absent = 0

    total_expected = total_sessions * total_enrolled
    overall_attendance_pct = round((total_present / total_expected * 100), 1) if total_expected > 0 else 0.0

    # 4. Subject-wise attendance breakdown
    subjects = conn.execute("SELECT * FROM subjects ORDER BY code ASC").fetchall()
    subject_analytics = []
    for sub in subjects:
        sub_code = sub['code']
        sub_sess_q = "SELECT id FROM attendance_sessions WHERE (subject = ? OR subject_code = ?) AND division = ?"
        sub_params = [sub_code, sub_code, division]
        if teacher_name:
            sub_sess_q += " AND teacher_name LIKE ?"
            sub_params.append(f"%{teacher_name}%")
        sub_sess_ids = [r['id'] for r in conn.execute(sub_sess_q, sub_params).fetchall()]
        sub_total_sess = len(sub_sess_ids)

        if sub_sess_ids:
            sub_placeholders = ','.join('?' * len(sub_sess_ids))
            sub_present = conn.execute(f"SELECT COUNT(*) FROM attendance_records WHERE session_id IN ({sub_placeholders}) AND status = 'Present'", sub_sess_ids).fetchone()[0]
            sub_absent = conn.execute(f"SELECT COUNT(*) FROM attendance_records WHERE session_id IN ({sub_placeholders}) AND status = 'Absent'", sub_sess_ids).fetchone()[0]
        else:
            sub_present = 0
            sub_absent = 0

        sub_expected = sub_total_sess * total_enrolled
        sub_turnout_pct = round((sub_present / sub_expected * 100), 1) if sub_expected > 0 else 0.0

        subject_analytics.append({
            "code": sub_code,
            "name": sub['name'],
            "faculty": sub['teacher_name'],
            "total_sessions": sub_total_sess,
            "present_count": sub_present,
            "absent_count": sub_absent,
            "turnout_pct": sub_turnout_pct,
            "status": "Healthy" if sub_turnout_pct >= 75.0 else ("Low" if sub_total_sess > 0 else "Pending")
        })

    # 5. Attendance Trend (Last 7 sessions)
    trend = []
    for s in sessions[:7]:
        s_id = s['id']
        s_present = conn.execute("SELECT COUNT(*) FROM attendance_records WHERE session_id = ? AND status = 'Present'", (s_id,)).fetchone()[0]
        s_turnout = round((s_present / total_enrolled * 100), 1) if total_enrolled > 0 else 0.0
        trend.append({
            "session_id": s_id,
            "date": s['date'],
            "time": s['start_time'],
            "subject": s['subject'],
            "present_count": s_present,
            "total_enrolled": total_enrolled,
            "turnout_pct": s_turnout
        })
    trend.reverse()

    # 6. Low-Attendance Students (< 75%)
    low_attendance_students = []
    for s in enrolled_students:
        s_pid = s['pid']
        s_stats = get_student_stats(s_pid)
        if s_stats['total_classes'] > 0 and s_stats['overall_percentage'] < 75.0:
            shortage_subs = [sub['subject'] for sub in s_stats['subject_breakdowns'] if sub['total'] > 0 and sub['percentage'] < 75.0]
            classes_needed = max(1, int(math.ceil(3 * s_stats['total_classes'] - 4 * s_stats['total_attended'])))
            low_attendance_students.append({
                "pid": s_pid,
                "name": s['name'],
                "roll_number": s['roll_number'],
                "department": s['department'],
                "total_attended": s_stats['total_attended'],
                "total_classes": s_stats['total_classes'],
                "overall_percentage": s_stats['overall_percentage'],
                "classes_needed": classes_needed,
                "shortage_subjects": shortage_subs
            })

    conn.close()

    return {
        "overall_percentage": overall_attendance_pct,
        "total_sessions": total_sessions,
        "total_enrolled": total_enrolled,
        "total_present": total_present,
        "total_absent": total_absent,
        "subject_analytics": subject_analytics,
        "trend": trend,
        "low_attendance_students": low_attendance_students,
        "shortage_count": len(low_attendance_students)
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

def add_notification(target_role, title, message, target_id=None, type='info'):
    """
    Inserts a functional notification into the notifications table.
    target_role: 'all', 'student', 'teacher'
    type: 'info', 'success', 'warning', 'danger'
    """
    try:
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO notifications (target_role, target_id, title, message, type)
            VALUES (?, ?, ?, ?, ?)
        ''', (target_role, target_id, title, message, type))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error adding notification: {e}")

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
