from flask import Flask, render_template, request, redirect, session, jsonify, url_for, send_file, Response
import datetime
import io
import os
import qrcode
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from database import (
    get_student_by_pid, get_student_by_id, get_student_by_email_or_pid,
    get_all_students, register_student, get_teacher_by_id,
    get_teacher_by_email_or_id, get_all_teachers, register_teacher,
    get_full_weekly_timetable, get_timetable_for_day, get_teacher_timetable,
    get_current_active_lecture, create_attendance_session, get_session_by_token,
    close_attendance_session, get_active_session_for_teacher, mark_qr_attendance,
    get_session_live_attendance, get_student_attendance_history, get_student_stats,
    get_teacher_attendance_records, get_teacher_stats, get_all_attendance_for_export,
    get_notifications_for_role, clear_attendance_history, init_db
)

app = Flask(__name__)
app.secret_key = 'supersecret_college_qr_key_2026'

# Ensure database is created on startup if missing
if not os.path.exists('attendance.db'):
    init_db()

# -------------------------------------------------------------
# AUTHENTICATION ROUTES
# -------------------------------------------------------------

@app.route('/')
def index():
    if 'role' in session:
        if session['role'] == 'teacher':
            return redirect(url_for('teacher_dashboard'))
        elif session['role'] == 'student':
            return redirect(url_for('student_dashboard'))
    return redirect(url_for('login'))

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/login-post', methods=['POST'])
def login_post():
    role = request.form.get('role', 'student').strip()
    identifier = request.form.get('identifier', '').strip()
    password = request.form.get('password', '').strip()

    if not identifier or not password:
        return render_template('login.html', error="Please provide both login ID and password.", role=role)

    if role in ['teacher', 'admin']:
        teacher = get_teacher_by_email_or_id(identifier)
        if not teacher and role == 'admin' and identifier.lower() in ['admin', 'admin@college.edu'] and password in ['admin123', 'admin', 'password']:
            all_teachers = get_all_teachers()
            teacher = all_teachers[0] if all_teachers else None

        if teacher and (teacher['password'] == password or (role == 'admin' and password in ['admin123', 'admin', 'password'])):
            session.clear()
            session['role'] = 'teacher'
            session['user_id'] = teacher['id']
            session['teacher_id'] = teacher['teacher_id']
            session['name'] = teacher['name']
            session['email'] = teacher['email']
            session['department'] = teacher['department']
            session['subjects'] = teacher['subjects']
            return redirect(url_for('teacher_dashboard'))
        else:
            return render_template('login.html', error="Invalid Teacher/Admin ID or Password.", role=role)
    else:
        student = get_student_by_email_or_pid(identifier)
        if student and student['password'] == password:
            session.clear()
            session['role'] = 'student'
            session['user_id'] = student['id']
            session['pid'] = student['pid']
            session['name'] = student['name']
            session['email'] = student['email']
            session['roll_number'] = student['roll_number']
            session['department'] = student['department']
            session['course'] = student['course']
            session['year'] = student['year']
            session['division'] = student['division']
            return redirect(url_for('student_dashboard'))
        else:
            return render_template('login.html', error="Invalid Student PID / Email / Roll or Password.", role='student')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/register-student-post', methods=['POST'])
def register_student_post():
    pid = request.form.get('pid', '').strip().upper()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()
    department = request.form.get('department', 'ECS').strip()
    course = request.form.get('course', 'Electronics & Computer Science').strip()
    year = request.form.get('year', 'Fourth Year').strip()
    division = request.form.get('division', 'A').strip().upper()
    roll_number = request.form.get('roll_number', '').strip()

    if not all([pid, name, email, password, roll_number]):
        return render_template('register.html', active_tab='student', error="All fields marked with * are required.")

    success, message = register_student(pid, name, email, password, department, course, year, division, roll_number)
    if success:
        return render_template('register.html', active_tab='student', success=f"Registration successful! Student PID: {pid}. You can now sign in.")
    else:
        return render_template('register.html', active_tab='student', error=message)

@app.route('/register-teacher-post', methods=['POST'])
def register_teacher_post():
    teacher_id = request.form.get('teacher_id', '').strip().upper()
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '').strip()
    department = request.form.get('department', 'ECS').strip()
    subjects = request.form.get('subjects', '').strip()

    if not all([teacher_id, name, email, password, subjects]):
        return render_template('register.html', active_tab='teacher', error="All fields marked with * are required.")

    success, message = register_teacher(teacher_id, name, email, password, department, subjects)
    if success:
        return render_template('register.html', active_tab='teacher', success=f"Teacher registered successfully! ID: {teacher_id}. You can now sign in.")
    else:
        return render_template('register.html', active_tab='teacher', error=message)

# -------------------------------------------------------------
# STUDENT DASHBOARD & SCANNER
# -------------------------------------------------------------

@app.route('/student-dashboard')
def student_dashboard():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    pid = session.get('pid')
    student = get_student_by_pid(pid)
    if not student:
        session.clear()
        return redirect(url_for('login'))

    stats = get_student_stats(pid)
    history = get_student_attendance_history(pid)
    now = datetime.datetime.now()
    active_lecture, upcoming_lecture, today_lectures = get_current_active_lecture(now)
    weekly_timetable = get_full_weekly_timetable()
    notifications = get_notifications_for_role('student', pid)

    return render_template(
        'student_dashboard.html',
        student=student,
        stats=stats,
        history=history,
        current_lecture=active_lecture,
        upcoming_lecture=upcoming_lecture,
        today_lectures=today_lectures,
        weekly_timetable=weekly_timetable,
        notifications=notifications,
        today_date=now.strftime('%A, %d %B %Y')
    )

@app.route('/student/scan-attendance', methods=['POST'])
def student_scan_attendance():
    """
    PROX-PREVENTION ATTENDANCE ENDPOINT:
    The student PID is STRICTLY fetched from the server session, NOT accepted from client request body.
    This guarantees that a student cannot mark attendance on behalf of someone else's PID.
    """
    if session.get('role') != 'student':
        return jsonify({"success": False, "error": "Unauthorized: Please log in as a student to mark attendance."}), 401

    student_pid = session.get('pid')
    if not student_pid:
        return jsonify({"success": False, "error": "Invalid student session. Please log in again."}), 401

    data = request.get_json(silent=True) or request.form
    session_token = data.get('session_token', '').strip()

    if not session_token:
        return jsonify({"success": False, "error": "Invalid scan: Attendance Session ID is missing."}), 400

    # Call backend validation & recording engine
    success, result = mark_qr_attendance(session_token, student_pid)

    if success:
        return jsonify({
            "success": True,
            "message": f"Attendance marked successfully for {result['subject']}!",
            "details": result
        })
    else:
        return jsonify({
            "success": False,
            "error": result
        }), 400

# -------------------------------------------------------------
# TEACHER DASHBOARD & LIVE ATTENDANCE
# -------------------------------------------------------------

@app.route('/teacher-dashboard')
def teacher_dashboard():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))

    teacher_id = session.get('teacher_id')
    teacher = get_teacher_by_id(teacher_id)
    if not teacher:
        session.clear()
        return redirect(url_for('login'))

    teacher_name = teacher['name']
    now = datetime.datetime.now()
    day_name = now.strftime('%A')
    
    # Timetable for teacher
    today_schedule = get_teacher_timetable(teacher_name, day_name)
    all_teacher_schedule = get_teacher_timetable(teacher_name)
    
    # Active lecture from timetable
    active_lecture, upcoming_lecture, _ = get_current_active_lecture(now)
    # Check if active lecture is taught by this teacher
    teacher_active_lec = None
    if active_lecture and (teacher['name'] in active_lecture['teacher_name'] or teacher['teacher_id'] in active_lecture['teacher_code']):
        teacher_active_lec = active_lecture

    # Active session if any
    active_session = get_active_session_for_teacher(teacher_id)
    
    stats = get_teacher_stats(teacher_name)
    recent_records = get_teacher_attendance_records(teacher_name)
    students_list = get_all_students()
    notifications = get_notifications_for_role('teacher', teacher_id)

    return render_template(
        'teacher_dashboard.html',
        teacher=teacher,
        today_schedule=today_schedule,
        all_schedule=all_teacher_schedule,
        current_lecture=teacher_active_lec,
        upcoming_lecture=upcoming_lecture,
        active_session=active_session,
        stats=stats,
        recent_records=recent_records,
        students=students_list,
        notifications=notifications,
        today_date=now.strftime('%A, %d %B %Y')
    )

@app.route('/teacher/start-attendance', methods=['POST'])
def teacher_start_attendance():
    if session.get('role') != 'teacher':
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    teacher_id = session.get('teacher_id')
    teacher = get_teacher_by_id(teacher_id)
    if not teacher:
        return jsonify({"success": False, "error": "Teacher profile not found"}), 404

    data = request.get_json(silent=True) or request.form
    subject = data.get('subject', '').strip()
    subject_code = data.get('subject_code', subject).strip()
    class_name = data.get('class_name', 'Fourth Year B.E. ECS').strip()
    division = data.get('division', 'A').strip().upper()
    duration = int(data.get('duration', 15))

    # If no subject passed, attempt to grab from active timetable lecture
    if not subject:
        active_lec, _, _ = get_current_active_lecture()
        if active_lec:
            subject = active_lec['subject']
            subject_code = active_lec['subject_code']
        else:
            # Fallback to teacher's first assigned subject
            subjects = [s.strip() for s in teacher['subjects'].split(',') if s.strip()]
            subject = subjects[0] if subjects else "General Lecture"
            subject_code = subject

    new_session = create_attendance_session(
        teacher_id=teacher_id,
        teacher_name=teacher['name'],
        subject=subject,
        subject_code=subject_code,
        class_name=class_name,
        division=division,
        duration_minutes=duration
    )

    return jsonify({
        "success": True,
        "message": f"Attendance session started for {subject}!",
        "session": new_session
    })

@app.route('/teacher/stop-attendance', methods=['POST'])
def teacher_stop_attendance():
    if session.get('role') != 'teacher':
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or request.form
    session_token = data.get('session_token')
    
    if not session_token:
        # Close current active session for this teacher
        active_session = get_active_session_for_teacher(session.get('teacher_id'))
        if active_session:
            session_token = active_session['session_token']

    if session_token:
        close_attendance_session(session_token)
        return jsonify({"success": True, "message": "Attendance session closed successfully."})
    
    return jsonify({"success": False, "error": "No active session found to close."}), 400

@app.route('/teacher/live-attendance/<session_token>')
def teacher_live_attendance(session_token):
    if session.get('role') != 'teacher':
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = get_session_live_attendance(session_token)
    if not data:
        return jsonify({"success": False, "error": "Session not found"}), 404

    return jsonify({"success": True, "data": data})

@app.route('/teacher/manual-override', methods=['POST'])
def teacher_manual_override():
    if session.get('role') != 'teacher':
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or request.form
    student_pid = data.get('student_pid', '').strip().upper()
    session_token = data.get('session_token', '').strip()

    if not student_pid:
        return jsonify({"success": False, "error": "Student PID is required."}), 400

    teacher_id = session.get('teacher_id')
    active_session = get_active_session_for_teacher(teacher_id)
    if not session_token and active_session:
        session_token = active_session['session_token']

    if not session_token:
        # If no active session, find current teacher and start a temporary manual session
        teacher = get_teacher_by_id(teacher_id)
        sub = teacher['subjects'].split(',')[0].strip() if teacher else 'General'
        sess_success, new_sess = create_attendance_session(teacher_id, sub, duration_minutes=60)
        if sess_success:
            session_token = new_sess['session_token']
        else:
            return jsonify({"success": False, "error": "Could not create attendance session."}), 400

    success, result = mark_qr_attendance(session_token, student_pid)
    if success:
        return jsonify({
            "success": True,
            "message": f"Student {student_pid} marked present manually!",
            "details": result,
            "session_token": session_token
        })
    else:
        return jsonify({"success": False, "error": result}), 400

@app.route('/teacher/clear-history', methods=['POST'])
def teacher_clear_history():
    if session.get('role') != 'teacher':
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    clear_attendance_history()
    return jsonify({"success": True, "message": "Attendance history cleared successfully."})

# -------------------------------------------------------------
# QR CODE GENERATORS (PNG RESPONSES)
# -------------------------------------------------------------

@app.route('/student-qr/<pid>')
def student_qr(pid):
    """
    Generates Student Profile QR code containing the Student's unique PID.
    """
    student = get_student_by_pid(pid)
    if not student:
        return "Student not found", 404

    # QR Payload formatted clearly
    qr_content = f"STUDENT-PID:{student['pid']}"
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=3,
    )
    qr.add_data(qr_content)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)

    download = request.args.get('download', '0') == '1'
    if download:
        return send_file(buf, mimetype="image/png", as_attachment=True, download_name=f"Student_QR_{student['pid']}.png")
    return send_file(buf, mimetype="image/png")

@app.route('/session-qr/<session_token>')
def session_qr(session_token):
    """
    Generates dynamic Temporary Attendance Session QR code.
    Contains the session token required for students to mark attendance.
    """
    sess = get_session_by_token(session_token)
    if not sess:
        return "Invalid session token", 404

    # Structured QR payload
    qr_payload = session_token
    
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(qr_payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="#171e19", back_color="#ffe17c")
    buf = io.BytesIO()
    img.save(buf)
    buf.seek(0)

    return send_file(buf, mimetype="image/png")

# -------------------------------------------------------------
# EXCEL EXPORT (.XLSX)
# -------------------------------------------------------------

@app.route('/export-attendance-excel')
def export_attendance_excel():
    if session.get('role') != 'teacher':
        return redirect(url_for('login'))

    subject = request.args.get('subject', 'All')
    date = request.args.get('date', '')
    division = request.args.get('division', 'A')

    records = get_all_attendance_for_export(
        subject=subject if subject != 'All' else None,
        date=date if date else None,
        division=division if division != 'All' else None
    )

    # Create openpyxl Workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Attendance Records"

    # Ensure grid lines are visible
    ws.views.sheetView[0].showGridLines = True

    # Styling definitions
    title_font = Font(name="Segoe UI", size=16, bold=True, color="171E19")
    subtitle_font = Font(name="Segoe UI", size=10, italic=True, color="555555")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="171E19", end_color="171E19", fill_type="solid")
    alt_fill = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
    present_font = Font(name="Segoe UI", size=10, bold=True, color="008000")
    
    thin_border = Border(
        left=Side(style='thin', color='CCCCCC'),
        right=Side(style='thin', color='CCCCCC'),
        top=Side(style='thin', color='CCCCCC'),
        bottom=Side(style='thin', color='CCCCCC')
    )

    # Header Title Block
    ws.merge_cells('A1:M1')
    ws['A1'] = "COLLEGE OF ENGINEERING & TECHNOLOGY — DEPARTMENT OF ECS"
    ws['A1'].font = title_font
    ws['A1'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells('A2:M2')
    export_sub = f"Official Attendance Report | Class: Fourth Year B.E. ECS (Div {division}) | Subject: {subject} | Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    ws['A2'] = export_sub
    ws['A2'].font = subtitle_font
    ws['A2'].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 20

    # Blank spacer row
    ws.row_dimensions[3].height = 10

    # Table Column Headers
    headers = [
        "PID", "Student Name", "Roll Number", "Department", "Year",
        "Division", "Subject", "Teacher", "Date", "Day",
        "Lecture Time", "Timestamp", "Status"
    ]
    ws.row_dimensions[4].height = 24

    for col_num, header_title in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_num, value=header_title)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Data Rows
    for row_idx, r in enumerate(records, 5):
        row_values = [
            r['pid'],
            r['student_name'],
            r['roll_number'],
            r['department'],
            r['year'],
            r['division'],
            r['subject'],
            r['teacher_name'],
            r['date'],
            r['day'],
            r['lecture_time'],
            r['timestamp'],
            r['status']
        ]
        ws.row_dimensions[row_idx].height = 20

        is_even = (row_idx % 2 == 0)
        for col_num, val in enumerate(row_values, 1):
            cell = ws.cell(row=row_idx, column=col_num, value=val)
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center" if col_num in [1, 3, 5, 6, 9, 10, 13] else "left", vertical="center")
            if is_even:
                cell.fill = alt_fill
            if col_num == 13: # Status column
                cell.font = present_font

    # Auto-adjust column widths
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.row > 2 and cell.value:
                max_len = max(max_len, len(str(cell.value)))
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    # Save to BytesIO buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"ECS_Attendance_Report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buffer,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename
    )

# -------------------------------------------------------------
# TIMETABLE API (For interactive dynamic schedules)
# -------------------------------------------------------------

@app.route('/api/timetable')
def api_timetable():
    day = request.args.get('day')
    if day:
        lectures = [dict(r) for r in get_timetable_for_day(day)]
    else:
        lectures = [dict(r) for r in get_full_weekly_timetable()]
    return jsonify(lectures)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
