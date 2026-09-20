from flask import Blueprint, request, jsonify, session

from backend.extensions import db
from backend.models.project import Project


projects_bp = Blueprint(
    "projects",
    __name__,
    url_prefix="/api/projects"
)


@projects_bp.route("", methods=["POST"])
def create_project():

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "message": "Authentication required."
        }), 401

    data = request.get_json(silent=True) or {}

    name = data.get("name", "").strip()
    description = data.get("description", "").strip()

    if not name:
        return jsonify({
            "message": "Project name is required."
        }), 400

    new_project = Project(
        user_id=user_id,
        name=name,
        description=description
    )

    db.session.add(new_project)
    db.session.commit()

    return jsonify({
        "message": "Project created successfully.",
        "project": {
            "id": new_project.id,
            "name": new_project.name,
            "description": new_project.description
        }
    }), 201

@projects_bp.route("", methods=["GET"])
def get_projects():

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "message": "Authentication required."
        }), 401

    projects = Project.query.filter_by(
        user_id=user_id
    ).order_by(
        Project.updated_at.desc()
    ).all()

    return jsonify({
        "projects": [
            {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "created_at": project.created_at.isoformat(),
                "updated_at": project.updated_at.isoformat()
            }
            for project in projects
        ]
    }), 200

@projects_bp.route("/<int:project_id>", methods=["GET"])
def get_project(project_id):

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "message": "Authentication required."
        }), 401

    project = Project.query.filter_by(
        id=project_id,
        user_id=user_id
    ).first()

    if not project:
        return jsonify({
            "message": "Project not found."
        }), 404

    return jsonify({
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat()
        }
    }), 200

@projects_bp.route("/<int:project_id>", methods=["PUT"])
def update_project(project_id):

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "message": "Authentication required."
        }), 401

    project = Project.query.filter_by(
        id=project_id,
        user_id=user_id
    ).first()

    if not project:
        return jsonify({
            "message": "Project not found."
        }), 404

    data = request.get_json(silent=True) or {}

    name = data.get("name")
    description = data.get("description")

    if name is not None:
        name = name.strip()

        if not name:
            return jsonify({
                "message": "Project name cannot be empty."
            }), 400

        project.name = name

    if description is not None:
        project.description = description.strip()

    db.session.commit()

    return jsonify({
        "message": "Project updated successfully.",
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "created_at": project.created_at.isoformat(),
            "updated_at": project.updated_at.isoformat()
        }
    }), 200

@projects_bp.route("/<int:project_id>", methods=["DELETE"])
def delete_project(project_id):

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "message": "Authentication required."
        }), 401

    project = Project.query.filter_by(
        id=project_id,
        user_id=user_id
    ).first()

    if not project:
        return jsonify({
            "message": "Project not found."
        }), 404

    db.session.delete(project)
    db.session.commit()

    return jsonify({
        "message": "Project deleted successfully."
    }), 200

@projects_bp.route("/<int:project_id>/data", methods=["PUT"])
def save_project_data(project_id):

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "message": "Authentication required."
        }), 401

    project = Project.query.filter_by(
        id=project_id,
        user_id=user_id
    ).first()

    if not project:
        return jsonify({
            "message": "Project not found."
        }), 404

    data = request.get_json(silent=True) or {}

    if "project_data" not in data:
        return jsonify({
            "message": "Project data is required."
        }), 400

    project.project_data = data["project_data"]

    db.session.commit()

    return jsonify({
        "message": "Project data saved successfully."
    }), 200

@projects_bp.route("/<int:project_id>/data", methods=["GET"])
def get_project_data(project_id):

    user_id = session.get("user_id")

    if not user_id:
        return jsonify({
            "message": "Authentication required."
        }), 401

    project = Project.query.filter_by(
        id=project_id,
        user_id=user_id
    ).first()

    if not project:
        return jsonify({
            "message": "Project not found."
        }), 404

    return jsonify({
        "project_data": project.project_data or {
            "objects": []
        }
    }), 200