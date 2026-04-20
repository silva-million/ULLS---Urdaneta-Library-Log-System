from flask import Blueprint, request, render_template
from ..extensions import db
from ..models.visitor import Visitor

visitor_bp = Blueprint("visitor", __name__, template_folder="templates")

@visitor_bp.route("/", methods=["GET", "POST"])
def visitor_home():
    msg = None
    error = None

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        gender = (request.form.get("gender") or "").strip()
        age_raw = (request.form.get("age") or "").strip()
        purpose = request.form.get("purpose", "").strip() or None
        address_institution = request.form.get("address_institution", "").strip() or None

        if not full_name:
            error = "Full name is required."
        elif not gender:
            error = "Gender is required."
        elif not age_raw.isdigit():
            error = "Valid age is required."
        else:
            age = int(age_raw)

            v = Visitor(
                full_name=full_name,
                gender=gender,
                age=age,
                purpose=purpose,
                address_institution=address_institution,
            )

            db.session.add(v)
            db.session.commit()
            msg = "Visitor logged successfully."

        return render_template("visitor/index.html", msg=msg, error=error)

    return render_template("visitor/index.html", msg=msg, error=error)