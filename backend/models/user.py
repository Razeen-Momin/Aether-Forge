
from backend.extensions import db


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
