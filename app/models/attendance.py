from datetime import datetime, date, time
from ..extensions import db

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=False, index=True)
    employee = db.relationship("Employee", backref=db.backref("attendance_records", lazy=True))

    # attendance date (one record per employee per date)
    day = db.Column(db.Date, nullable=False, index=True)

    am_in = db.Column(db.Time, nullable=True)
    lunch_out = db.Column(db.Time, nullable=True)
    lunch_in = db.Column(db.Time, nullable=True)
    pm_out = db.Column(db.Time, nullable=True)

    # computed fields (store for faster reporting; we’ll compute in code later)
    total_minutes = db.Column(db.Integer, nullable=False, default=0)
    overtime_minutes = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("employee_id", "day", name="uq_att_employee_day"),
    )
