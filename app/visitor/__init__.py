from flask import Flask

def create_app():
    app = Flask(__name__)

    # later we’ll move this to config + .env
    app.config["SECRET_KEY"] = "dev-secret-change-this"

    # register blueprints
    from .admin.routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/admin")

    return app
