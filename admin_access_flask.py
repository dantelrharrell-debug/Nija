"""Shared authenticated administrator routes and dashboard boundaries for Flask."""

from __future__ import annotations

from typing import Any

from flask import g, jsonify, request

from admin_access import (
    AccessDenied, authenticate_bearer, is_owner, permission_summary,
    require_administrator, set_administrator,
)


def install_admin_access(app: Any, dashboard: str = "", protected_prefixes: tuple[str, ...] = ()) -> None:
    """Protect admin surfaces and expose owner-only grant/revoke endpoints.

    Personal read-only dashboard requests require a matching login ID.
    The legacy personal ``platform`` records are accessible to Dante or an
    explicitly delegated administrator, not anyone named ``platform``.
    """
    @app.before_request
    def administrator_boundary() -> Any:
        path = request.path
        if dashboard == "owner" and path == "/api/owner/login-config" and request.method == "GET":
            return None
        is_admin_route = path == "/api/admin" or path.startswith("/api/admin/")
        protected = is_admin_route or any(path.startswith(prefix) for prefix in protected_prefixes)
        if dashboard == "owner":
            protected = protected or path.startswith("/api/owner/")
        elif dashboard == "user":
            protected = protected or (path.startswith("/api/") and path != "/api/health")
        if not protected:
            return None
        # Preflight has no data or authority; browsers still must authenticate
        # the actual request. View functions are not invoked on OPTIONS.
        if request.method == "OPTIONS":
            return None
        try:
            actor = authenticate_bearer(request.headers.get("Authorization", ""))
            g.authenticated_user_id = actor
            if path == "/api/admin/me":
                return None
            if is_admin_route:
                require_administrator(actor, owner_only=True)
                return None
            if dashboard == "user" and request.method == "GET":
                target = (request.view_args or {}).get("user_id")
                if target == actor and target != "platform":
                    return None
                if target == "platform" and is_owner(actor):
                    return None
            require_administrator(actor)
        except AccessDenied as exc:
            return jsonify({"error": str(exc)}), exc.status_code
        return None

    @app.get("/api/admin/me")
    def administrator_identity() -> Any:
        try:
            return jsonify(permission_summary(g.authenticated_user_id))
        except AccessDenied as exc:
            return jsonify({"error": str(exc)}), exc.status_code

    @app.route("/api/admin/grants/<target_id>", methods=["POST", "DELETE"])
    def administrator_grant(target_id: str) -> Any:
        try:
            set_administrator(g.authenticated_user_id, target_id, request.method == "POST")
            return jsonify({"user_id": target_id, "administrator_granted": request.method == "POST"})
        except AccessDenied as exc:
            return jsonify({"error": str(exc)}), exc.status_code
