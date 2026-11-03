from backend.extensions import db
from datetime import datetime

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(80),
        unique=True,
        nullable=False
    )

    password_hash = db.Column(
        db.String(255),
        nullable=False
    )

    # Email associated with the account
    email = db.Column(
        db.String(255),
        unique=True,
        nullable=True
    )

    # Unique Google account identifier
    google_id = db.Column(
        db.String(255),
        unique=True,
        nullable=True
    )

    # When the account was created (older accounts get a backfilled date)
    created_at = db.Column(
        db.DateTime,
        nullable=True,
        default=datetime.utcnow
    )

    # Optional public-facing name (the login username never changes)
    display_name = db.Column(db.String(50), nullable=True)

    # Short "about me" text
    bio = db.Column(db.String(160), nullable=True)