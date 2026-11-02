from datetime import datetime

from backend.extensions import db


class CommunityAsset(db.Model):
    __tablename__ = "community_assets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id"),
        nullable=False,
        index=True
    )

    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(1000), nullable=True)
    category = db.Column(db.String(60), nullable=True, index=True)

    original_filename = db.Column(db.String(255), nullable=False)
    file_format = db.Column(db.String(12), nullable=False, index=True)
    storage_path = db.Column(db.String(500), nullable=False, unique=True)
    file_size = db.Column(db.BigInteger, nullable=False)

    visibility = db.Column(
        db.String(10),
        nullable=False,
        default="public",
        server_default="public",
        index=True
    )

    downloads_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow,
        index=True
    )

    owner = db.relationship(
        "User",
        backref=db.backref("community_assets", lazy=True)
    )