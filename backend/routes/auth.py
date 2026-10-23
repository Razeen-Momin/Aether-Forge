# Import necessary modules and classes
from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash

from backend.extensions import db
from backend.models.user import User

import os
import secrets

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


# --------------------------------------------------
# Register a new user
# --------------------------------------------------

@auth_bp.route("/register", methods=["POST"])
def register():

    data = request.get_json(silent=True) or {}

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({
            "message": "Username and password are required."
        }), 400

    if len(username) < 3:
        return jsonify({
            "message": "Username must contain at least 3 characters."
        }), 400

    if len(password) < 6:
        return jsonify({
            "message": "Password must contain at least 6 characters."
        }), 400

    existing_user = User.query.filter_by(
        username=username
    ).first()

    if existing_user:
        return jsonify({
            "message": "Username already exists."
        }), 409

    hashed_password = generate_password_hash(password)

    new_user = User(
        username=username,
        password_hash=hashed_password
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "message": "Account created successfully."
    }), 201


# --------------------------------------------------
# Login an existing user
# --------------------------------------------------

@auth_bp.route("/login", methods=["POST"])
def login():

    data = request.get_json(silent=True) or {}

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({
            "message": "Username and password are required."
        }), 400

    user = User.query.filter_by(
        username=username
    ).first()

    if not user or not check_password_hash(
        user.password_hash,
        password
    ):
        return jsonify({
            "message": "Invalid username or password."
        }), 401

    session.clear()

    session["user_id"] = user.id
    session["username"] = user.username

    return jsonify({
        "message": "Login successful.",
        "user": {
            "id": user.id,
            "username": user.username
        }
    }), 200


# --------------------------------------------------
# Logout the current user
# --------------------------------------------------

@auth_bp.route("/logout", methods=["POST"])
def logout():

    session.clear()

    return jsonify({
        "message": "Logout successful."
    }), 200


# --------------------------------------------------
# Get information about the current user
# --------------------------------------------------

@auth_bp.route("/me", methods=["GET"])
def current_user():

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "authenticated": False
        }), 401

    user = db.session.get(User, user_id)

    if not user:
        session.clear()

        return jsonify({
            "authenticated": False
        }), 401

    return jsonify({
        "authenticated": True,
        "user": {
            "id": user.id,
            "username": user.username
        }
    }), 200

# --------------------------------------------------
# Google Login
# --------------------------------------------------

@auth_bp.route("/google", methods=["POST"])
def google_login():

    data = request.get_json(silent=True) or {}
    credential = data.get("credential")

    if not credential:
        return jsonify({
            "message": "Google credential is required."
        }), 400

    client_id = os.environ.get("GOOGLE_CLIENT_ID")

    if not client_id:
        return jsonify({
            "message": "Google Login is not configured on the server."
        }), 500

    # Verify the credential with Google
    try:
        google_user = id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            client_id
        )
    except ValueError:
        return jsonify({
            "message": "Invalid or expired Google credential."
        }), 401

    google_id = google_user.get("sub")
    email = (google_user.get("email") or "").strip().lower()
    email_verified = google_user.get("email_verified", False)

    if not google_id or not email or email_verified is not True:
        return jsonify({
            "message": "A verified Google email is required."
        }), 400

    # Check whether this Google account already exists
    user = User.query.filter_by(
        google_id=google_id
    ).first()

    if user:
        session.clear()
        session["user_id"] = user.id
        session["username"] = user.username

        return jsonify({
            "message": "Google login successful.",
            "user": {
                "id": user.id,
                "username": user.username
            }
        }), 200

    # Do not automatically link a Google account to an
    # existing password account with the same email.
    existing_email = User.query.filter_by(
        email=email
    ).first()

    if existing_email:
        return jsonify({
            "message": (
                "An account with this email already exists. "
                "Please log in using your existing method."
            )
        }), 409

    # Create a unique username
    base_username = (
        google_user.get("name")
        or email.split("@")[0]
    )

    import re

    base_username = re.sub(
        r"[^a-zA-Z0-9_]",
        "",
        base_username
    )[:60]

    if len(base_username) < 3:
        base_username = "googleuser"

    username = base_username
    counter = 1

    while User.query.filter_by(username=username).first():
        username = f"{base_username[:65]}{counter}"
        counter += 1

    # Google users do not set a local password here.
    # Store a random, unusable password hash instead.
    new_user = User(
        username=username,
        email=email,
        google_id=google_id,
        password_hash=generate_password_hash(
            secrets.token_urlsafe(32)
        )
    )

    db.session.add(new_user)
    db.session.commit()

    # Start the same session used by regular login
    session.clear()
    session["user_id"] = new_user.id
    session["username"] = new_user.username

    return jsonify({
        "message": "Google login successful.",
        "user": {
            "id": new_user.id,
            "username": new_user.username
        }
    }), 200
