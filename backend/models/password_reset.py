from datetime import datetime

from backend.extensions import db


class PasswordResetToken(db.Model):
    """A one-time "forgot password" link.

    Only a SHA-256 hash of the secret token is stored, so a leaked database
    row cannot be used to reset anyone's password. Rows are kept after use
    (used_at is set) so they can also count towards the request limits.
    """

    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    token_hash = db.Column(
        db.String(64),
        nullable=False,
        unique=True,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True
    )

    expires_at = db.Column(db.DateTime, nullable=False)

    used_at = db.Column(db.DateTime, nullable=True)
