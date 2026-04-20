from flask import Blueprint, Response, request, redirect, url_for, render_template, flash
from flask import current_app, send_file
from flask_login import login_user, logout_user, login_required
from datetime import datetime, date, time, timedelta
from reportlab.lib.pagesizes import LEGAL, landscape
from reportlab.pdfgen import canvas
import io, secrets, qrcode, calendar, os
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

def fmt_12h(t):
    """Format a time/datetime to 12-hour like 08:05 AM. Returns '' if None."""
    if not t:
        return ""
    return t.strftime("%I:%M %p")

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
        flash("Employee added successfully.", "success")
        return redirect(url_for("admin.employees"))


    # SEARCH by surname
    q = request.args.get("q", "").strip()
    query = Employee.query
    if q:
        query = query.filter(Employee.surname.ilike(f"%{q}%"))

    employees = query.order_by(Employee.surname.asc(), Employee.first_name.asc()).all()

    ojt_keywords = {"ojt", "immersion"}

    staff_employees = []
    ojt_employees = []

    for e in employees:
        pos = (e.position or "").strip().lower()
        if pos in ojt_keywords:
            ojt_employees.append(e)
        else:
            staff_employees.append(e)

    return render_template(
        "admin/employees.html",
        staff_employees=staff_employees,
        ojt_employees=ojt_employees,
        error=error,
        q=q
    )

#TOGGLE EMPLOYEE ACTIVATE OR DEACTIVATE
@admin_bp.route("/employees/<int:emp_id>/toggle", methods=["POST"])
@login_required
def toggle_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    e.is_active = not e.is_active
    db.session.commit()
    flash("Employee status updated.", "success")
    return redirect(url_for("admin.employees"))

#DELETE EMPLOYEE
@admin_bp.route("/employees/<int:emp_id>/delete", methods=["POST"])
@login_required
def delete_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    db.session.delete(e)
    db.session.commit()
    flash("Employee deleted.", "success")
    return redirect(url_for("admin.employees"))

#EDIT EMPLOYEE
@admin_bp.route("/employees/<int:emp_id>/edit", methods=["POST"])
@login_required
def edit_employee(emp_id):
    e = Employee.query.get_or_404(emp_id)
    error = None

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
        flash("Employee ID, Surname, and First Name are required.", "error")
        return redirect(url_for("admin.employees"))

    exists = Employee.query.filter(Employee.employee_id == employee_id, Employee.id != e.id).first()
    if exists:
        flash("Employee ID already exists.", "error")
        return redirect(url_for("admin.employees"))

    e.employee_id = employee_id
    e.surname = surname
    e.first_name = first_name
    e.middle_name = middle_name
    e.birthday = birthday
    e.position = position
    e.status = status

    db.session.commit()
    flash(f"{e.first_name} {e.surname} updated successfully.", "success")
    return redirect(url_for("admin.employees"))

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

#ATTENDANCE PAGE ROUTE
@admin_bp.route("/attendance", methods=["GET", "POST"])
@login_required
def attendance():
    error = None
    msg = None

    employees = Employee.query.order_by(Employee.surname.asc()).all()

    # ---- SAVE (POST) ----
    if request.method == "POST":
        emp_id = request.form.get("employee_id", "").strip()
        day_raw = request.form.get("day", "").strip()

        if not emp_id or not day_raw:
            flash("Employee and Date are required.", "error")
            return redirect(url_for("admin.attendance"))
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
            flash("Attendance saved successfully.", "success")
            return redirect(url_for("admin.attendance"))

    # ---- FILTERS (GET) ----
    rng = request.args.get("range", "").strip()  # today | week | month
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    month = request.args.get("month", "").strip()
    selected_day = request.args.get("day", "").strip()

    q = Attendance.query

    # quick range
    if rng and not (month or from_raw or to_raw):
        today = date.today()
        if rng == "today":
            q = q.filter(Attendance.day == today)
        elif rng == "week":
            start = today - timedelta(days=today.weekday())
            end = today
            q = q.filter(Attendance.day >= start, Attendance.day <= end)
        elif rng == "month":
            start = today.replace(day=1)
            end = today
            q = q.filter(Attendance.day >= start, Attendance.day <= end)

    # month filter
    if month:
        y, m = month.split("-")
        y = int(y)
        m = int(m)
        start = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1)
        else:
            end = date(y, m + 1, 1)
        q = q.filter(Attendance.day >= start, Attendance.day < end)

    # from / to filters
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

    # ---- GROUP BY DAY ----
    records_by_day = {}
    for r in records:
        records_by_day.setdefault(r.day, []).append(r)

    day_list = sorted(records_by_day.keys(), reverse=True)

    # selected day logic
    selected_day_date = None
    if selected_day:
        try:
            selected_day_date = datetime.strptime(selected_day, "%Y-%m-%d").date()
        except ValueError:
            selected_day_date = None

    if not selected_day_date and day_list:
        selected_day_date = day_list[0]

    selected_records = records_by_day.get(selected_day_date, []) if selected_day_date else []

    # summaries for selected day
    late_cutoff = time(8, 0)
    selected_present = len(selected_records)
    selected_late = sum(1 for r in selected_records if r.am_in and r.am_in > late_cutoff)
    selected_ot = sum(1 for r in selected_records if (r.overtime_minutes or 0) > 0)

        # ---- CALENDAR DATA ----
    view_month = request.args.get("view_month", "").strip()  # YYYY-MM

    if view_month:
        try:
            view_year, view_mon = map(int, view_month.split("-"))
            calendar_anchor = date(view_year, view_mon, 1)
        except ValueError:
            calendar_anchor = selected_day_date or date.today()
            calendar_anchor = calendar_anchor.replace(day=1)
    else:
        calendar_anchor = selected_day_date or date.today()
        calendar_anchor = calendar_anchor.replace(day=1)

    cal = calendar.Calendar(firstweekday=6)  # Sunday
    month_days = list(cal.itermonthdates(calendar_anchor.year, calendar_anchor.month))

    month_matrix = [month_days[i:i+7] for i in range(0, len(month_days), 7)]

    # days that have attendance records
    record_days = set(db.session.query(Attendance.day).distinct().all())
    record_days = {d[0] for d in record_days if d[0]}

    prev_month = (calendar_anchor.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (calendar_anchor.replace(day=28) + timedelta(days=4)).replace(day=1)

    # month dropdown
    month_rows = db.session.query(Attendance.day).distinct().all()
    month_set = set()
    for (d,) in month_rows:
        if d:
            month_set.add((d.year, d.month))

    month_list = sorted(month_set, reverse=True)
    months = [
        {"value": f"{y:04d}-{m:02d}", "label": datetime(y, m, 1).strftime("%B %Y")}
        for y, m in month_list
    ]

    return render_template(
        "admin/attendance.html",
        employees=employees,
        records=records,
        records_by_day=records_by_day,
        day_list=day_list,
        selected_day=selected_day_date,
        selected_records=selected_records,
        selected_present=selected_present,
        selected_late=selected_late,
        selected_ot=selected_ot,
        calendar_anchor=calendar_anchor,
        month_matrix=month_matrix,
        record_days=record_days,
        prev_month=prev_month,
        next_month=next_month,
        error=error,
        msg=msg,
        from_date=from_raw,
        to_date=to_raw,
        month=month,
        months=months,
        rng=rng,
    )

#EXPORT EMPLOYEE LIST AS PDF
@admin_bp.route("/employees/export/pdf", methods=["GET"])
@login_required
def employees_export_pdf():
    q = request.args.get("q", "").strip()

    query = Employee.query
    if q:
        query = query.filter(Employee.surname.ilike(f"%{q}%"))

    employees = query.order_by(Employee.surname.asc(), Employee.first_name.asc()).all()

    # classify employees
    staff_employees = []
    ojt_employees = []

    for e in employees:
        pos = (e.position or "").strip().lower()
        if "ojt" in pos or "immersion" in pos:
            ojt_employees.append(e)
        else:
            staff_employees.append(e)

    import os
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import legal, landscape
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(legal))
    width, height = landscape(legal)

    current_year = datetime.now().year

    library_logo_path = os.path.join(current_app.root_path, "static", "img", "library_logo.png")
    city_logo_path = os.path.join(current_app.root_path, "static", "img", "urdaneta_logo.png")

    margin_x = 32
    top_y = height - 28
    bottom_margin = 40
    table_x = margin_x
    usable_width = width - (margin_x * 2)

    headers = ["Emp ID", "Surname", "First Name", "Middle Name", "Birthday", "Position", "Status", "Active"]

    col_w = [
        usable_width * 0.10,
        usable_width * 0.15,
        usable_width * 0.15,
        usable_width * 0.14,
        usable_width * 0.12,
        usable_width * 0.16,
        usable_width * 0.10,
        usable_width * 0.08,
    ]

    header_h = 28
    base_row_h = 22
    cell_pad_x = 6
    cell_pad_y = 6
    body_font = "Helvetica"
    body_font_size = 8.5

    def wrap_text(text, max_width, font_name="Helvetica", font_size=8.5):
        text = str(text or "")
        if not text:
            return [""]

        words = text.split()
        if not words:
            return [""]

        lines = []
        current = words[0]

        for word in words[1:]:
            trial = current + " " + word
            if stringWidth(trial, font_name, font_size) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)

        final_lines = []
        for line in lines:
            if stringWidth(line, font_name, font_size) <= max_width:
                final_lines.append(line)
            else:
                chunk = ""
                for ch in line:
                    trial = chunk + ch
                    if stringWidth(trial, font_name, font_size) <= max_width:
                        chunk = trial
                    else:
                        if chunk:
                            final_lines.append(chunk)
                        chunk = ch
                if chunk:
                    final_lines.append(chunk)

        return final_lines

    def draw_header():
        header_y = top_y
        center_x = width / 2

        lib_w, lib_h = 46, 46
        city_w, city_h = 70, 45

        left_logo_x = center_x - 185
        right_logo_x = center_x + 130
        logo_y_lib = header_y - 38
        logo_y_city = header_y - 40

        if os.path.exists(library_logo_path):
            c.drawImage(
                ImageReader(library_logo_path),
                left_logo_x, logo_y_lib,
                width=lib_w, height=lib_h,
                preserveAspectRatio=True, mask='auto'
            )

        if os.path.exists(city_logo_path):
            c.drawImage(
                ImageReader(city_logo_path),
                right_logo_x, logo_y_city,
                width=city_w, height=city_h,
                preserveAspectRatio=True, mask='auto'
            )

        c.setFillColor(colors.HexColor("#2148FF"))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(center_x, header_y, "URDANETA CITY PUBLIC LIBRARY")

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(center_x, header_y - 18, "UCPL Employee/Staff List")

        c.setFont("Helvetica", 9)
        c.drawCentredString(center_x, header_y - 32, f"Year: {current_year}")
        c.drawCentredString(center_x, header_y - 44, f"Search filter: {q or 'None'}")

        c.setStrokeColor(colors.HexColor("#2148FF"))
        c.setLineWidth(1.2)
        c.line(margin_x, header_y - 56, width - margin_x, header_y - 56)

        return header_y - 82

    def draw_footer(page_no):
        footer_y = 18

        c.setStrokeColor(colors.HexColor("#D6E2FF"))
        c.setLineWidth(0.8)
        c.line(margin_x, footer_y + 12, width - margin_x, footer_y + 12)

        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#2148FF"))
        c.drawString(margin_x, footer_y, "ULLS - Urdaneta Library Log System")

        c.setFillColor(colors.black)
        c.drawRightString(width - margin_x, footer_y, f"Page {page_no}")

    def draw_section_title(y, title, count):
        c.setFillColor(colors.HexColor("#2148FF"))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(table_x, y, title)

        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawRightString(table_x + sum(col_w), y, f"{count} record(s)")

        c.setStrokeColor(colors.HexColor("#BFD2FF"))
        c.setLineWidth(0.8)
        c.line(table_x, y - 4, table_x + sum(col_w), y - 4)

        return y - 14

    def draw_table_header(y):
        c.setFillColor(colors.HexColor("#2148FF"))
        c.roundRect(table_x, y - header_h, sum(col_w), header_h, 7, fill=1, stroke=0)

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)

        x = table_x
        for head, w in zip(headers, col_w):
            c.drawString(x + 7, y - 18, head)
            x += w

        return y - header_h

    def measure_row(values):
        wrapped = []
        max_lines = 1

        for val, w in zip(values, col_w):
            lines = wrap_text(val, w - (cell_pad_x * 2), body_font, body_font_size)
            wrapped.append(lines)
            max_lines = max(max_lines, len(lines))

        row_h = max(base_row_h, (max_lines * 10) + (cell_pad_y * 2))
        return wrapped, row_h

    def draw_table_row(y, values, fill_color):
        wrapped, row_h = measure_row(values)

        c.setFillColor(fill_color)
        c.rect(table_x, y - row_h, sum(col_w), row_h, fill=1, stroke=0)

        c.setStrokeColor(colors.HexColor("#D8E3FF"))
        c.setLineWidth(0.6)

        x = table_x
        for w in col_w:
            c.line(x, y, x, y - row_h)
            x += w
        c.line(table_x + sum(col_w), y, table_x + sum(col_w), y - row_h)
        c.line(table_x, y - row_h, table_x + sum(col_w), y - row_h)

        c.setFillColor(colors.black)
        c.setFont(body_font, body_font_size)

        x = table_x
        for lines, w in zip(wrapped, col_w):
            text_y = y - cell_pad_y - 8
            for line in lines:
                c.drawString(x + cell_pad_x, text_y, line)
                text_y -= 10
            x += w

        return y - row_h

    def start_new_page(page_no):
        c.showPage()
        y = draw_header()
        draw_footer(page_no)
        return y

    def render_section(y, page_no, title, data):
        if y < bottom_margin + 60:
            page_no += 1
            y = start_new_page(page_no)

        y = draw_section_title(y, title, len(data))

        if not data:
            c.setFont("Helvetica", 9)
            c.setFillColor(colors.black)
            c.drawString(table_x, y, "No records found.")
            return y - 20, page_no

        y = draw_table_header(y)

        for idx, e in enumerate(data):
            birthday_text = fmt_mdY(e.birthday) if e.birthday else ""

            row = [
                e.employee_id,
                e.surname,
                e.first_name,
                e.middle_name or "",
                birthday_text,
                e.position or "",
                (e.status or "").replace("_", " ").title(),
                "Yes" if e.is_active else "No",
            ]

            _, needed_h = measure_row(row)
            if y - needed_h < bottom_margin + 16:
                page_no += 1
                y = start_new_page(page_no)
                y = draw_section_title(y, title + " (cont.)", len(data))
                y = draw_table_header(y)

            fill = colors.white if idx % 2 == 0 else colors.HexColor("#F6FAFF")
            y = draw_table_row(y, row, fill)

        return y - 14, page_no

    page_no = 1
    y = draw_header()
    draw_footer(page_no)

    y, page_no = render_section(y, page_no, "Library Staff", staff_employees)
    y, page_no = render_section(y, page_no, "Immersion / OJT", ojt_employees)

    c.save()
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"UCPL_Employee_Staff_List_{current_year}.pdf",
        mimetype="application/pdf",
    )

#EXPORT ATTENDANCE PDF
@admin_bp.route("/attendance/export/pdf", methods=["GET"])
@login_required
def attendance_export_pdf():
    import calendar
    import os
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import legal, landscape
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth

    export_type = request.args.get("export_type", "").strip()

    day = request.args.get("day", "").strip()
    month = request.args.get("month", "").strip()   # YYYY-MM
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    year = request.args.get("year", "").strip()

    q = Attendance.query
    title = "Attendance Report"
    file_suffix = "attendance_report"

    # ---- FILTER LOGIC BASED ON EXPORT TYPE ----
    if export_type == "day" and day:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        q = q.filter(Attendance.day == d)
        title = f"Daily Attendance ({d.strftime('%B %d, %Y')})"
        file_suffix = f"Daily_Attendance_{d.strftime('%Y_%m_%d')}"

    elif export_type == "month" and month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        end = date(y, m, calendar.monthrange(y, m)[1])
        q = q.filter(Attendance.day >= start, Attendance.day <= end)
        title = f"Monthly Attendance ({start.strftime('%B %Y')})"
        file_suffix = f"Monthly_Attendance_{start.strftime('%Y_%m')}"

    elif export_type == "range" and from_raw and to_raw:
        start = datetime.strptime(from_raw, "%Y-%m-%d").date()
        end = datetime.strptime(to_raw, "%Y-%m-%d").date()
        q = q.filter(Attendance.day >= start, Attendance.day <= end)
        title = f"Attendance ({start.strftime('%B %d, %Y')} to {end.strftime('%B %d, %Y')})"
        file_suffix = f"Attendance_{start.strftime('%Y_%m_%d')}_to_{end.strftime('%Y_%m_%d')}"

    elif export_type == "year" and year:
        y = int(year)
        start = date(y, 1, 1)
        end = date(y, 12, 31)
        q = q.filter(Attendance.day >= start, Attendance.day <= end)
        title = f"Yearly Attendance ({y})"
        file_suffix = f"Yearly_Attendance_{y}"

    elif day:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        q = q.filter(Attendance.day == d)
        title = f"Daily Attendance ({d.strftime('%B %d, %Y')})"
        file_suffix = f"Daily_Attendance_{d.strftime('%Y_%m_%d')}"

    records = q.order_by(Attendance.day.asc(), Attendance.id.asc()).all()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(legal))
    width, height = landscape(legal)

    current_year = datetime.now().year

    library_logo_path = os.path.join(current_app.root_path, "static", "img", "library_logo.png")
    city_logo_path = os.path.join(current_app.root_path, "static", "img", "urdaneta_logo.png")

    margin_x = 32
    top_y = height - 28
    bottom_margin = 40
    table_x = margin_x
    usable_width = width - (margin_x * 2)

    headers = ["Date", "Employee", "AM In", "Lunch Out", "Lunch In", "PM Out", "Total", "OT"]

    col_w = [
        usable_width * 0.14,  # Date
        usable_width * 0.26,  # Employee
        usable_width * 0.10,  # AM In
        usable_width * 0.12,  # Lunch Out
        usable_width * 0.12,  # Lunch In
        usable_width * 0.10,  # PM Out
        usable_width * 0.08,  # Total
        usable_width * 0.08,  # OT
    ]

    header_h = 28
    base_row_h = 22
    cell_pad_x = 6
    cell_pad_y = 6
    body_font = "Helvetica"
    body_font_size = 8.5

    def wrap_text(text, max_width, font_name="Helvetica", font_size=8.5):
        text = str(text or "")
        if not text:
            return [""]

        words = text.split()
        if not words:
            return [""]

        lines = []
        current = words[0]

        for word in words[1:]:
            trial = current + " " + word
            if stringWidth(trial, font_name, font_size) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)

        final_lines = []
        for line in lines:
            if stringWidth(line, font_name, font_size) <= max_width:
                final_lines.append(line)
            else:
                chunk = ""
                for ch in line:
                    trial = chunk + ch
                    if stringWidth(trial, font_name, font_size) <= max_width:
                        chunk = trial
                    else:
                        if chunk:
                            final_lines.append(chunk)
                        chunk = ch
                if chunk:
                    final_lines.append(chunk)

        return final_lines

    def draw_header():
        header_y = top_y
        center_x = width / 2

        lib_w, lib_h = 46, 46
        city_w, city_h = 70, 45

        left_logo_x = center_x - 185
        right_logo_x = center_x + 130
        logo_y_lib = header_y - 38
        logo_y_city = header_y - 40

        if os.path.exists(library_logo_path):
            c.drawImage(
                ImageReader(library_logo_path),
                left_logo_x, logo_y_lib,
                width=lib_w, height=lib_h,
                preserveAspectRatio=True, mask='auto'
            )

        if os.path.exists(city_logo_path):
            c.drawImage(
                ImageReader(city_logo_path),
                right_logo_x, logo_y_city,
                width=city_w, height=city_h,
                preserveAspectRatio=True, mask='auto'
            )

        c.setFillColor(colors.HexColor("#2148FF"))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(center_x, header_y, "URDANETA CITY PUBLIC LIBRARY")

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(center_x, header_y - 18, title)

        c.setFont("Helvetica", 9)
        c.drawCentredString(center_x, header_y - 32, f"Year: {current_year}")

        c.setStrokeColor(colors.HexColor("#2148FF"))
        c.setLineWidth(1.2)
        c.line(margin_x, header_y - 56, width - margin_x, header_y - 56)

        return header_y - 82

    def draw_footer(page_no):
        footer_y = 18

        c.setStrokeColor(colors.HexColor("#D6E2FF"))
        c.setLineWidth(0.8)
        c.line(margin_x, footer_y + 12, width - margin_x, footer_y + 12)

        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#2148FF"))
        c.drawString(margin_x, footer_y, "ULLS - Urdaneta Library Log System")

        c.setFillColor(colors.black)
        c.drawRightString(width - margin_x, footer_y, f"Page {page_no}")

    def draw_table_header(y):
        c.setFillColor(colors.HexColor("#2148FF"))
        c.roundRect(table_x, y - header_h, sum(col_w), header_h, 7, fill=1, stroke=0)

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)

        x = table_x
        for head, w in zip(headers, col_w):
            c.drawString(x + 7, y - 18, head)
            x += w

        return y - header_h

    def measure_row(values):
        wrapped = []
        max_lines = 1

        for val, w in zip(values, col_w):
            lines = wrap_text(val, w - (cell_pad_x * 2), body_font, body_font_size)
            wrapped.append(lines)
            max_lines = max(max_lines, len(lines))

        row_h = max(base_row_h, (max_lines * 10) + (cell_pad_y * 2))
        return wrapped, row_h

    def draw_table_row(y, values, fill_color):
        wrapped, row_h = measure_row(values)

        c.setFillColor(fill_color)
        c.rect(table_x, y - row_h, sum(col_w), row_h, fill=1, stroke=0)

        c.setStrokeColor(colors.HexColor("#D8E3FF"))
        c.setLineWidth(0.6)

        x = table_x
        for w in col_w:
            c.line(x, y, x, y - row_h)
            x += w
        c.line(table_x + sum(col_w), y, table_x + sum(col_w), y - row_h)
        c.line(table_x, y - row_h, table_x + sum(col_w), y - row_h)

        c.setFillColor(colors.black)
        c.setFont(body_font, body_font_size)

        x = table_x
        for lines, w in zip(wrapped, col_w):
            text_y = y - cell_pad_y - 8
            for line in lines:
                c.drawString(x + cell_pad_x, text_y, line)
                text_y -= 10
            x += w

        return y - row_h

    def draw_summary(y):
        c.setFillColor(colors.HexColor("#2148FF"))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(table_x, y, "Attendance Records")

        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawRightString(table_x + sum(col_w), y, f"{len(records)} record(s)")

        c.setStrokeColor(colors.HexColor("#BFD2FF"))
        c.setLineWidth(0.8)
        c.line(table_x, y - 4, table_x + sum(col_w), y - 4)

        return y - 14

    def start_new_page(page_no):
        c.showPage()
        y = draw_header()
        draw_footer(page_no)
        y = draw_summary(y)
        y = draw_table_header(y)
        return y

    page_no = 1
    y = draw_header()
    draw_footer(page_no)
    y = draw_summary(y)
    y = draw_table_header(y)

    if not records:
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        c.drawString(table_x, y - 10, "No attendance records found.")
    else:
        for idx, r in enumerate(records):
            row = [
                r.day.strftime("%B %d, %Y"),
                f"{r.employee.surname}, {r.employee.first_name}",
                r.am_in.strftime("%I:%M %p") if r.am_in else "-",
                r.lunch_out.strftime("%I:%M %p") if r.lunch_out else "-",
                r.lunch_in.strftime("%I:%M %p") if r.lunch_in else "-",
                r.pm_out.strftime("%I:%M %p") if r.pm_out else "-",
                f"{(r.total_minutes or 0)/60:.2f}",
                f"{(r.overtime_minutes or 0)/60:.2f}",
            ]

            _, needed_h = measure_row(row)
            if y - needed_h < bottom_margin + 16:
                page_no += 1
                y = start_new_page(page_no)

            fill = colors.white if idx % 2 == 0 else colors.HexColor("#F6FAFF")
            y = draw_table_row(y, row, fill)

    c.save()
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{file_suffix}.pdf",
        mimetype="application/pdf",
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
            fmt_12h(r.am_in),
            fmt_12h(r.lunch_out),
            fmt_12h(r.lunch_in),
            fmt_12h(r.pm_out),
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
        flash("Visitor timed out successfully.", "success")
    return redirect(url_for("admin.visitors"))

@admin_bp.route("/visitors", methods=["GET"])
@login_required
def visitors():
    error = None

    rng = request.args.get("range", "").strip()
    selected_day = request.args.get("day", "").strip()
    view_month = request.args.get("view_month", "").strip()  # YYYY-MM

    q = Visitor.query

    # quick range filters
    if rng and not selected_day:
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

    visitors = q.order_by(Visitor.time_in.desc()).limit(500).all()

    # group by day
    visitors_by_day = {}
    for v in visitors:
        if v.time_in:
            d = v.time_in.date()
            visitors_by_day.setdefault(d, []).append(v)

    day_list = sorted(visitors_by_day.keys(), reverse=True)

    selected_day_date = None
    if selected_day:
        try:
            selected_day_date = datetime.strptime(selected_day, "%Y-%m-%d").date()
        except ValueError:
            selected_day_date = None

    if not selected_day_date and day_list:
        selected_day_date = day_list[0]

    selected_visitors = visitors_by_day.get(selected_day_date, []) if selected_day_date else []

    selected_timed_out = sum(1 for v in selected_visitors if v.time_out)
    selected_active = sum(1 for v in selected_visitors if not v.time_out)

    # calendar anchor
    if view_month:
        try:
            view_year, view_mon = map(int, view_month.split("-"))
            calendar_anchor = date(view_year, view_mon, 1)
        except ValueError:
            calendar_anchor = selected_day_date or date.today()
            calendar_anchor = calendar_anchor.replace(day=1)
    else:
        calendar_anchor = selected_day_date or date.today()
        calendar_anchor = calendar_anchor.replace(day=1)

    cal = calendar.Calendar(firstweekday=6)  # Sunday
    month_days = list(cal.itermonthdates(calendar_anchor.year, calendar_anchor.month))
    month_matrix = [month_days[i:i+7] for i in range(0, len(month_days), 7)]

    # days with visitor records
    record_days = set()
    for v in Visitor.query.with_entities(Visitor.time_in).all():
        if v[0]:
            record_days.add(v[0].date())

    prev_month = (calendar_anchor.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (calendar_anchor.replace(day=28) + timedelta(days=4)).replace(day=1)

    return render_template(
        "admin/visitors.html",
        visitors=visitors,
        visitors_by_day=visitors_by_day,
        day_list=day_list,
        selected_day=selected_day_date,
        selected_visitors=selected_visitors,
        selected_timed_out=selected_timed_out,
        selected_active=selected_active,
        calendar_anchor=calendar_anchor,
        month_matrix=month_matrix,
        record_days=record_days,
        prev_month=prev_month,
        next_month=next_month,
        error=error,
        rng=rng,
    )

#EXPORT VISITOR BY PDF
@admin_bp.route("/visitors/export/pdf", methods=["GET"])
@login_required
def visitors_export_pdf():
    import calendar
    import os
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import legal, landscape
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase.pdfmetrics import stringWidth

    export_type = request.args.get("export_type", "").strip()

    day = request.args.get("day", "").strip()
    month = request.args.get("month", "").strip()   # YYYY-MM
    from_raw = request.args.get("from", "").strip()
    to_raw = request.args.get("to", "").strip()
    year = request.args.get("year", "").strip()

    q = Visitor.query
    title = "Visitor Log Report"
    file_suffix = "Visitor_Log_Report"

    if export_type == "day" and day:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        start_dt = datetime.combine(d, time(0, 0))
        end_dt = datetime.combine(d, time(23, 59, 59))
        q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)
        title = f"Daily Visitor Log ({d.strftime('%B %d, %Y')})"
        file_suffix = f"Daily_Visitor_Log_{d.strftime('%Y_%m_%d')}"

    elif export_type == "month" and month:
        y, m = map(int, month.split("-"))
        start = date(y, m, 1)
        end = date(y, m, calendar.monthrange(y, m)[1])
        start_dt = datetime.combine(start, time(0, 0))
        end_dt = datetime.combine(end, time(23, 59, 59))
        q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)
        title = f"Monthly Visitor Log ({start.strftime('%B %Y')})"
        file_suffix = f"Monthly_Visitor_Log_{start.strftime('%Y_%m')}"

    elif export_type == "range" and from_raw and to_raw:
        start = datetime.strptime(from_raw, "%Y-%m-%d").date()
        end = datetime.strptime(to_raw, "%Y-%m-%d").date()
        start_dt = datetime.combine(start, time(0, 0))
        end_dt = datetime.combine(end, time(23, 59, 59))
        q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)
        title = f"Visitor Log ({start.strftime('%B %d, %Y')} to {end.strftime('%B %d, %Y')})"
        file_suffix = f"Visitor_Log_{start.strftime('%Y_%m_%d')}_to_{end.strftime('%Y_%m_%d')}"

    elif export_type == "year" and year:
        y = int(year)
        start = date(y, 1, 1)
        end = date(y, 12, 31)
        start_dt = datetime.combine(start, time(0, 0))
        end_dt = datetime.combine(end, time(23, 59, 59))
        q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)
        title = f"Yearly Visitor Log ({y})"
        file_suffix = f"Yearly_Visitor_Log_{y}"

    else:
        # fallback to old quick filters if needed
        rng = request.args.get("range", "").strip()
        if rng:
            today = date.today()
            if rng == "week":
                start = today - timedelta(days=today.weekday())
                end = today
                title = f"Weekly Visitor Log ({start.strftime('%b %d, %Y')} to {end.strftime('%b %d, %Y')})"
                file_suffix = f"Weekly_Visitor_Log_{today.strftime('%Y_%m_%d')}"
            elif rng == "month":
                start = today.replace(day=1)
                end = today
                title = f"Monthly Visitor Log ({start.strftime('%B %Y')})"
                file_suffix = f"Monthly_Visitor_Log_{start.strftime('%Y_%m')}"
            else:
                start = today
                end = today
                title = f"Daily Visitor Log ({today.strftime('%B %d, %Y')})"
                file_suffix = f"Daily_Visitor_Log_{today.strftime('%Y_%m_%d')}"

            start_dt = datetime.combine(start, time(0, 0))
            end_dt = datetime.combine(end, time(23, 59, 59))
            q = q.filter(Visitor.time_in >= start_dt, Visitor.time_in <= end_dt)

    visitors = q.order_by(Visitor.time_in.asc(), Visitor.id.asc()).all()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(legal))
    width, height = landscape(legal)

    current_year = datetime.now().year

    library_logo_path = os.path.join(current_app.root_path, "static", "img", "library_logo.png")
    city_logo_path = os.path.join(current_app.root_path, "static", "img", "urdaneta_logo.png")

    margin_x = 32
    top_y = height - 28
    bottom_margin = 40
    table_x = margin_x
    usable_width = width - (margin_x * 2)

    headers = ["Date", "Name", "Contact", "Purpose", "Time In", "Time Out"]

    col_w = [
        usable_width * 0.16,  # Date
        usable_width * 0.22,  # Name
        usable_width * 0.16,  # Contact
        usable_width * 0.24,  # Purpose
        usable_width * 0.11,  # Time In
        usable_width * 0.11,  # Time Out
    ]

    header_h = 28
    base_row_h = 22
    cell_pad_x = 6
    cell_pad_y = 6
    body_font = "Helvetica"
    body_font_size = 8.5

    def wrap_text(text, max_width, font_name="Helvetica", font_size=8.5):
        text = str(text or "")
        if not text:
            return [""]

        words = text.split()
        if not words:
            return [""]

        lines = []
        current = words[0]

        for word in words[1:]:
            trial = current + " " + word
            if stringWidth(trial, font_name, font_size) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)

        final_lines = []
        for line in lines:
            if stringWidth(line, font_name, font_size) <= max_width:
                final_lines.append(line)
            else:
                chunk = ""
                for ch in line:
                    trial = chunk + ch
                    if stringWidth(trial, font_name, font_size) <= max_width:
                        chunk = trial
                    else:
                        if chunk:
                            final_lines.append(chunk)
                        chunk = ch
                if chunk:
                    final_lines.append(chunk)

        return final_lines

    def draw_header():
        header_y = top_y
        center_x = width / 2

        lib_w, lib_h = 46, 46
        city_w, city_h = 70, 45

        left_logo_x = center_x - 185
        right_logo_x = center_x + 130
        logo_y_lib = header_y - 38
        logo_y_city = header_y - 40

        if os.path.exists(library_logo_path):
            c.drawImage(
                ImageReader(library_logo_path),
                left_logo_x, logo_y_lib,
                width=lib_w, height=lib_h,
                preserveAspectRatio=True, mask='auto'
            )

        if os.path.exists(city_logo_path):
            c.drawImage(
                ImageReader(city_logo_path),
                right_logo_x, logo_y_city,
                width=city_w, height=city_h,
                preserveAspectRatio=True, mask='auto'
            )

        c.setFillColor(colors.HexColor("#2148FF"))
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(center_x, header_y, "URDANETA CITY PUBLIC LIBRARY")

        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(center_x, header_y - 18, title)

        c.setFont("Helvetica", 9)
        c.drawCentredString(center_x, header_y - 32, f"Year: {current_year}")

        c.setStrokeColor(colors.HexColor("#2148FF"))
        c.setLineWidth(1.2)
        c.line(margin_x, header_y - 56, width - margin_x, header_y - 56)

        return header_y - 82

    def draw_footer(page_no):
        footer_y = 18

        c.setStrokeColor(colors.HexColor("#D6E2FF"))
        c.setLineWidth(0.8)
        c.line(margin_x, footer_y + 12, width - margin_x, footer_y + 12)

        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#2148FF"))
        c.drawString(margin_x, footer_y, "ULLS - Urdaneta Library Log System")

        c.setFillColor(colors.black)
        c.drawRightString(width - margin_x, footer_y, f"Page {page_no}")

    def draw_summary(y):
        c.setFillColor(colors.HexColor("#2148FF"))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(table_x, y, "Visitor Records")

        c.setFillColor(colors.black)
        c.setFont("Helvetica", 9)
        c.drawRightString(table_x + sum(col_w), y, f"{len(visitors)} record(s)")

        c.setStrokeColor(colors.HexColor("#BFD2FF"))
        c.setLineWidth(0.8)
        c.line(table_x, y - 4, table_x + sum(col_w), y - 4)

        return y - 14

    def draw_table_header(y):
        c.setFillColor(colors.HexColor("#2148FF"))
        c.roundRect(table_x, y - header_h, sum(col_w), header_h, 7, fill=1, stroke=0)

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 9)

        x = table_x
        for head, w in zip(headers, col_w):
            c.drawString(x + 7, y - 18, head)
            x += w

        return y - header_h

    def measure_row(values):
        wrapped = []
        max_lines = 1

        for val, w in zip(values, col_w):
            lines = wrap_text(val, w - (cell_pad_x * 2), body_font, body_font_size)
            wrapped.append(lines)
            max_lines = max(max_lines, len(lines))

        row_h = max(base_row_h, (max_lines * 10) + (cell_pad_y * 2))
        return wrapped, row_h

    def draw_table_row(y, values, fill_color):
        wrapped, row_h = measure_row(values)

        c.setFillColor(fill_color)
        c.rect(table_x, y - row_h, sum(col_w), row_h, fill=1, stroke=0)

        c.setStrokeColor(colors.HexColor("#D8E3FF"))
        c.setLineWidth(0.6)

        x = table_x
        for w in col_w:
            c.line(x, y, x, y - row_h)
            x += w
        c.line(table_x + sum(col_w), y, table_x + sum(col_w), y - row_h)
        c.line(table_x, y - row_h, table_x + sum(col_w), y - row_h)

        c.setFillColor(colors.black)
        c.setFont(body_font, body_font_size)

        x = table_x
        for lines, w in zip(wrapped, col_w):
            text_y = y - cell_pad_y - 8
            for line in lines:
                c.drawString(x + cell_pad_x, text_y, line)
                text_y -= 10
            x += w

        return y - row_h

    def start_new_page(page_no):
        c.showPage()
        y = draw_header()
        draw_footer(page_no)
        y = draw_summary(y)
        y = draw_table_header(y)
        return y

    page_no = 1
    y = draw_header()
    draw_footer(page_no)
    y = draw_summary(y)
    y = draw_table_header(y)

    if not visitors:
        c.setFont("Helvetica", 9)
        c.setFillColor(colors.black)
        c.drawString(table_x, y - 10, "No visitor records found.")
    else:
        for idx, v in enumerate(visitors):
            row = [
                fmt_mdY(v.time_in.date()) if v.time_in else "-",
                v.full_name or "-",
                v.contact or "-",
                v.purpose or "-",
                v.time_in.strftime("%I:%M %p") if v.time_in else "-",
                v.time_out.strftime("%I:%M %p") if v.time_out else "-",
            ]

            _, needed_h = measure_row(row)
            if y - needed_h < bottom_margin + 16:
                page_no += 1
                y = start_new_page(page_no)

            fill = colors.white if idx % 2 == 0 else colors.HexColor("#F6FAFF")
            y = draw_table_row(y, row, fill)

    c.save()
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{file_suffix}.pdf",
        mimetype="application/pdf"
    )

    
@admin_bp.route("/visitors/monthly-report", methods=["GET"])
@login_required
def visitors_monthly_report():
    month = request.args.get("month", "").strip()  # YYYY-MM

    q = Visitor.query
    rows = []
    total = 0

    if month:
        y, m = month.split("-")
        y = int(y); m = int(m)
        start = date(y, m, 1)
        end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)

        q = q.filter(
            Visitor.time_in >= datetime.combine(start, time(0, 0)),
            Visitor.time_in < datetime.combine(end, time(0, 0))
        )

        rows = q.order_by(Visitor.time_in.desc()).all()
        total = len(rows)

    return render_template(
        "admin/visitors_monthly_report.html",
        rows=rows,
        total=total,
        month=month,
    )

@admin_bp.route("/visitors/monthly-report/export/pdf", methods=["GET"])
@login_required
def visitors_monthly_report_export_pdf():
    month = request.args.get("month", "").strip()
    if not month:
        return redirect(url_for("admin.visitors_monthly_report"))

    y0, m0 = month.split("-")
    y0 = int(y0); m0 = int(m0)
    start = date(y0, m0, 1)
    end = date(y0 + 1, 1, 1) if m0 == 12 else date(y0, m0 + 1, 1)

    all_rows = (Visitor.query
        .filter(
            Visitor.time_in >= datetime.combine(start, time(0, 0)),
            Visitor.time_in < datetime.combine(end, time(0, 0))
        )
        .order_by(Visitor.time_in.asc())
        .all()
    )

    # ---- Grouping (Female first, then Male) ----
    females = [v for v in all_rows if (v.gender or "").lower() == "female"]
    males = [v for v in all_rows if (v.gender or "").lower() == "male"]
    others = [v for v in all_rows if v not in females and v not in males]  # optional

    month_label = datetime(y0, m0, 1).strftime("%B %Y")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(letter))
    width, height = landscape(letter)

    # column setup
    headers = ["Name", "Gender", "Age", "Purpose", "Time In", "Time Out"]
    col_w = [180, 70, 40, 220, 150, 150]
    x0 = 30

    def draw_table_title(title, y_pos):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(x0, y_pos, title)

    def draw_row(vals, y_pos, bold=False):
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 9)
        x = x0
        for v, w in zip(vals, col_w):
            c.drawString(x, y_pos, str(v)[:45])
            x += w

    def draw_table_section(section_title, rows, y_pos):
        """Draw one section (title + header + rows). Returns new y_pos."""
        # if near bottom, new page
        if y_pos < 80:
            c.showPage()
            y_pos = height - 40

        draw_table_title(section_title, y_pos)
        y_pos -= 14

        # headers
        draw_row(headers, y_pos, bold=True)
        y_pos -= 10
        c.line(x0, y_pos, width - 30, y_pos)
        y_pos -= 14

        if not rows:
            c.setFont("Helvetica", 9)
            c.drawString(x0, y_pos, "No records.")
            y_pos -= 18
            return y_pos

        for v in rows:
            if y_pos < 50:
                c.showPage()
                y_pos = height - 40
                draw_table_title(section_title + " (cont.)", y_pos)
                y_pos -= 14
                draw_row(headers, y_pos, bold=True)
                y_pos -= 10
                c.line(x0, y_pos, width - 30, y_pos)
                y_pos -= 14

            row = [
                v.full_name,
                v.gender or "",
                v.age if v.age is not None else "",
                v.purpose or "",
                fmt_mdY_time(v.time_in),
                fmt_mdY_time(v.time_out),
            ]
            draw_row(row, y_pos, bold=False)
            y_pos -= 14

        y_pos -= 10  # space after section
        return y_pos

    # ---- Report title ----
    y_pos = height - 40
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x0, y_pos, "Monthly Visitor Report")
    y_pos -= 16
    c.setFont("Helvetica", 10)
    c.drawString(x0, y_pos, f"Month: {month_label}")
    y_pos -= 24

    # ---- Female then Male ----
    y_pos = draw_table_section(f"Female Visitors ({len(females)})", females, y_pos)
    y_pos = draw_table_section(f"Male Visitors ({len(males)})", males, y_pos)

    # Optional: include others/unknown at the end
    if others:
        y_pos = draw_table_section(f"Other/Unspecified ({len(others)})", others, y_pos)

    c.save()
    buf.seek(0)

    return send_file(
        buf,
        as_attachment=True,
        download_name=f"visitors_monthly_{month}.pdf",
        mimetype="application/pdf"
    )

#LOGOUT BUTTON
@admin_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("admin.login"))