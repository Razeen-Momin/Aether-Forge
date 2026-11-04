# Profile page API: one-call summary + password change.
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta
from html import escape

import requests
from flask import Blueprint, Response, current_app, request, jsonify, session
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash, check_password_hash

from backend.extensions import db
from backend.models.user import User
from backend.models.project import Project
from backend.models.community_asset import CommunityAsset
from backend.models.email_change import EmailChangeRequest
from backend.models.password_reset import PasswordResetToken
from backend.email_service import send_email, EmailNotConfigured, EmailSendError
from backend.routes.community import (
    _storage_config,
    _storage_headers,
    _storage_error,
    _storage_limit_bytes,
    _storage_used_bytes,
)


profile_bp = Blueprint("profile", __name__, url_prefix="/api/profile")

RECENT_LIMIT = 4
MIN_PASSWORD_LENGTH = 6
MAX_DISPLAY_NAME = 50
MAX_BIO = 160
MIN_USERNAME = 3
MAX_USERNAME = 80
MAX_EMAIL = 255
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
STORAGE_DELETE_CHUNK = 100
EMAIL_LINK_MINUTES = 60
EMAIL_RESEND_SECONDS = 60
EMAIL_DAILY_LIMIT = 5

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

    pending_request = (
        EmailChangeRequest.query
        .filter(
            EmailChangeRequest.user_id == user.id,
            EmailChangeRequest.used_at.is_(None),
            EmailChangeRequest.expires_at > datetime.utcnow(),
        )
        .order_by(EmailChangeRequest.created_at.desc())
        .first()
    )

    is_google = bool(user.google_id)

    return jsonify({
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "display_name": user.display_name,
            "bio": user.bio,
            "sign_in_method": "google" if is_google else "password",
            "created_at": _iso(user.created_at),
            "pending_email": (
                pending_request.new_email if pending_request else None
            ),
        },
        "stats": {
            "projects": project_count,
            "uploads": upload_count,
            "downloads": int(download_total),
        },
        "storage": {
            "used_bytes": _storage_used_bytes(user.id),
            "limit_bytes": _storage_limit_bytes(),
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
# Update display name and bio
# --------------------------------------------------

def _clean_text(value):
    """Trim, collapse stray control characters, and turn '' into None."""
    text = "".join(
        ch for ch in str(value or "")
        if ch in "\n" or ch.isprintable()
    ).strip()
    return text or None


@profile_bp.route("", methods=["PUT"])
def update_profile():

    user = _current_user()

    if not user:
        return jsonify({"message": "Authentication required."}), 401

    data = request.get_json(silent=True) or {}

    display_name = _clean_text(data.get("display_name"))
    bio = _clean_text(data.get("bio"))

    if display_name and len(display_name) > MAX_DISPLAY_NAME:
        return jsonify({
            "message": (
                f"Display name must be {MAX_DISPLAY_NAME} characters "
                "or fewer."
            )
        }), 400

    if bio and len(bio) > MAX_BIO:
        return jsonify({
            "message": f"Bio must be {MAX_BIO} characters or fewer."
        }), 400

    user.display_name = display_name
    user.bio = bio
    db.session.commit()

    return jsonify({
        "message": "Profile updated.",
        "display_name": user.display_name,
        "bio": user.bio,
    }), 200

# --------------------------------------------------
# Change username
# --------------------------------------------------

def _clean_line(value):
    """Single-line text: printable characters only, trimmed."""
    return "".join(
        ch for ch in str(value or "") if ch.isprintable()
    ).strip()


@profile_bp.route("/username", methods=["PUT"])
def change_username():

    user = _current_user()

    if not user:
        return jsonify({"message": "Authentication required."}), 401

    data = request.get_json(silent=True) or {}
    new_username = _clean_line(data.get("username"))

    if len(new_username) < MIN_USERNAME:
        return jsonify({
            "message": (
                f"Username must contain at least {MIN_USERNAME} characters."
            )
        }), 400

    if len(new_username) > MAX_USERNAME:
        return jsonify({
            "message": (
                f"Username must be {MAX_USERNAME} characters or fewer."
            )
        }), 400

    if new_username == user.username:
        return jsonify({
            "message": "That is already your username."
        }), 400

    # Case-insensitive check so "Razeen" and "razeen" cannot both exist.
    # (Your own account is excluded, so changing only the capitalisation
    # of your own name is allowed.)
    taken = User.query.filter(
        func.lower(User.username) == new_username.lower(),
        User.id != user.id
    ).first()

    if taken:
        return jsonify({"message": "Username already exists."}), 409

    user.username = new_username

    try:
        db.session.commit()
    except IntegrityError:
        # Someone grabbed the name between the check and the save
        db.session.rollback()
        return jsonify({"message": "Username already exists."}), 409

    session["username"] = user.username

    return jsonify({
        "message": "Username updated. Use it the next time you sign in.",
        "username": user.username,
    }), 200


# --------------------------------------------------
# Change email (password accounts only)
# --------------------------------------------------

def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_base_url():
    """Address used inside the emailed link, e.g. https://your-app.onrender.com"""
    configured = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    return configured or request.host_url.rstrip("/")


def _result_page(title, message, ok):
    # Only fixed text is placed in this page, never user input.
    colour = "#5b4bd6" if ok else "#c62a3f"
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Aether Forge</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
         justify-content:center; background:#0f1117; color:#eceef5;
         font-family:Inter,"Segoe UI",system-ui,sans-serif; }}
  .box {{ max-width:420px; margin:20px; padding:32px; text-align:center;
         background:#161922; border:1px solid rgba(255,255,255,.09);
         border-radius:14px; }}
  h1 {{ font-size:1.4rem; margin:0 0 12px; color:{colour}; }}
  p {{ color:#98a0b3; line-height:1.6; margin:0 0 22px; }}
  a {{ display:inline-block; background:{colour}; color:#fff;
       padding:11px 22px; border-radius:10px; text-decoration:none;
       font-weight:600; }}
</style>
</head>
<body>
  <div class="box">
    <h1>{title}</h1>
    <p>{message}</p>
    <a href="/profile.html">Go to your profile</a>
  </div>
</body>
</html>"""
    return Response(html, mimetype="text/html")


@profile_bp.route("/email", methods=["PUT"])
def change_email():
    """Step 1: verify the password, then email a confirmation link to the
    NEW address. The account's email is NOT changed here."""

    user = _current_user()

    if not user:
        return jsonify({"message": "Authentication required."}), 401

    # A Google account's email comes from Google and is tied to its
    # google_id, so it must not be edited here.
    if user.google_id:
        return jsonify({
            "message": "Your email is managed by your Google account."
        }), 400

    data = request.get_json(silent=True) or {}
    new_email = _clean_line(data.get("email")).lower()
    current_password = data.get("current_password", "")

    if not current_password:
        return jsonify({
            "message": "Enter your current password to change your email."
        }), 400

    if not check_password_hash(user.password_hash, current_password):
        return jsonify({
            "message": "Current password is incorrect."
        }), 403

    if (
        not new_email
        or len(new_email) > MAX_EMAIL
        or not EMAIL_PATTERN.match(new_email)
    ):
        return jsonify({
            "message": "Enter a valid email address."
        }), 400

    if new_email == (user.email or "").lower():
        return jsonify({
            "message": "That is already your email."
        }), 400

    taken = User.query.filter(
        func.lower(User.email) == new_email,
        User.id != user.id
    ).first()

    if taken:
        return jsonify({
            "message": "That email is already in use."
        }), 409

    # --- limits, so this cannot be used to spam someone's inbox ---------
    now = datetime.utcnow()

    recent = (
        EmailChangeRequest.query
        .filter(
            EmailChangeRequest.user_id == user.id,
            EmailChangeRequest.created_at > now - timedelta(hours=24),
        )
        .order_by(EmailChangeRequest.created_at.desc())
        .all()
    )

    if len(recent) >= EMAIL_DAILY_LIMIT:
        return jsonify({
            "message": "Too many email change requests today. Try again tomorrow."
        }), 429

    if recent and (now - recent[0].created_at).total_seconds() < EMAIL_RESEND_SECONDS:
        return jsonify({
            "message": "Please wait a minute before requesting another link."
        }), 429

    # Older pending links stop working as soon as a newer one is made
    EmailChangeRequest.query.filter(
        EmailChangeRequest.user_id == user.id,
        EmailChangeRequest.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    token = secrets.token_urlsafe(32)

    db.session.add(EmailChangeRequest(
        user_id=user.id,
        new_email=new_email,
        token_hash=_hash_token(token),
        created_at=now,
        expires_at=now + timedelta(minutes=EMAIL_LINK_MINUTES),
    ))
    db.session.flush()

    link = f"{_public_base_url()}/api/profile/email/confirm?token={token}"

    text_body = (
        f"Hi {user.username},\n\n"
        "Someone (hopefully you) asked to use this address for your "
        "Aether Forge account.\n\n"
        f"Confirm the change here (valid for {EMAIL_LINK_MINUTES} minutes):\n"
        f"{link}\n\n"
        "If you did not ask for this, ignore this email and nothing "
        "will change.\n"
    )
    html_body = (
        f"<p>Hi {escape(user.username)},</p>"
        "<p>Someone (hopefully you) asked to use this address for your "
        "Aether Forge account.</p>"
        f'<p><a href="{link}">Confirm my new email</a></p>'
        f"<p>This link is valid for {EMAIL_LINK_MINUTES} minutes.</p>"
        "<p>If you did not ask for this, ignore this email and nothing "
        "will change.</p>"
    )

    try:
        send_email(
            new_email,
            "Confirm your new Aether Forge email",
            text_body,
            html_body,
        )
    except EmailNotConfigured:
        db.session.rollback()
        current_app.logger.error("Email provider is not configured.")
        return jsonify({
            "message": "Email sending is not set up on the server yet."
        }), 503
    except EmailSendError:
        db.session.rollback()
        return jsonify({
            "message": "We could not send the email. Please try again later."
        }), 502

    db.session.commit()

    return jsonify({
        "message": (
            "We sent a confirmation link to the new address. "
            "Your email changes after you click it."
        ),
        "pending_email": new_email,
    }), 200


@profile_bp.route("/email/confirm", methods=["GET"])
def confirm_email():
    """Step 2: the link inside the email. The token itself proves the person
    can read mail sent to the new address, so no login is required."""

    token = request.args.get("token", "")

    invalid = lambda: (
        _result_page(
            "Link not valid",
            "This confirmation link is invalid or has expired. "
            "Please request a new one from your profile page.",
            False,
        ),
        400,
    )

    if not token or len(token) > 200:
        return invalid()

    req = EmailChangeRequest.query.filter_by(
        token_hash=_hash_token(token)
    ).first()

    now = datetime.utcnow()

    if not req or req.used_at is not None or req.expires_at < now:
        return invalid()

    user = db.session.get(User, req.user_id)

    if not user or user.google_id:
        req.used_at = now
        db.session.commit()
        return invalid()

    taken = User.query.filter(
        func.lower(User.email) == req.new_email.lower(),
        User.id != user.id
    ).first()

    if taken:
        req.used_at = now
        db.session.commit()
        return _result_page(
            "Email unavailable",
            "That address is now used by another account, "
            "so it could not be added.",
            False,
        ), 409

    user.email = req.new_email
    req.used_at = now

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _result_page(
            "Email unavailable",
            "That address is now used by another account, "
            "so it could not be added.",
            False,
        ), 409

    return _result_page(
        "Email confirmed",
        "Your new email address has been saved to your account.",
        True,
    )


# --------------------------------------------------
# Delete account
# --------------------------------------------------
# Order matters: cloud files are removed FIRST. If storage fails we stop
# and leave the account untouched, so nothing is ever left in storage
# that no database row points to. Deleting a file that is already gone
# is harmless, so after a failure the user can simply try again.

@profile_bp.route("", methods=["DELETE"])
def delete_account():

    user = _current_user()

    if not user:
        return jsonify({"message": "Authentication required."}), 401

    data = request.get_json(silent=True) or {}

    # --- confirmation -------------------------------------------------
    if user.google_id:
        # Google accounts have no password, so they type their username
        if data.get("confirm_username", "") != user.username:
            return jsonify({
                "message": "Type your username exactly to confirm."
            }), 400
    else:
        password = data.get("current_password", "")

        if not password:
            return jsonify({
                "message": "Enter your password to delete your account."
            }), 400

        if not check_password_hash(user.password_hash, password):
            return jsonify({
                "message": "Current password is incorrect."
            }), 403

    user_id = user.id

    # --- 1. delete the uploaded files from Supabase -------------------
    storage_paths = []
    for storage_path, preview_time in db.session.query(
        CommunityAsset.storage_path,
        CommunityAsset.thumbnail_updated_at
    ).filter(CommunityAsset.user_id == user_id).all():
        storage_paths.append(storage_path)

        # The 3D preview image is stored next to the model file
        if preview_time:
            storage_paths.append(
                storage_path.rsplit("/", 1)[0] + "/thumbnail.png"
            )

    if storage_paths:
        config = _storage_config()

        if not config:
            return jsonify({
                "message": (
                    "Community storage is not configured on the server. "
                    "Your account was not deleted."
                )
            }), 503

        project_url, service_key, bucket = config

        for start in range(0, len(storage_paths), STORAGE_DELETE_CHUNK):
            chunk = storage_paths[start:start + STORAGE_DELETE_CHUNK]

            try:
                response = requests.delete(
                    f"{project_url}/storage/v1/object/{bucket}",
                    headers=_storage_headers(
                        service_key, "application/json"
                    ),
                    json={"prefixes": chunk},
                    timeout=30,
                )
            except requests.RequestException:
                current_app.logger.exception(
                    "Supabase delete request failed during account deletion."
                )
                return jsonify({
                    "message": (
                        "Could not reach cloud storage. "
                        "Your account was not deleted - please try again."
                    )
                }), 502

            if response.status_code not in (200, 204):
                current_app.logger.error(
                    "Supabase delete failed during account deletion: %s",
                    _storage_error(response)
                )
                return jsonify({
                    "message": (
                        "Cloud storage could not delete your files. "
                        "Your account was not deleted - please try again."
                    )
                }), 502

    # --- 2. delete database rows (one transaction) --------------------
    try:
        CommunityAsset.query.filter_by(
            user_id=user_id
        ).delete(synchronize_session=False)

        EmailChangeRequest.query.filter_by(
            user_id=user_id
        ).delete(synchronize_session=False)

        PasswordResetToken.query.filter_by(
            user_id=user_id
        ).delete(synchronize_session=False)

        Project.query.filter_by(
            user_id=user_id
        ).delete(synchronize_session=False)

        User.query.filter_by(
            id=user_id
        ).delete(synchronize_session=False)

        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Account deletion failed in database.")
        return jsonify({
            "message": (
                "Something went wrong while deleting your account. "
                "Please try again."
            )
        }), 500

    session.clear()

    return jsonify({"message": "Account deleted."}), 200

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