from datetime import datetime
from ..extensions import db

class Visitor(db.Model):
    __tablename__ = "visitor"

    id = db.Column(db.Integer, primary_key=True)

    full_name = db.Column(db.String(150), nullable=False)
    gender = db.Column(db.String(10), nullable=True)   # Male/Female/Other
    age = db.Column(db.Integer, nullable=True)
    purpose = db.Column(db.String(255), nullable=True)
    address_institution = db.Column(db.String(255), nullable=True)

    contact = db.Column(db.String(50), nullable=True)  # keep this only if still needed elsewhere

    time_in = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    time_out = db.Column(db.DateTime, nullable=True)