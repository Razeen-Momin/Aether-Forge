from datetime import datetime

from backend.extensions import db


class EmailChangeRequest(db.Model):
    """A pending request to change a user's email address.

    The address is only copied onto the user AFTER they click the link that
    was emailed to the NEW address. Only a hash of the token is stored, so a
    leaked database row cannot be used to confirm a change.
    """

    __tablename__ = "email_change_requests"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    new_email = db.Column(db.String(255), nullable=False)

    # SHA-256 hash (64 hex characters) of the secret token in the email link
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

    # Set when the link was used, or replaced by a newer request
    used_at = db.Column(db.DateTime, nullable=True)
