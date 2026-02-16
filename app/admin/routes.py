from flask import Blueprint, Response, request, redirect, url_for, render_template
from flask import current_app, send_file
from flask_login import login_user, logout_user, login_required
from datetime import datetime, date, time, timedelta
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
import io, secrets, qrcode
import pandas as pd

from ..extensions import db
from ..models.user import AdminUser
from ..models.attendance import Attendance
from ..models.employee import Employee
from ..models.daily_qr import DailyQR
from ..models.visitor import Visitor

admin_bp = Blueprint("admin", __name__, template_folder="templates")

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

def fmt_mdY(d):
    """
    Format: Month D, Yr  (e.g., February 13, 2026)
    Works for date objects or 'YYYY-MM-DD' strings.
    """
    if not d:
        return ""
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    return d.strftime("%B ") + str(d.day) + d.strftime(", %Y")

def fmt_mdY_time(dt):
    """
    Format: Month D, Yr hh:mm AM/PM (e.g., February 1, 2026 08:13 AM)
    """
    if not dt:
        return ""
    return dt.strftime("%B ") + str(dt.day) + dt.strftime(", %Y %I:%M %p")

def employee_export_filter_label(from_raw: str, to_raw: str, month: str):
    """
    Returns a human label that includes formatted dates.
    - month like '2026-02' -> 'February 2026'
    - from/to like 'YYYY-MM-DD' -> 'Month D, Yr'
    """
    if month:
        y, m = month.split("-")
        month_name = datetime(int(y), int(m), 1).strftime("%B %Y")
        return f"Month: {month_name}"

    if from_raw or to_raw:
        left = fmt_mdY(from_raw) if from_raw else "..."
        right = fmt_mdY(to_raw) if to_raw else "..."
        return f"From {left} to {right}"

    return "All Records"

def attendance_filter_label(from_raw: str, to_raw: str, month: str):
    if month:
        y, m = month.split("-")
        month_name = datetime(int(y), int(m), 1).strftime("%B %Y")  # e.g., February 2026
        return f"Month: {month_name}"

    if from_raw or to_raw:
        left = fmt_mdY(from_raw) if from_raw else "..."
        right = fmt_mdY(to_raw) if to_raw else "..."
        return f"From {left} to {right}"

    return "All Records"

@admin_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")

        if u == ADMIN_USERNAME and p == ADMIN_PASSWORD:
            login_user(AdminUser("admin"))
            return redirect(url_for("admin.dashboard"))
        error = "Invalid username/password"

    return render_template("admin/login.html", error=error, date=date)

#DASHBOARD ROUTE
@admin_bp.route("/dashboard")
@login_required
def dashboard():
    today = date.today()
    late_cutoff = time(8, 0)

    total_employees = Employee.query.filter_by(is_active=True).count()

    todays_records = (
        Attendance.query
        .join(Employee, Attendance.employee_id == Employee.id)
        .filter(Attendance.day == today, Employee.is_active == True)
        .order_by(Employee.surname.asc(), Employee.first_name.asc())
        .all()
    )

    logged_today = len(todays_records)
    late_today = sum(1 for r in todays_records if r.am_in and r.am_in > late_cutoff)

    # visitors today
    start_dt = datetime.combine(today, time(0, 0))
    end_dt = datetime.combine(today, time(23, 59, 59))
    visitors_today = Visitor.query.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt).order_by(Visitor.time_in.desc()).all()

    return render_template(
        "admin/dashboard.html",
        today=today,
        total_employees=total_employees,
        logged_today=logged_today,
        late_today=late_today,
        visitors_today_count=len(visitors_today),
        records=todays_records,
        visitors=visitors_today,
        late_cutoff=late_cutoff,
    )

#ADD EMPLOYEEEEEEE
@admin_bp.route("/employees", methods=["GET", "POST"])
@login_required
def employees():
    error = None

    # ADD employee
    if request.method == "POST":

        employee_id = request.form.get("employee_id", "").strip()
        surname = request.form.get("surname", "").strip()
        first_name = request.form.get("first_name", "").strip()
        middle_name = request.form.get("middle_name", "").strip() or None
        birthday_raw = request.form.get("birthday", "").strip()
        position = request.form.get("position", "").strip() or None
        status = request.form.get("status", "active").strip()

        birthday = None
        if birthday_raw:
            birthday = datetime.strptime(birthday_raw, "%Y-%m-%d").date()

        e = Employee(
            employee_id=employee_id,
            surname=surname,
            first_name=first_name,
            middle_name=middle_name,
            birthday=birthday,
            position=position,
            status=status,
            is_active=True,
        )
        db.session.add(e)
        db.session.commit()
        return redirect(url_for("admin.employees"))


    # SEARCH by surname
    q = request.args.get("q", "").strip()
    query = Employee.query
    if q:
        query = query.filter(Employee.surname.ilike(f"%{q}%"))

    employees = query.order_by(Employee.id.desc()).all()
    return render_template("admin/employees.html", employees=employees, error=error, q=q)

#TOGGLE EMPLOYEE ACTIVATE OR DEACTIVATE
@admin_bp.route("/employees/<int:emp_id>/toggle", methods=["POST"])
@login_required
def toggle_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    e.is_active = not e.is_active
    db.session.commit()
    return redirect(url_for("admin.employees"))

#DELETE EMPLOYEE
@admin_bp.route("/employees/<int:emp_id>/delete", methods=["POST"])
@login_required
def delete_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    db.session.delete(e)
    db.session.commit()
    return redirect(url_for("admin.employees"))

#EDIT EMPLOYEE
@admin_bp.route("/employees/<int:emp_id>/edit", methods=["GET", "POST"])
@login_required
def edit_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    error = None

    if request.method == "POST":
        employee_id = request.form.get("employee_id", "").strip()
        surname = request.form.get("surname", "").strip()
        first_name = request.form.get("first_name", "").strip()
        middle_name = request.form.get("middle_name", "").strip() or None
        position = request.form.get("position", "").strip() or None
        status = request.form.get("status", "active").strip()

        birthday_raw = request.form.get("birthday", "").strip()
        birthday = None
        if birthday_raw:
            birthday = datetime.strptime(birthday_raw, "%Y-%m-%d").date()

        if not employee_id or not surname or not first_name:
            error = "Employee ID, Surname, and First Name are required."
        else:
            # prevent employee_id conflicts (exclude self)
            exists = Employee.query.filter(Employee.employee_id == employee_id, Employee.id != e.id).first()
            if exists:
                error = "Employee ID already exists."
            else:
                e.employee_id = employee_id
                e.surname = surname
                e.first_name = first_name
                e.middle_name = middle_name
                e.birthday = birthday
                e.position = position
                e.status = status
                db.session.commit()
                return redirect(url_for("admin.employees"))

    return render_template("admin/employee_edit.html", e=e, error=error)

#FORM FOR EMPLOYEE LOGS
def _parse_time(val: str):
    val = (val or "").strip()
    if not val:
        return None
    return datetime.strptime(val, "%H:%M").time()

def _compute_minutes(am_in, lunch_out, lunch_in, pm_out):
    """
    Computes working minutes: (am_in -> lunch_out) + (lunch_in -> pm_out)
    Missing segments are treated as 0.
    """
    def to_dt(t):
        return datetime.combine(datetime.today().date(), t)

    total = 0
    if am_in and lunch_out and lunch_out > am_in:
        total += int((to_dt(lunch_out) - to_dt(am_in)).total_seconds() // 60)
    if lunch_in and pm_out and pm_out > lunch_in:
        total += int((to_dt(pm_out) - to_dt(lunch_in)).total_seconds() // 60)

    return total

@admin_bp.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    error = None
    msg = None

    employees = Employee.query.order_by(Employee.surname.asc()).all()

    if request.method == "POST":
        emp_id = request.form.get("employee_id", "").strip()
        day_raw = request.form.get("day", "").strip()

        if not emp_id or not day_raw:
            error = "Employee and Date are required."
        else:
            day = datetime.strptime(day_raw, "%Y-%m-%d").date()

            am_in = _parse_time(request.form.get("am_in"))
            lunch_out = _parse_time(request.form.get("lunch_out"))
            lunch_in = _parse_time(request.form.get("lunch_in"))
            pm_out = _parse_time(request.form.get("pm_out"))

            rec = Attendance.query.filter_by(employee_id=int(emp_id), day=day).first()
            if not rec:
                rec = Attendance(employee_id=int(emp_id), day=day)

            rec.am_in = am_in
            rec.lunch_out = lunch_out
            rec.lunch_in = lunch_in
            rec.pm_out = pm_out

            total_minutes = _compute_minutes(am_in, lunch_out, lunch_in, pm_out)
            overtime_minutes = max(0, total_minutes - (8 * 60))

            rec.total_minutes = total_minutes
            rec.overtime_minutes = overtime_minutes

            db.session.add(rec)
            db.session.commit()
            msg = "Attendance saved ✅"

        # --- filters ---
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    month = request.args.get("month", "").strip()

    q = Attendance.query

    # month format: YYYY-MM (e.g., 2026-02)
    if month:
        y, m = month.split("-")
        y = int(y); m = int(m)
        start = datetime(y, m, 1).date()
        # next month start
        if m == 12:
            end = datetime(y + 1, 1, 1).date()
        else:
            end = datetime(y, m + 1, 1).date()
        q = q.filter(Attendance.day >= start, Attendance.day < end)

    if from_raw:
        from_date = datetime.strptime(from_raw, "%Y-%m-%d").date()
        q = q.filter(Attendance.day >= from_date)
    else:
        from_date = None

    if to_raw:
        to_date = datetime.strptime(to_raw, "%Y-%m-%d").date()
        q = q.filter(Attendance.day <= to_date)
    else:
        to_date = None

    records = q.order_by(Attendance.day.desc(), Attendance.id.desc()).all()

    # Build month dropdown from existing Attendance days
    # (unique YYYY-MM sorted desc)
    month_rows = db.session.query(Attendance.day).distinct().all()
    month_set = set()
    for (d,) in month_rows:
        if d:
            month_set.add((d.year, d.month))

    month_list = sorted(month_set, reverse=True)

    months = []
    for y, m in month_list:
        months.append({
            "value": f"{y:04d}-{m:02d}",
            "label": f"{datetime(y, m, 1).strftime('%B %Y')}"
        })


    return render_template(
        "admin/attendance.html",
        employees=employees,
        records=records,
        error=error,
        msg=msg,
        from_date=from_raw,
        to_date=to_raw,
        month=month,
        months=months,
    )

@admin_bp.route("/employees/export/excel", methods=["GET"])
@login_required
def employees_export_excel():
    q = request.args.get("q", "").strip()
    query = Employee.query
    if q:
        query = query.filter(Employee.surname.ilike(f"%{q}%"))

    employees = query.order_by(Employee.surname.asc(), Employee.first_name.asc()).all()

    rows = []
    for e in employees:
        rows.append({
            "Employee ID": e.employee_id,
            "Surname": e.surname,
            "First Name": e.first_name,
            "Middle Name": e.middle_name or "",
            "Birthday": e.birthday.isoformat() if e.birthday else "",
            "Position": e.position or "",
            "Status": e.status,
            "Active": "Yes" if e.is_active else "No",
            "Created": e.created_at.strftime("%Y-%m-%d %H:%M:%S") if e.created_at else "",
        })

    df = pd.DataFrame(rows)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Employees")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="employees.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@admin_bp.route("/employees/export/pdf", methods=["GET"])
@login_required
def employees_export_pdf():
    q = request.args.get("q", "").strip()
    query = Employee.query
    if q:
        query = query.filter(Employee.surname.ilike(f"%{q}%"))

    employees = query.order_by(Employee.surname.asc(), Employee.first_name.asc()).all()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

    y = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30, y, "Employee Masterlist")
    y -= 22
    c.setFont("Helvetica", 10)
    c.drawString(30, y, f"Search filter: {q or 'None'}")
    y -= 20

    headers = ["EmpID", "Surname", "First", "Middle", "Birthday", "Position", "Status", "Active"]
    col_w = [80, 110, 110, 90, 80, 170, 80, 60]
    x0 = 30

    def draw_row(values, y_pos, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        x = x0
        for v, w in zip(values, col_w):
            c.drawString(x, y_pos, str(v)[:35])
            x += w

    draw_row(headers, y, bold=True)
    y -= 12
    c.line(30, y, width - 30, y)
    y -= 14

    for e in employees:
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(30, y, "Employee Masterlist")
            y -= 22
            draw_row(headers, y, bold=True)
            y -= 12
            c.line(30, y, width - 30, y)
            y -= 14

        row = [
            e.employee_id,
            e.surname,
            e.first_name,
            e.middle_name or "",
            e.birthday.isoformat() if e.birthday else "",
            e.position or "",
            e.status,
            "Yes" if e.is_active else "No",
        ]
        draw_row(row, y)
        y -= 14

    c.save()
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name="UC Library Employees.pdf",
        mimetype="application/pdf",
    )

#EXPORT EXCEL
@admin_bp.route("/attendance/export/excel", methods=["GET"])
@login_required
def attendance_export_excel():
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    month = request.args.get("month", "").strip()

    q = Attendance.query

    if month:
        y, m = month.split("-")
        y = int(y); m = int(m)
        start = datetime(y, m, 1).date()
        if m == 12:
            end = datetime(y + 1, 1, 1).date()
        else:
            end = datetime(y, m + 1, 1).date()
        q = q.filter(Attendance.day >= start, Attendance.day < end)

    if from_raw:
        from_date = datetime.strptime(from_raw, "%Y-%m-%d").date()
        q = q.filter(Attendance.day >= from_date)

    if to_raw:
        to_date = datetime.strptime(to_raw, "%Y-%m-%d").date()
        q = q.filter(Attendance.day <= to_date)

    records = q.order_by(Attendance.day.asc()).all()

    rows = []
    for r in records:
        rows.append({
            "Date": fmt_mdY(r.day),
            "Employee ID": r.employee.employee_id,
            "Surname": r.employee.surname,
            "First Name": r.employee.first_name,
            "AM In": (r.am_in.strftime("%H:%M") if r.am_in else ""),
            "Lunch Out": (r.lunch_out.strftime("%H:%M") if r.lunch_out else ""),
            "Lunch In": (r.lunch_in.strftime("%H:%M") if r.lunch_in else ""),
            "PM Out": (r.pm_out.strftime("%H:%M") if r.pm_out else ""),
            "Total Hours": round(r.total_minutes / 60, 2),
            "Overtime Hours": round(r.overtime_minutes / 60, 2),
        })

    df = pd.DataFrame(rows)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Attendance")

    output.seek(0)

    fname = "attendance.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=fname,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

#EXPORT PDF
@admin_bp.route("/attendance/export/pdf", methods=["GET"])
@login_required
def attendance_export_pdf():
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    month = request.args.get("month", "").strip()
    label = attendance_filter_label(from_raw, to_raw, month)

    q = Attendance.query

    if month:
        y, m = month.split("-")
        y = int(y); m = int(m)
        start = datetime(y, m, 1).date()
        if m == 12:
            end = datetime(y + 1, 1, 1).date()
        else:
            end = datetime(y, m + 1, 1).date()
        q = q.filter(Attendance.day >= start, Attendance.day < end)

    if from_raw:
        from_date = datetime.strptime(from_raw, "%Y-%m-%d").date()
        q = q.filter(Attendance.day >= from_date)

    if to_raw:
        to_date = datetime.strptime(to_raw, "%Y-%m-%d").date()
        q = q.filter(Attendance.day <= to_date)

    records = q.order_by(Attendance.day.asc()).all()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

    title = "Attendance Report"
    subtitle = f"Filter: {label}"

    y = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30, y, title)
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(30, y, subtitle)
    y -= 20

    headers = ["Date", "EmpID", "Surname", "First", "AM In", "Lunch Out", "PM In", "PM Out", "Total", "OT"]
    col_w = [100, 70, 110, 110, 60, 60, 60, 60, 60, 60]
    x0 = 30

    def draw_row(values, y_pos, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        x = x0
        for v, w in zip(values, col_w):
            c.drawString(x, y_pos, str(v)[:30])
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
            c.drawString(30, y, title)
            y -= 22
            draw_row(headers, y, bold=True)
            y -= 12
            c.line(30, y, width - 30, y)
            y -= 14

        row = [
            fmt_mdY(r.day),
            r.employee.employee_id,
            r.employee.surname,
            r.employee.first_name,
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
        download_name="attendance.pdf",
        mimetype="application/pdf"
    )

#EXPORT PER EMPLOYEE
@admin_bp.route("/employees/<int:emp_id>/attendance", methods=["GET"])
@login_required
def employee_attendance(emp_id):
    emp = Employee.query.get_or_404(emp_id)

    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    q = Attendance.query.filter_by(employee_id=emp.id)
    if from_raw:
        q = q.filter(Attendance.day >= datetime.strptime(from_raw, "%Y-%m-%d").date())
    if to_raw:
        q = q.filter(Attendance.day <= datetime.strptime(to_raw, "%Y-%m-%d").date())

    records = q.order_by(Attendance.day.desc()).all()

    return render_template(
        "admin/employee_attendance.html",
        emp=emp,
        records=records,
        from_date=from_raw,
        to_date=to_raw,
    )

#EXPORT PER EMPLOYEE BY EXCEL
@admin_bp.route("/employees/<int:emp_id>/attendance/export/excel", methods=["GET"])
@login_required
def employee_attendance_export_excel(emp_id):
    emp = Employee.query.get_or_404(emp_id)

    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    
    label = employee_export_filter_label(from_raw, to_raw, month="")
    safe_label = label.replace(" ", "_").replace(":", "").replace("/", "-").replace(",", "")

    q = Attendance.query.filter_by(employee_id=emp.id)
    if from_raw:
        q = q.filter(Attendance.day >= datetime.strptime(from_raw, "%Y-%m-%d").date())
    if to_raw:
        q = q.filter(Attendance.day <= datetime.strptime(to_raw, "%Y-%m-%d").date())

    records = q.order_by(Attendance.day.asc()).all()

    rows = []
    for r in records:
        rows.append({
            "Date": fmt_mdY(r.day),
            "Employee ID": emp.employee_id,
            "Surname": emp.surname,
            "First Name": emp.first_name,
            "AM In": (r.am_in.strftime("%H:%M") if r.am_in else ""),
            "Lunch Out": (r.lunch_out.strftime("%H:%M") if r.lunch_out else ""),
            "Lunch In": (r.lunch_in.strftime("%H:%M") if r.lunch_in else ""),
            "PM Out": (r.pm_out.strftime("%H:%M") if r.pm_out else ""),
            "Total Hours": round(r.total_minutes / 60, 2),
            "Overtime Hours": round(r.overtime_minutes / 60, 2),
        })

    df = pd.DataFrame(rows)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        meta = pd.DataFrame([{"Filter": label}])
        meta.to_excel(writer, index=False, sheet_name="Attendance", startrow=0)
        df.to_excel(writer, index=False, sheet_name="Attendance", startrow=2)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"attendance_{emp.employee_id}_{safe_label}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


#EXPORT PER EMPLOYEE BY PDF
@admin_bp.route("/employees/<int:emp_id>/attendance/export/pdf", methods=["GET"])
@login_required
def employee_attendance_export_pdf(emp_id):
    emp = Employee.query.get_or_404(emp_id)

    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    
    label = employee_export_filter_label(from_raw, to_raw, month="")
    safe_label = label.replace(" ", "_").replace(":", "").replace("/", "-").replace(",", "")

    q = Attendance.query.filter_by(employee_id=emp.id)
    if from_raw:
        q = q.filter(Attendance.day >= datetime.strptime(from_raw, "%Y-%m-%d").date())
    if to_raw:
        q = q.filter(Attendance.day <= datetime.strptime(to_raw, "%Y-%m-%d").date())

    records = q.order_by(Attendance.day.asc()).all()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

    title = f"Attendance - {emp.surname}, {emp.first_name} ({emp.employee_id})"
    y = height - 40
    c.setFont("Helvetica-Bold", 12)
    c.drawString(30, y, title)
    y -= 18
    c.setFont("Helvetica", 10)
    c.drawString(30, y, f"Filter: {label}")
    y -= 20

    headers = ["Date", "AM In", "L.Out", "L.In", "PM Out", "Total", "OT"]
    col_w = [120, 70, 70, 70, 70, 60, 50]
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
            c.drawString(30, y, title)
            y -= 22
            draw_row(headers, y, bold=True)
            y -= 12
            c.line(30, y, width - 30, y)
            y -= 14

        row = [
            fmt_mdY(r.day),
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
        download_name=f"attendance_{emp.employee_id}_{safe_label}.pdf",
        mimetype="application/pdf"
    )

#GENERATE QR DAILY
@admin_bp.route("/qr", methods=["GET", "POST"])
@login_required
def qr_today():
    today = date.today()

    rec = DailyQR.query.filter_by(day=today).first()

    if request.method == "POST":
    # generate ONLY ONCE per day
        if rec:
            # already exists for today; do not change token
            pass
        else:
            token = secrets.token_urlsafe(24)
            rec = DailyQR(day=today, token=token)
            db.session.add(rec)
            db.session.commit()

    rec = DailyQR.query.filter_by(day=today).first()
    token = rec.token if rec else None

    scan_url = None
    if token:
        # employee endpoint we’ll create next step
        base = current_app.config["SERVER_BASE_URL"]
        scan_url = f"{base}/employee/scan?token={token}"

    return render_template("admin/qr_today.html", day=today, token=token, scan_url=scan_url)

@admin_bp.route("/qr/image/<token>")
@login_required
def qr_image(token):
    base = current_app.config["SERVER_BASE_URL"]
    scan_url = f"{base}/employee/scan?token={token}"

    img = qrcode.make(scan_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(buf.getvalue(), mimetype="image/png")

@admin_bp.route("/visitors/<int:visitor_id>/timeout", methods=["POST"])
@login_required
def visitor_timeout(visitor_id):
    v = Visitor.query.get_or_404(visitor_id)
    if not v.time_out:
        v.time_out = datetime.now()
        db.session.commit()
    return redirect(url_for("admin.visitors"))

def _visitor_filter_label():
    rng = request.args.get("range", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    if rng:
        today = date.today()
        if rng == "week":
            start = today - timedelta(days=today.weekday())
            end = today
            q = q.filter(Attendance.day >= start, Attendance.day <= end)
        elif rng == "month":
            start = today.replace(day=1)
            end = today
            q = q.filter(Attendance.day >= start, Attendance.day <= end)
        else:
            # today
            q = q.filter(Attendance.day == today)


    return "All Records"


#EXPORT VISITOR BY EXCEL
@admin_bp.route("/visitors/export/excel", methods=["GET"])
@login_required
def visitors_export_excel():
    rng = request.args.get("range", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    q = Visitor.query

    if rng:
        today = date.today()
        if rng == "week":
            start = today - timedelta(days=today.weekday())
            end = today
        elif rng == "month":
            start = today.replace(day=1)
            end = today
        else:
            start = today
            end = today

        start_dt = datetime.combine(start, time(0, 0))
        end_dt = datetime.combine(end, time(23, 59, 59))
        q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)

    if from_raw:
        start_dt = datetime.combine(datetime.strptime(from_raw, "%Y-%m-%d").date(), time(0, 0))
        q = q.filter(Visitor.time_in >= start_dt)

    if to_raw:
        end_dt = datetime.combine(datetime.strptime(to_raw, "%Y-%m-%d").date(), time(23, 59, 59))
        q = q.filter(Visitor.time_in <= end_dt)

    visitors = q.order_by(Visitor.time_in.desc()).all()

    rows = []
    for v in visitors:
        rows.append({
            "Name": v.full_name,
            "Contact": v.contact or "",
            "Purpose": v.purpose or "",
            "Time In": fmt_mdY_time(v.time_in),
            "Time Out": fmt_mdY_time(v.time_out),
        })

    df = pd.DataFrame(rows)

    label = _visitor_filter_label()
    safe_label = label.replace(" ", "_").replace(":", "").replace("/", "-")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        meta = pd.DataFrame([{"Filter": label}])
        meta.to_excel(writer, index=False, sheet_name="Visitors", startrow=0)
        df.to_excel(writer, index=False, sheet_name="Visitors", startrow=2)

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"visitors_{safe_label}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


#EXPORT VISITOR BY PDF
@admin_bp.route("/visitors/export/pdf", methods=["GET"])
@login_required
def visitors_export_pdf():
    rng = request.args.get("range", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    q = Visitor.query

    if rng:
        today = date.today()
        if rng == "week":
            start = today - timedelta(days=today.weekday())
            end = today
        elif rng == "month":
            start = today.replace(day=1)
            end = today
        else:
            start = today
            end = today

        start_dt = datetime.combine(start, time(0, 0))
        end_dt = datetime.combine(end, time(23, 59, 59))
        q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)

    if from_raw:
        start_dt = datetime.combine(datetime.strptime(from_raw, "%Y-%m-%d").date(), time(0, 0))
        q = q.filter(Visitor.time_in >= start_dt)

    if to_raw:
        end_dt = datetime.combine(datetime.strptime(to_raw, "%Y-%m-%d").date(), time(23, 59, 59))
        q = q.filter(Visitor.time_in <= end_dt)

    visitors = q.order_by(Visitor.time_in.desc()).all()


    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

    y = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(30, y, "Visitor Log Report")
    y -= 24

    label = _visitor_filter_label()
    c.setFont("Helvetica", 10)
    c.drawString(30, y, f"Filter: {label}")
    y -= 18


    headers = ["Name", "Contact", "Purpose", "Time In", "Time Out"]
    col_w = [170, 110, 210, 190, 190]
    x0 = 30

    def draw_row(values, y_pos, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        x = x0
        for v, w in zip(values, col_w):
            c.drawString(x, y_pos, str(v)[:40])
            x += w

    draw_row(headers, y, bold=True)
    y -= 12
    c.line(30, y, width - 30, y)
    y -= 14

    for v in visitors:
        if y < 40:
            c.showPage()
            y = height - 40
            c.setFont("Helvetica-Bold", 12)
            c.drawString(30, y, "Visitor Log Report")
            y -= 22
            draw_row(headers, y, bold=True)
            y -= 12
            c.line(30, y, width - 30, y)
            y -= 14

        row = [
            v.full_name,
            v.contact or "",
            v.purpose or "",
            fmt_mdY_time(v.time_in),
            fmt_mdY_time(v.time_out),
        ]
        draw_row(row, y)
        y -= 14

    c.save()
    buf.seek(0)

    safe_label = label.replace(" ", "_").replace(":", "").replace("/", "-")
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"visitors_{safe_label}.pdf",
        mimetype="application/pdf"
    )


#EXPORT VISITORS DATE FILTERATION
@admin_bp.route("/visitors", methods=["GET"])
@login_required
def visitors():
    rng = request.args.get("range", "").strip()
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()

    # default no filter -> show latest
    q = Visitor.query

    if rng:
        today = date.today()
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

        start_dt = datetime.combine(start, time(0, 0))
        end_dt = datetime.combine(end, time(23, 59, 59))
        q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)

    if from_raw:
        start_dt = datetime.combine(datetime.strptime(from_raw, "%Y-%m-%d").date(), time(0, 0))
        q = q.filter(Visitor.time_in >= start_dt)

    if to_raw:
        end_dt = datetime.combine(datetime.strptime(to_raw, "%Y-%m-%d").date(), time(23, 59, 59))
        q = q.filter(Visitor.time_in <= end_dt)

    visitors = q.order_by(Visitor.time_in.desc()).limit(500).all()

    return render_template(
        "admin/visitors.html",
        visitors=visitors,
        from_date=from_raw,
        to_date=to_raw,
    )


#LOGOUT BUTTON
@admin_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))
