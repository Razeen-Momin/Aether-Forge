import os
from pathlib import Path

from flask import Flask, send_from_directory
from flask_cors import CORS

from backend.extensions import db
from backend.routes.auth import auth_bp
from backend.models.project import Project
from backend.routes.project import projects_bp
from backend.models.user import User
from dotenv import load_dotenv


def create_app():
    app = Flask(__name__)

    # -----------------------------
    # Application configuration
    # -----------------------------

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "dev-secret-key-change-this"
    )

    # -----------------------------
    # Neon PostgreSQL Database
    # -----------------------------
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL environment variable is not configured."
        )

    # PostgreSQL URL compatibility
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://",
            "postgresql://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # -----------------------------
    # Initialize extensions
    # -----------------------------

    db.init_app(app)

    CORS(
        app,
        supports_credentials=True
    )

    # -----------------------------
    # Register API routes
    # -----------------------------

    app.register_blueprint(auth_bp)
    app.register_blueprint(projects_bp)

    # -----------------------------
    # Frontend files
    # -----------------------------

    # app.py is located in the project root
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

    @app.route("/")
    def home():
        return send_from_directory(
            PROJECT_ROOT,
            "index.html"
        )

    @app.route("/index.html")
    def index_page():
        return send_from_directory(
            PROJECT_ROOT,
            "index.html"
        )

    @app.route("/login.html")
    def login_page():
        return send_from_directory(
            PROJECT_ROOT,
            "login.html"
        )

    @app.route("/signup.html")
    def signup_page():
        return send_from_directory(
            PROJECT_ROOT,
            "signup.html"
        )

    @app.route("/AetherForge.html")
    def aether_forge():
        return send_from_directory(
            PROJECT_ROOT,
            "AetherForge.html"
        )

    @app.route("/projects.html")
    def projects_page():
        return send_from_directory(
            PROJECT_ROOT,
            "projects.html"
    )

    @app.route("/contact.html")
    def contact_page():
        return send_from_directory(
            PROJECT_ROOT,
            "contact.html"
        )

    @app.route("/logo.png")
    def logo():
        return send_from_directory(
            PROJECT_ROOT,
            "logo.png"
        )

    # -----------------------------
    # Create database tables
    # -----------------------------

    with app.app_context():

        db.create_all()

        # Add project_data column if it does not exist
        from sqlalchemy import inspect, text

        inspector = inspect(db.engine)

        # Only check if the projects table exists
        if "projects" in inspector.get_table_names():

            columns = [
                column["name"]
                for column in inspector.get_columns("projects")
            ]

            if "project_data" not in columns:

                with db.engine.connect() as connection:

                    connection.execute(
                        text(
                            "ALTER TABLE projects "
                            "ADD COLUMN project_data JSON"
                        )
                    )

                    connection.commit()

    return app


# -----------------------------
# Create Flask application
# -----------------------------

app = create_app()


# -----------------------------
# Local development
# -----------------------------

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=True
    )
