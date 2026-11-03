# Profile page API: one-call summary + password change.

from flask import Blueprint, request, jsonify, session
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash

from backend.extensions import db
from backend.models.user import User
from backend.models.project import Project
from backend.models.community_asset import CommunityAsset


profile_bp = Blueprint("profile", __name__, url_prefix="/api/profile")

RECENT_LIMIT = 4
MIN_PASSWORD_LENGTH = 6


def _current_user():
    """Return the logged-in user, or None (clearing a stale session)."""
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = db.session.get(User, user_id)
    if not user:
        session.clear()
    return user


def _iso(value):
    # Same convention as community.py: naive UTC datetimes get a "Z"
    return value.isoformat() + "Z" if value else None


# --------------------------------------------------
# Profile summary (header, stats, recent items)
# --------------------------------------------------

@profile_bp.route("", methods=["GET"])
def get_profile():

    user = _current_user()

    if not user:
        return jsonify({"message": "Authentication required."}), 401

    project_count = Project.query.filter_by(user_id=user.id).count()

    upload_count, download_total = db.session.query(
        func.count(CommunityAsset.id),
        func.coalesce(func.sum(CommunityAsset.downloads_count), 0)
    ).filter(CommunityAsset.user_id == user.id).one()

    recent_projects = (
        Project.query.filter_by(user_id=user.id)
        .order_by(Project.updated_at.desc())
        .limit(RECENT_LIMIT)
        .all()
    )

    recent_uploads = (
        CommunityAsset.query.filter_by(user_id=user.id)
        .order_by(CommunityAsset.created_at.desc())
        .limit(RECENT_LIMIT)
        .all()
    )

    is_google = bool(user.google_id)

    return jsonify({
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "sign_in_method": "google" if is_google else "password",
            "created_at": _iso(user.created_at),
        },
        "stats": {
            "projects": project_count,
            "uploads": upload_count,
            "downloads": int(download_total),
        },
        "recent_projects": [
            {
                "id": p.id,
                "name": p.name,
                "created_at": _iso(p.created_at),
                "updated_at": _iso(p.updated_at),
            }
            for p in recent_projects
        ],
        "recent_uploads": [
            {
                "id": a.id,
                "title": a.title,
                "file_format": a.file_format,
                "visibility": a.visibility,
                "downloads_count": a.downloads_count,
                "created_at": _iso(a.created_at),
            }
            for a in recent_uploads
        ],
        # Google accounts store a random unusable password, so there is
        # nothing meaningful for them to change here.
        "can_change_password": not is_google,
    }), 200


# --------------------------------------------------
# Change password
# --------------------------------------------------

@profile_bp.route("/password", methods=["PUT"])
def change_password():

    user = _current_user()

    if not user:
        return jsonify({"message": "Authentication required."}), 401

    if user.google_id:
        return jsonify({
            "message": "Google accounts do not have an Aether Forge password."
        }), 400

    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password", "")
    new_password = data.get("new_password", "")

    if not current_password or not new_password:
        return jsonify({
            "message": "Current and new password are required."
        }), 400

    if not check_password_hash(user.password_hash, current_password):
        return jsonify({
            "message": "Current password is incorrect."
        }), 403

    if len(new_password) < MIN_PASSWORD_LENGTH:
        return jsonify({
            "message": (
                f"Password must contain at least {MIN_PASSWORD_LENGTH} "
                "characters."
            )
        }), 400

    if check_password_hash(user.password_hash, new_password):
        return jsonify({
            "message": "New password must be different from the current one."
        }), 400

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()

    return jsonify({"message": "Password updated successfully."}), 200