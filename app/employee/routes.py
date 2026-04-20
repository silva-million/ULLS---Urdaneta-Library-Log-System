from datetime import datetime, date, time, timedelta
from flask import Blueprint, request, render_template
from flask import current_app, Response
import io, qrcode
from ..extensions import db
from ..models.employee import Employee
from ..models.attendance import Attendance
from ..models.daily_qr import DailyQR

employee_bp = Blueprint("employee", __name__, template_folder="templates")
late_cutoff = time(8, 0)

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
    token = request.args.get("token") if request.method == "GET" else request.form.get("token")
    token = (token or "").strip()

    rec = DailyQR.query.filter_by(day=date.today(), token=token).first()
    if not rec:
        return render_template("employee/scan.html", ok=False, token=token, error="Invalid/expired QR. Ask admin to generate today's QR.", msg=None)

    if request.method == "GET":
        return render_template("employee/scan.html", ok=True, token=token, error=None, msg=None)

    emp_code = request.form.get("employee_id", "").strip()
    emp = Employee.query.filter_by(employee_id=emp_code).first()

    if not emp:
        return render_template("employee/scan.html", ok=True, token=token, error="Employee ID not found.", msg=None)

    if not emp.is_active:
        return render_template("employee/scan.html", ok=True, token=token, error="Employee is deactivated. Contact admin.", msg=None)

    now = datetime.now().time()
    today = date.today()

    att = Attendance.query.filter_by(employee_id=emp.id, day=today).first()
    if not att:
        att = Attendance(employee_id=emp.id, day=today)
        att.am_in = now
        msg = f"AM IN recorded for {emp.surname}, {emp.first_name} at {now.strftime('%I:%M %p')}"
    else:
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

    total_minutes = _compute_minutes(att.am_in, att.lunch_out, att.lunch_in, att.pm_out)
    att.total_minutes = total_minutes
    att.overtime_minutes = max(0, total_minutes - (8 * 60))

    db.session.add(att)
    db.session.commit()

    return render_template("employee/scan.html", ok=True, token=token, error=None, msg=msg)