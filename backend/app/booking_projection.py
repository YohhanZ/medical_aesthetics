"""Only a scoped, current proposal is exposed; private snapshot stays encrypted."""

from typing import Any

from app.domain import Repository, now


def current_proposal(repo: Repository, row: dict[str, Any]) -> dict[str, Any] | None:
    proposal = repo.one(
        "SELECT id,proposed_version,snapshot_hash,proposed_at,expires_at FROM "
        "booking_change_proposal WHERE tenant_id=%s AND store_id=%s AND visitor_id=%s "
        "AND appointment_id=%s AND status='active' AND expires_at>now()",
        (row["tenant_id"], row["store_id"], row["visitor_id"], row["id"]),
    )
    if not proposal or proposal["proposed_version"] != row["version"]:
        return None
    return {
        "id": str(proposal["id"]),
        "version": proposal["proposed_version"],
        "snapshot_hash": proposal["snapshot_hash"],
        "proposed_at": proposal["proposed_at"].isoformat(),
        "expires_at": proposal["expires_at"].isoformat(),
        "expired": proposal["expires_at"] <= now(),
    }
