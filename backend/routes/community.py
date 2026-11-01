import os
import uuid
from datetime import datetime

import requests
from flask import Blueprint, current_app, jsonify, request, session
from sqlalchemy import desc, or_
from werkzeug.utils import secure_filename

from backend.extensions import db
from backend.models.community_asset import CommunityAsset
from backend.models.user import User

community_bp = Blueprint("community", __name__, url_prefix="/api/community")

ALLOWED_EXTENSIONS = {"obj", "glb", "gltf", "fbx", "stl", "ply", "3mf", "usdz"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SIGNED_URL_SECONDS = 300


def _storage_config():
    project_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    bucket = os.getenv("SUPABASE_BUCKET", "community-assets").strip()

    current_app.logger.info(
        "SUPABASE CONFIG CHECK | URL present: %s | KEY present: %s | BUCKET present: %s",
        bool(project_url),
        bool(service_key),
        bool(bucket)
    )

    if not project_url or not service_key:
        return None

    return project_url, service_key, bucket


def _storage_headers(service_key, content_type=None):
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _storage_error(response):
    try:
        payload = response.json()
        message = payload.get("message") or payload.get("error") or payload.get("statusCode")
    except (ValueError, AttributeError):
        message = None
    return str(message or f"Storage request failed ({response.status_code}).")


def _asset_json(asset, owner_name=None):
    return {
        "id": asset.id,
        "title": asset.title,
        "description": asset.description or "",
        "category": asset.category or "Other",
        "file_format": asset.file_format,
        "file_size": asset.file_size,
        "downloads_count": asset.downloads_count,
        "creator": owner_name or (asset.owner.username if asset.owner else "Unknown"),
        "created_at": asset.created_at.isoformat() + "Z",
    }


@community_bp.get("")
def list_community_assets():
    search = (request.args.get("q") or "").strip()[:100]
    category = (request.args.get("category") or "").strip()[:60]
    try:
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(40, max(1, int(request.args.get("per_page", 20))))
    except ValueError:
        return jsonify({"message": "Page values must be whole numbers."}), 400

    query = db.session.query(CommunityAsset, User.username).join(
        User, CommunityAsset.user_id == User.id
    )
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(
            CommunityAsset.title.ilike(pattern),
            CommunityAsset.description.ilike(pattern),
            CommunityAsset.category.ilike(pattern),
        ))
    if category:
        query = query.filter(CommunityAsset.category == category)

    total = query.count()
    rows = query.order_by(desc(CommunityAsset.created_at)).offset(
        (page - 1) * per_page
    ).limit(per_page).all()

    return jsonify({
        "assets": [_asset_json(asset, username) for asset, username in rows],
        "page": page,
        "per_page": per_page,
        "total": total,
    }), 200


@community_bp.post("")
def upload_community_asset():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"message": "Please log in to upload a community asset."}), 401

    config = _storage_config()
    if not config:
        current_app.logger.error("Supabase Storage environment variables are missing.")
        return jsonify({"message": "Community storage is not configured on the server."}), 503

    uploaded_file = request.files.get("file")
    if not uploaded_file or not uploaded_file.filename:
        return jsonify({"message": "Choose a 3D model file to upload."}), 400

    original_filename = secure_filename(uploaded_file.filename)
    if not original_filename or "." not in original_filename:
        return jsonify({"message": "The selected filename is invalid."}), 400

    extension = original_filename.rsplit(".", 1)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return jsonify({
            "message": "Unsupported format. Allowed formats: " + ", ".join(sorted(ALLOWED_EXTENSIONS))
        }), 400

    file_bytes = uploaded_file.read(MAX_UPLOAD_BYTES + 1)
    if not file_bytes:
        return jsonify({"message": "The selected file is empty."}), 400
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        return jsonify({"message": "File is too large. Maximum upload size is 50 MB."}), 413

    title = (request.form.get("title") or original_filename.rsplit(".", 1)[0]).strip()[:160]
    description = (request.form.get("description") or "").strip()[:1000]
    category = (request.form.get("category") or "Other").strip()[:60] or "Other"
    if not title:
        return jsonify({"message": "Asset title is required."}), 400

    project_url, service_key, bucket = config
    storage_path = f"users/{user_id}/{uuid.uuid4().hex}/{original_filename}"
    content_type = uploaded_file.mimetype or "application/octet-stream"
    upload_url = f"{project_url}/storage/v1/object/{bucket}/{storage_path}"

    try:
        response = requests.post(
            upload_url,
            headers={**_storage_headers(service_key, content_type), "x-upsert": "false"},
            data=file_bytes,
            timeout=60,
        )
    except requests.RequestException:
        current_app.logger.exception("Supabase upload request failed.")
        return jsonify({"message": "Could not reach cloud storage. Please try again."}), 502

    if response.status_code not in (200, 201):
        current_app.logger.error("Supabase upload failed: %s", _storage_error(response))
        return jsonify({"message": "Cloud storage rejected the upload. Check bucket configuration."}), 502

    asset = CommunityAsset(
        user_id=user_id,
        title=title,
        description=description or None,
        category=category,
        original_filename=original_filename,
        file_format=extension,
        storage_path=storage_path,
        file_size=len(file_bytes),
    )
    try:
        db.session.add(asset)
        db.session.commit()
    except Exception:
        db.session.rollback()
        # Avoid leaving an unlisted object in the bucket if the database insert fails.
        try:
            requests.delete(
                f"{project_url}/storage/v1/object/{bucket}",
                headers=_storage_headers(service_key, "application/json"),
                json={"prefixes": [storage_path]},
                timeout=30,
            )
        except requests.RequestException:
            current_app.logger.exception("Could not clean up an orphaned Supabase object.")
        current_app.logger.exception("Could not save community asset metadata.")
        return jsonify({"message": "Upload reached storage, but its details could not be saved."}), 500

    return jsonify({
        "message": "Community asset uploaded successfully.",
        "asset": _asset_json(asset),
    }), 201


@community_bp.get("/<int:asset_id>/download")
def get_asset_download_url(asset_id):
    config = _storage_config()
    if not config:
        return jsonify({"message": "Community storage is not configured on the server."}), 503

    asset = db.session.get(CommunityAsset, asset_id)
    if not asset:
        return jsonify({"message": "Community asset not found."}), 404

    project_url, service_key, bucket = config
    sign_url = f"{project_url}/storage/v1/object/sign/{bucket}/{asset.storage_path}"
    try:
        response = requests.post(
            sign_url,
            headers=_storage_headers(service_key, "application/json"),
            json={"expiresIn": SIGNED_URL_SECONDS},
            timeout=20,
        )
    except requests.RequestException:
        current_app.logger.exception("Supabase signed URL request failed.")
        return jsonify({"message": "Could not create a download link. Please try again."}), 502

    if response.status_code not in (200, 201):
        current_app.logger.error("Supabase signed URL failed: %s", _storage_error(response))
        return jsonify({"message": "Could not create a download link for this asset."}), 502

    signed_path = (response.json() or {}).get("signedURL")
    if not signed_path:
        return jsonify({"message": "Storage did not return a download link."}), 502
    if signed_path.startswith("http://") or signed_path.startswith("https://"):
        download_url = signed_path
    else:
        download_url = f"{project_url}/storage/v1{signed_path if signed_path.startswith('/') else '/' + signed_path}"

    asset.downloads_count += 1
    db.session.commit()
    return jsonify({"download_url": download_url, "expires_in": SIGNED_URL_SECONDS}), 200


@community_bp.delete("/<int:asset_id>")
def delete_community_asset(asset_id):
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"message": "Please log in to delete a community asset."}), 401

    asset = CommunityAsset.query.filter_by(id=asset_id, user_id=user_id).first()
    if not asset:
        return jsonify({"message": "Asset not found or you do not own it."}), 404

    config = _storage_config()
    if not config:
        return jsonify({"message": "Community storage is not configured on the server."}), 503

    project_url, service_key, bucket = config
    try:
        response = requests.delete(
            f"{project_url}/storage/v1/object/{bucket}",
            headers=_storage_headers(service_key, "application/json"),
            json={"prefixes": [asset.storage_path]},
            timeout=30,
        )
    except requests.RequestException:
        current_app.logger.exception("Supabase delete request failed.")
        return jsonify({"message": "Could not reach cloud storage. Asset was not deleted."}), 502

    if response.status_code not in (200, 204):
        current_app.logger.error("Supabase delete failed: %s", _storage_error(response))
        return jsonify({"message": "Cloud storage could not delete this file."}), 502

    db.session.delete(asset)
    db.session.commit()
    return jsonify({"message": "Community asset deleted successfully."}), 200
