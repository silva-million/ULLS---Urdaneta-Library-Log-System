from datetime import datetime
from ..extensions import db

class Visitor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    contact = db.Column(db.String(80), nullable=True)
    purpose = db.Column(db.String(200), nullable=True)

    time_in = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    time_out = db.Column(db.DateTime, nullable=True)
