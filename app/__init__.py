from flask import Flask, render_template
from datetime import date as _date
from datetime import date
from .config import Config
from .extensions import login_manager, db, migrate
import os
from .models import daily_qr  # noqa: F401

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.instance_path, exist_ok=True)
    
    
    @app.route("/")
    def landing():
        return render_template("landing.html", date=date)
    
    def j_mdY(value):
        if not value:
            return ""
        # date object
        return value.strftime("%B ") + str(value.day) + value.strftime(", %Y")

    def j_mdY_time(value):
        if not value:
            return ""
        # datetime object
        return value.strftime("%B ") + str(value.day) + value.strftime(", %Y %I:%M %p")

    app.jinja_env.filters["mdY"] = j_mdY
    app.jinja_env.filters["mdY_time"] = j_mdY_time

    login_manager.init_app(app)
    db.init_app(app)
    migrate.init_app(app, db)
    with app.app_context():
        db.create_all()

    from .models.user import AdminUser

    @login_manager.user_loader
    def load_user(user_id):
        return AdminUser(user_id)

    # import models so migrate can see them
    from .models import employee  # noqa: F401
    from .models import attendance  # noqa: F401
    from .models import visitor  # noqa: F401

    from .employee.routes import employee_bp
    app.register_blueprint(employee_bp, url_prefix="/employee")

    from .admin.routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    from .visitor.routes import visitor_bp
    app.register_blueprint(visitor_bp, url_prefix="/visitor")

    @app.template_filter("longdate")
    def longdate(value):
        if not value:
            return ""
        # value can be date or datetime
        d = value.date() if hasattr(value, "date") else value
        return d.strftime("%B %-d, %Y") if hasattr(d, "strftime") else str(value)
    return app
