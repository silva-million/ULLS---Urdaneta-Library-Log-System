from flask import Blueprint, request, render_template_string
from ..extensions import db
from ..models.visitor import Visitor

visitor_bp = Blueprint("visitor", __name__)

FORM = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Visitor Log</title>
</head>

<body style="font-family:Arial; padding:24px;">
  <h2>Visitor Log</h2>

  <form method="post">
    <input name="full_name" placeholder="Full Name" required><br><br>

    <select name="gender" required>
      <option value="">Select Gender</option>
      <option value="Male">Male</option>
      <option value="Female">Female</option>
      <option value="Other">Other</option>
    </select><br><br>

    <input name="age" type="number" min="0" max="120" placeholder="Age" required><br><br>

    <input name="contact" placeholder="Contact (optional)"><br><br>
    <input name="purpose" placeholder="Purpose (optional)"><br><br>

    <button type="submit">Time In</button>
  </form>

  {% if msg %}<p style="color:green;">{{ msg }}</p>{% endif %}
</body>
</html>
"""

@visitor_bp.route("/", methods=["GET", "POST"])
def visitor_home():
    msg = None
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        contact = request.form.get("contact", "").strip() or None
        purpose = request.form.get("purpose", "").strip() or None

        gender = (request.form.get("gender") or "").strip() or None
        age_raw = (request.form.get("age") or "").strip()
        age = int(age_raw) if age_raw.isdigit() else None

        v = Visitor(
            full_name=full_name,
            contact=contact,
            purpose=purpose,
            gender=gender,
            age=age,
        )

        db.session.add(v)
        db.session.commit()
        msg = "Logged ✅"

    return render_template_string(FORM, msg=msg)