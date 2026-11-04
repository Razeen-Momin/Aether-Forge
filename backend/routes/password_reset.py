import hashlib
import os
import re
import secrets
import threading
from datetime import datetime, timedelta
from html import escape

from flask import Blueprint, current_app, request, jsonify
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from backend.extensions import db
from backend.models.user import User
from backend.models.password_reset import PasswordResetToken
from backend.email_service import send_email, EmailNotConfigured, EmailSendError


password_reset_bp = Blueprint(
    "password_reset",
    __name__,
    url_prefix="/api/auth"
)

RESET_LINK_MINUTES = 60
RESET_RESEND_SECONDS = 60
RESET_DAILY_LIMIT = 5

MIN_PASSWORD = 6      # same rule as registration
MAX_PASSWORD = 128

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# The same answer is given whether or not the email belongs to an account,
# so this form cannot be used to find out who has an account.
GENERIC_MESSAGE = (
    "If an account uses that email address, we have sent a link to reset "
    "the password. It can take a minute to arrive, so check your spam "
    "folder too."
)


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public_base_url():
    configured = (os.getenv("APP_BASE_URL") or "").strip().rstrip("/")
    return configured or request.host_url.rstrip("/")


def _send_in_background(app, to_email, subject, text_body, html_body):
    """Send the email without making the visitor wait. This also keeps the
    response time the same for existing and unknown addresses."""

    def run():
        with app.app_context():
            try:
                send_email(to_email, subject, text_body, html_body)
            except EmailNotConfigured:
                app.logger.error(
                    "Password reset email not sent: provider not configured."
                )
            except EmailSendError:
                pass  # already logged inside send_email
            except Exception:
                app.logger.exception("Unexpected error sending reset email.")

    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------
# Step 1: ask for a reset link
# --------------------------------------------------

@password_reset_bp.route("/forgot-password", methods=["POST"])
def forgot_password():

    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()

    if not email or len(email) > 255 or not EMAIL_PATTERN.match(email):
        return jsonify({
            "message": "Enter a valid email address."
        }), 400

    user = User.query.filter(func.lower(User.email) == email).first()

    if user:
        now = datetime.utcnow()

        recent = (
            PasswordResetToken.query
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.created_at > now - timedelta(hours=24),
            )
            .order_by(PasswordResetToken.created_at.desc())
            .all()
        )

        within_limits = (
            len(recent) < RESET_DAILY_LIMIT
            and not (
                recent
                and (now - recent[0].created_at).total_seconds()
                < RESET_RESEND_SECONDS
            )
        )

        if within_limits:
            # Older links stop working as soon as a newer one is made
            PasswordResetToken.query.filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
            ).update({"used_at": now}, synchronize_session=False)

            safe_name = escape(user.username)

            if user.google_id:
                # Google accounts have no password. Tell the owner so, and
                # log the notice as an already-used row so the limits apply.
                db.session.add(PasswordResetToken(
                    user_id=user.id,
                    token_hash=_hash_token(secrets.token_urlsafe(32)),
                    created_at=now,
                    expires_at=now,
                    used_at=now,
                ))
                db.session.commit()

                subject = "Signing in to Aether Forge"
                text_body = (
                    f"Hi {user.username},\n\n"
                    "Someone asked to reset the password for this Aether "
                    "Forge account. It signs in with Google, so it has no "
                    "password to reset. Use \"Continue with Google\" on the "
                    "sign in page.\n\n"
                    "If this wasn't you, you can ignore this email.\n"
                )
                html_body = (
                    f"<p>Hi {safe_name},</p>"
                    "<p>Someone asked to reset the password for this Aether "
                    "Forge account. It signs in with Google, so it has no "
                    "password to reset. Use <strong>Continue with "
                    "Google</strong> on the sign in page.</p>"
                    "<p>If this wasn't you, you can ignore this email.</p>"
                )
            else:
                token = secrets.token_urlsafe(32)

                db.session.add(PasswordResetToken(
                    user_id=user.id,
                    token_hash=_hash_token(token),
                    created_at=now,
                    expires_at=now + timedelta(minutes=RESET_LINK_MINUTES),
                ))
                db.session.commit()

                link = f"{_public_base_url()}/reset-password.html?token={token}"

                subject = "Reset your Aether Forge password"
                text_body = (
                    f"Hi {user.username},\n\n"
                    "We received a request to reset the password for your "
                    "Aether Forge account.\n\n"
                    f"Choose a new password here (valid for "
                    f"{RESET_LINK_MINUTES} minutes):\n{link}\n\n"
                    "If you did not ask for this, ignore this email. Your "
                    "password will stay the same.\n"
                )
                html_body = (
                    f"<p>Hi {safe_name},</p>"
                    "<p>We received a request to reset the password for "
                    "your Aether Forge account.</p>"
                    f'<p><a href="{link}">Choose a new password</a></p>'
                    f"<p>This link is valid for {RESET_LINK_MINUTES} "
                    "minutes.</p>"
                    "<p>If you did not ask for this, ignore this email. "
                    "Your password will stay the same.</p>"
                )

            _send_in_background(
                current_app._get_current_object(),
                user.email,
                subject,
                text_body,
                html_body,
            )

    return jsonify({"message": GENERIC_MESSAGE}), 200


# --------------------------------------------------
# Step 2: set the new password
# --------------------------------------------------

@password_reset_bp.route("/reset-password", methods=["POST"])
def reset_password():

    data = request.get_json(silent=True) or {}
    token = str(data.get("token", ""))
    new_password = data.get("new_password", "")

    invalid = (
        jsonify({
            "message": "This reset link is invalid or has expired. "
                       "Please request a new one."
        }),
        400,
    )

    if not isinstance(new_password, str) or len(new_password) < MIN_PASSWORD:
        return jsonify({
            "message": (
                f"Password must contain at least {MIN_PASSWORD} characters."
            )
        }), 400

    if len(new_password) > MAX_PASSWORD:
        return jsonify({
            "message": f"Password must be at most {MAX_PASSWORD} characters."
        }), 400

    if not token or len(token) > 200:
        return invalid

    req = PasswordResetToken.query.filter_by(
        token_hash=_hash_token(token)
    ).first()

    now = datetime.utcnow()

    if not req or req.used_at is not None or req.expires_at < now:
        return invalid

    user = db.session.get(User, req.user_id)

    if not user or user.google_id:
        req.used_at = now
        db.session.commit()
        return invalid

    user.password_hash = generate_password_hash(new_password)

    # This link and any other open links are now spent
    PasswordResetToken.query.filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    ).update({"used_at": now}, synchronize_session=False)

    db.session.commit()

    return jsonify({
        "message": "Your password has been reset. You can now sign in."
    }), 200
