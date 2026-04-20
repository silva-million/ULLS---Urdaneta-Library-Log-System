from datetime import datetime, date
from ..extensions import db

class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    employee_id = db.Column(db.String(50), unique=True, nullable=False, index=True)

    surname = db.Column(db.String(80), nullable=False)
    first_name = db.Column(db.String(80), nullable=False)
    middle_name = db.Column(db.String(80), nullable=True)

    birthday = db.Column(db.Date, nullable=True)
    position = db.Column(db.String(120), nullable=True)

    status = db.Column(db.String(30), nullable=False, default="active")  # active, away, on_leave
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    @property
    def full_name(self):
        parts = [self.surname, self.first_name, self.middle_name or ""]
        return " ".join([p for p in parts if p]).strip()
