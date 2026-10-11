"""FastAPI routes for the same owner-only durable permission policy."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from admin_access import AccessDenied, authenticate_bearer, permission_summary, set_administrator


def install_admin_access(app: Any) -> None:
    """Expose authenticated identity and owner-only grant/revoke operations."""
    @app.get("/api/admin/me", tags=["admin"])
    def administrator_identity(request: Request) -> dict[str, Any]:
        try:
            actor = authenticate_bearer(request.headers.get("Authorization", ""))
            return permission_summary(actor)
        except AccessDenied as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/api/admin/grants/{target_id}", tags=["admin"])
    def grant_administrator(target_id: str, request: Request) -> dict[str, Any]:
        return change_grant(target_id, request, True)

    @app.delete("/api/admin/grants/{target_id}", tags=["admin"])
    def revoke_administrator(target_id: str, request: Request) -> dict[str, Any]:
        return change_grant(target_id, request, False)

    def change_grant(target_id: str, request: Request, grant: bool) -> dict[str, Any]:
        try:
            actor = authenticate_bearer(request.headers.get("Authorization", ""))
            set_administrator(actor, target_id, grant)
            return {"user_id": target_id, "administrator_granted": grant}
        except AccessDenied as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
