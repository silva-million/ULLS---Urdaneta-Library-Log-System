from datetime import datetime, date, time, timedelta
from flask import Blueprint, request, render_template_string, render_template
from flask import current_app, Response, send_file
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
import io, qrcode
import pandas as pd

from ..extensions import db
from ..models.employee import Employee
from ..models.attendance import Attendance
from ..models.daily_qr import DailyQR

employee_bp = Blueprint("employee", __name__, template_folder="templates")
late_cutoff = time(8, 0)

SCAN_HTML = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>Employee Scan</title></head>
<body style="font-family:Arial; padding:24px;">
  <h2>Attendance Scan</h2>

  {% if error %}<p style="color:red;">{{ error }}</p>{% endif %}
  {% if msg %}<p style="color:green;">{{ msg }}</p>{% endif %}

  {% if ok %}
    <form method="post">
      <input type="hidden" name="token" value="{{ token }}">
      <label>Enter Employee ID</label><br>
      <input name="employee_id" placeholder="e.g. 2024-001" required>
      <button type="submit">Submit</button>
    </form>
  {% endif %}
</body>
</html>
"""

def _to_dt(t):
    return datetime.combine(date.today(), t)

def _compute_minutes(am_in, lunch_out, lunch_in, pm_out):
    total = 0
    if am_in and lunch_out and lunch_out > am_in:
        total += int((_to_dt(lunch_out) - _to_dt(am_in)).total_seconds() // 60)
    if lunch_in and pm_out and pm_out > lunch_in:
        total += int((_to_dt(pm_out) - _to_dt(lunch_in)).total_seconds() // 60)
    return total

@employee_bp.route("/dashboard")
def dashboard():
    today = date.today()
    rng = request.args.get("range", "today")

    # date window
    if rng == "week":
        start = today - timedelta(days=today.weekday())
        end = today
    elif rng == "month":
        start = today.replace(day=1)
        end = today
    else:
        rng = "today"
        start = today
        end = today

    # QR token
    qr = DailyQR.query.filter_by(day=today).first()
    token = qr.token if qr else None

    late_cutoff = time(8, 0)

    total_employees = Employee.query.filter_by(is_active=True).count()

    records = (
        Attendance.query
        .join(Employee, Attendance.employee_id == Employee.id)
        .filter(Attendance.day >= start, Attendance.day <= end, Employee.is_active == True)
        .order_by(Attendance.day.desc(), Employee.surname.asc(), Employee.first_name.asc())
        .all()
    )

    logged_employees = len(records)
    late_employees = sum(1 for r in records if r.day == today and r.am_in and r.am_in > late_cutoff)

    latest = (
        Attendance.query
        .filter(Attendance.day == today)
        .order_by(Attendance.id.desc())
        .first()
    )
    latest_id = latest.id if latest else None

    return render_template(
        "employee/dashboard.html",
        today=today,
        start=start,
        end=end,
        rng=rng,
        token=token,
        late_cutoff=late_cutoff,
        total_employees=total_employees,
        logged_employees=logged_employees,
        late_employees=late_employees,
        latest_id=latest_id,
        records=records,
    )

@employee_bp.route("/qr/image/<token>")
def qr_image_public(token):
    base = current_app.config["SERVER_BASE_URL"]
    scan_url = f"{base}/employee/scan?token={token}"

    img = qrcode.make(scan_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(buf.getvalue(), mimetype="image/png")

@employee_bp.route("/scan", methods=["GET", "POST"])
def scan():
    # token from qr
    token = request.args.get("token") if request.method == "GET" else request.form.get("token")
    token = (token or "").strip()

    # validate token for today
    rec = DailyQR.query.filter_by(day=date.today(), token=token).first()
    if not rec:
        return render_template_string(SCAN_HTML, ok=False, token=token, error="Invalid/expired QR. Ask admin to generate today's QR.", msg=None)

    if request.method == "GET":
        return render_template_string(SCAN_HTML, ok=True, token=token, error=None, msg=None)

    # POST: employee submits ID
    emp_code = request.form.get("employee_id", "").strip()
    emp = Employee.query.filter_by(employee_id=emp_code).first()

    if not emp:
        return render_template_string(SCAN_HTML, ok=True, token=token, error="Employee ID not found.", msg=None)

    if not emp.is_active:
        return render_template_string(SCAN_HTML, ok=True, token=token, error="Employee is deactivated. Contact admin.", msg=None)

    now = datetime.now().time()
    today = date.today()

    att = Attendance.query.filter_by(employee_id=emp.id, day=today).first()
    if not att:
        att = Attendance(employee_id=emp.id, day=today)
        att.am_in = now
        msg = f"AM IN recorded for {emp.surname}, {emp.first_name} at {now.strftime('%I:%M %p')}"
    else:
        msg = None
        if att.am_in and not att.lunch_out:
            att.lunch_out = now
            msg = f"LUNCH OUT recorded at {now.strftime('%I:%M %p')}"
        elif att.lunch_out and not att.lunch_in:
            att.lunch_in = now
            msg = f"LUNCH IN recorded at {now.strftime('%I:%M %p')}"
        elif att.lunch_in and not att.pm_out:
            att.pm_out = now
            msg = f"PM OUT recorded at {now.strftime('%I:%M %p')}"
        else:
            msg = "Attendance already completed for today."

    # compute totals
    total_minutes = _compute_minutes(att.am_in, att.lunch_out, att.lunch_in, att.pm_out)
    att.total_minutes = total_minutes
    att.overtime_minutes = max(0, total_minutes - (8 * 60))

    db.session.add(att)
    db.session.commit()

    return render_template_string(SCAN_HTML, ok=True, token=token, error=None, msg=msg)

@employee_bp.route("/my-attendance", methods=["GET"])
def my_attendance():
    emp_code = request.args.get("employee_id", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    error = None
    records = []

    if emp_code:
        emp = Employee.query.filter_by(employee_id=emp_code).first()
        if not emp:
            error = "Employee ID not found."
        else:
            q = Attendance.query.filter_by(employee_id=emp.id)

            if from_raw:
                q = q.filter(Attendance.day >= datetime.strptime(from_raw, "%Y-%m-%d").date())
            if to_raw:
                q = q.filter(Attendance.day <= datetime.strptime(to_raw, "%Y-%m-%d").date())

            records = q.order_by(Attendance.day.desc()).all()

    # token for sidebar "Scan (QR)" link
    qr = DailyQR.query.filter_by(day=date.today()).first()
    token = qr.token if qr else None

    return render_template(
        "employee/my_attendance.html",
        employee_id=emp_code,
        from_date=from_raw,
        to_date=to_raw,
        records=records,
        error=error,
        token=token,
    )

@employee_bp.route("/my-attendance/export/excel", methods=["GET"])
def my_attendance_export_excel():
    emp_code = request.args.get("employee_id", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    emp = Employee.query.filter_by(employee_id=emp_code).first()
    if not emp:
        return "Employee not found", 404

    q = Attendance.query.filter_by(employee_id=emp.id)
    if from_raw:
        q = q.filter(Attendance.day >= datetime.strptime(from_raw, "%Y-%m-%d").date())
    if to_raw:
        q = q.filter(Attendance.day <= datetime.strptime(to_raw, "%Y-%m-%d").date())

    records = q.order_by(Attendance.day.asc()).all()

    rows = []
    for r in records:
        rows.append({
            "Date": r.day.isoformat(),
            "AM In": r.am_in.strftime("%H:%M") if r.am_in else "",
            "Lunch Out": r.lunch_out.strftime("%H:%M") if r.lunch_out else "",
            "Lunch In": r.lunch_in.strftime("%H:%M") if r.lunch_in else "",
            "PM Out": r.pm_out.strftime("%H:%M") if r.pm_out else "",
            "Total Hours": round(r.total_minutes / 60, 2),
            "Overtime Hours": round(r.overtime_minutes / 60, 2),
        })

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="MyAttendance")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"my_attendance_{emp.employee_id}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@employee_bp.route("/my-attendance/export/pdf", methods=["GET"])
def my_attendance_export_pdf():
    emp_code = request.args.get("employee_id", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    emp = Employee.query.filter_by(employee_id=emp_code).first()
    if not emp:
        return "Employee not found", 404

    q = Attendance.query.filter_by(employee_id=emp.id)
    if from_raw:
        q = q.filter(Attendance.day >= datetime.strptime(from_raw, "%Y-%m-%d").date())
    if to_raw:
        q = q.filter(Attendance.day <= datetime.strptime(to_raw, "%Y-%m-%d").date())

    records = q.order_by(Attendance.day.asc()).all()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

    y = height - 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30, y, f"My Attendance - {emp.surname}, {emp.first_name} ({emp.employee_id})")
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(30, y, f"Range: {from_raw or '...'} to {to_raw or '...'}")
    y -= 20

    headers = ["Date", "AM In", "L.Out", "L.In", "PM Out", "Total", "OT"]
    col_w = [85, 70, 70, 70, 70, 60, 50]
    x0 = 30

    def draw_row(values, y_pos, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        x = x0
        for v, w in zip(values, col_w):
            c.drawString(x, y_pos, str(v))
            x += w

    draw_row(headers, y, bold=True)
    y -= 12
    c.line(30, y, width - 30, y)
    y -= 14

    for r in records:
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(30, y, "My Attendance")
            y -= 22
            draw_row(headers, y, bold=True)
            y -= 12
            c.line(30, y, width - 30, y)
            y -= 14

        row = [
            r.day.isoformat(),
            r.am_in.strftime("%H:%M") if r.am_in else "",
            r.lunch_out.strftime("%H:%M") if r.lunch_out else "",
            r.lunch_in.strftime("%H:%M") if r.lunch_in else "",
            r.pm_out.strftime("%H:%M") if r.pm_out else "",
            f"{r.total_minutes/60:.2f}",
            f"{r.overtime_minutes/60:.2f}",
        ]
        draw_row(row, y)
        y -= 14

    c.save()
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"my_attendance_{emp.employee_id}.pdf",
        mimetype="application/pdf"
    )
