# ============================================================
# Importing the required libraries
# ============================================================

import os
from datetime import datetime, timezone
from flask import (
    Flask,
    jsonify,
    request,
    session,
    send_from_directory
)
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

# ============================================================
# AETHER FORGE — BACKEND
# Authentication 
# ============================================================

app = Flask(__name__)

# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------
# Secret key for secure Flask sessions.

app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")

if not app.config["SECRET_KEY"]:
    raise RuntimeError(
        "SECRET_KEY environment variable is not configured."
    )

# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not configured."
    )

# SQLAlchemy / Neon compatibility

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ------------------------------------------------------------
# CORS
# ------------------------------------------------------------

CORS(
    app,
    supports_credentials=True
)


# ============================================================
# DATABASE MODEL
# ============================================================

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    def to_dict(self):
     return {
        "id": self.id,
        "username": self.username,
        "created_at": self.created_at.isoformat()
        if self.created_at else None,
     } 

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "success": True,
        "message": "Aether Forge backend is running."
    })

# ============================================================
# AUTHENTICATION — NEW API
# ============================================================

# ------------------------------------------------------------
# REGISTER
# POST /api/auth/register
# ------------------------------------------------------------

@app.route(
    "/api/auth/register",
    methods=["POST"]
)
def register():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Request body is required."
        }), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

     # Validation
    if not username:
        return jsonify({
            "success": False,
            "message": "Username is required."
        }), 400

    if len(username) < 3:
        return jsonify({
            "success": False,
            "message": "Username must be at least 3 characters."
        }), 400

    if len(username) > 80:
        return jsonify({
            "success": False,
            "message": "Username is too long."
        }), 400

    if not password:
        return jsonify({
            "success": False,
            "message": "Password is required."
        }), 400

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "Password must be at least 6 characters."
        }), 400

    # Check duplicate username
    existing_user = User.query.filter_by(
        username=username
    ).first()

    if existing_user:
        return jsonify({
            "success": False,
            "message": "Username already exists."
        }), 409
    
    # Create user
    password_hash = generate_password_hash(password)

    user = User(
        username=username,
        password_hash=password_hash
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Account created successfully.",
        "user": user.to_dict()
    }), 201

# ------------------------------------------------------------
# LOGIN
# POST /api/auth/login
# ------------------------------------------------------------

@app.route("/api/auth/login", methods=["POST"])
def login():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Request body is required."
        }), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Username and password are required."
        }), 400

    # Find user
    user = User.query.filter_by(
        username=username
    ).first()

    if not user:
        return jsonify({
            "success": False,
            "message": "Invalid username or password."
        }), 401

    # Verify password
    if not check_password_hash(
        user.password_hash,
        password
    ):
        return jsonify({
            "success": False,
            "message": "Invalid username or password."
        }), 401
    
    # Create session
    session.clear()

    session["user_id"] = user.id
    session["username"] = user.username

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": user.to_dict()
    })

# ------------------------------------------------------------
# CURRENT USER
# GET /api/auth/me
# ------------------------------------------------------------

@app.route("/api/auth/me", methods=["GET"])
def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "success": False,
            "authenticated": False,
            "message": "Not authenticated."
        }), 401

    user = db.session.get(User, user_id)

    if not user:
        session.clear()

        return jsonify({
            "success": False,
            "authenticated": False,
            "message": "User session is invalid."
        }), 401

    return jsonify({
        "success": True,
        "authenticated": True,
        "user": user.to_dict()
    })

# ------------------------------------------------------------
# LOGOUT
# POST /api/auth/logout
# ------------------------------------------------------------

@app.route("/api/auth/logout", methods=["POST"])
def logout():

    session.clear()

    return jsonify({
        "success": True,
        "message": "Logged out successfully."
    })

# ============================================================
# LEGACY AUTHENTICATION ROUTES
# ============================================================
#
# These temporarily remain so the current frontend does not
# immediately break while we migrate login.html and signup.html
# to the new /api/auth/* endpoints.
#
# ============================================================

@app.route("/api/register", methods=["POST"])
def legacy_register():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Request body is required."
        }), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({
            "success": False,
            "message": "Username and password are required."
        }), 400

    if len(username) < 3:
        return jsonify({
            "success": False,
            "message": "Username must be at least 3 characters."
        }), 400

    if len(password) < 6:
        return jsonify({
            "success": False,
            "message": "Password must be at least 6 characters."
        }), 400

    existing_user = User.query.filter_by(
        username=username
    ).first()

    if existing_user:
        return jsonify({
            "success": False,
            "message": "Username already exists."
        }), 409

    user = User(
        username=username,
        password_hash=generate_password_hash(password)
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Account created successfully.",
        "user": user.to_dict()
    }), 201


@app.route("/api/login", methods=["POST"])
def legacy_login():

    data = request.get_json(silent=True)

    if not data:
        return jsonify({
            "success": False,
            "message": "Request body is required."
        }), 400

    username = data.get("username", "").strip()
    password = data.get("password", "")

    user = User.query.filter_by(
        username=username
    ).first()

    if not user or not check_password_hash(
        user.password_hash,
        password
    ):
        return jsonify({
            "success": False,
            "message": "Invalid username or password."
        }), 401

    session.clear()

    session["user_id"] = user.id
    session["username"] = user.username

    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": user.to_dict()
    })

# ============================================================
# FRONTEND ROUTES
# ============================================================

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/index.html")
def index_html():
    return send_from_directory(".", "index.html")


@app.route("/login.html")
def login_page():
    return send_from_directory(".", "login.html")


@app.route("/signup.html")
def signup_page():
    return send_from_directory(".", "signup.html")


@app.route("/AetherForge.html")
def aether_forge():
    return send_from_directory(".", "AetherForge.html")


@app.route("/logo.png")
def logo():
    return send_from_directory(".", "logo.png")


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

with app.app_context():
    db.create_all()


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )

