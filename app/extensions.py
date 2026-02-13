from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

login_manager = LoginManager()
login_manager.login_view = "admin.login"

db = SQLAlchemy()
migrate = Migrate()
