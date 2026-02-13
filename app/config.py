import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = "dev-secret-change-this"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SERVER_BASE_URL = "http://192.168.100.101:5000"

    # creates /instance/app.sqlite3
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(BASE_DIR, "..", "instance", "app.sqlite3")
