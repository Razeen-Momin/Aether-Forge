# Import necessary modules and classes
from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash

from backend.extensions import db
from backend.models.user import User


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Register a new user

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

    existing_user = User.query.filter_by(username=username).first()

    if existing_user:
        return jsonify({
            "message": "Username already exists."
        }), 409

    hashed_password = generate_password_hash(password)

    new_user = User(
        username=username,
        password=hashed_password
    )

    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "message": "Account created successfully."
    }), 201

#Login an existing user

@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}

    username = data.get("username", "").strip()
    password = data.get("password", "")

    if not username or not password:
        return jsonify({
            "message": "Username and password are required."
        }), 400

    user = User.query.filter_by(username=username).first()

    if not user or not check_password_hash(user.password, password):
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

# Logout the current user

@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()

    return jsonify({
        "message": "Logout successful."
    }), 200

# Get information about the current user

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